#!/usr/bin/env python3
"""Build a public-download manifest from index.yaml (and optional sources.yaml).

The full corpus index may include gated briefs, NDA parts, or unknown access. This tool
copies document entries whose `access` is in the public set (default: public, public-mirror)
and optionally requires source_url and has_electrical.

Outputs are meant for rebuild automation (download skill, CI mirrors), not as a replacement
for the internal index. See docs/corpus-rebuild.md.

Usage:
  export AGNI_DATASHEET_ROOT=path_to_your_datasheets_folder
  python3 tools/filter_index_public.py
  python3 tools/filter_index_public.py --index /path/index.yaml --out /path/index.public.yaml
  python3 tools/filter_index_public.py --sources --require-url --require-electrical
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from genindex import load_sidecar, resolve_corpus_root, yq


PUBLIC_ACCESS_DEFAULT = frozenset({"public", "public-mirror"})


def _unquote_scalar(raw: str) -> Any:
    raw = raw.strip()
    if raw.startswith('"') and raw.endswith('"'):
        inner = raw[1:-1].replace('\\"', '"').replace("\\\\", "\\")
        return inner
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1].strip()
        if not inner:
            return []
        return [t.strip().strip('"') for t in inner.split(",")]
    if raw.lower() in ("true", "false"):
        return raw.lower() == "true"
    if re.fullmatch(r"-?\d+", raw):
        return int(raw)
    return raw


def parse_index_documents(path: str) -> Tuple[List[str], List[Dict[str, Any]], List[str]]:
    """Return (preamble lines before documents, document dicts, tail from issues onward)."""
    with open(path, errors="replace") as fh:
        lines = fh.readlines()

    doc_start = None
    issues_start = None
    for i, line in enumerate(lines):
        if line.strip() == "documents:":
            doc_start = i
        if doc_start is not None and line.startswith("# --- issues"):
            issues_start = i
            break

    if doc_start is None:
        raise SystemExit(f"{path}: no documents: section found")

    preamble = lines[:doc_start]
    body_end = issues_start if issues_start is not None else len(lines)
    tail = lines[issues_start:] if issues_start is not None else []

    docs: List[Dict[str, Any]] = []
    cur: Optional[Dict[str, Any]] = None
    for line in lines[doc_start + 1 : body_end]:
        if not line.strip():
            continue
        m = re.match(r"^  - pdf:\s*(.+)$", line)
        if m:
            if cur:
                docs.append(cur)
            cur = {"pdf": _unquote_scalar(m.group(1).strip())}
            continue
        m = re.match(r"^    (\w+):\s*(.*)$", line)
        if m and cur is not None:
            key, rest = m.group(1), m.group(2).strip()
            if rest.startswith("#"):
                continue
            cur[key] = _unquote_scalar(rest.split("#", 1)[0].strip())
    if cur:
        docs.append(cur)
    return preamble, docs, tail


def document_lines(doc: Dict[str, Any]) -> List[str]:
    """Serialize one document entry (field order stable enough for diffs)."""
    order = [
        "pdf",
        "vendor",
        "filed_under",
        "doc_ir",
        "content_hash",
        "kind",
        "pages",
        "doc_number",
        "published",
        "revised",
        "title",
        "has_electrical",
        "source_url",
        "access",
        "download_method",
        "covers",
        "variants",
        "extracted",
        "note",
    ]
    seen = set()
    out = [f"  - pdf: {yq(doc['pdf'])}\n"]
    for key in order:
        if key == "pdf" or key not in doc:
            continue
        seen.add(key)
        val = doc[key]
        if isinstance(val, bool):
            out.append(f"    {key}: {'true' if val else 'false'}\n")
        elif isinstance(val, list):
            items = ", ".join(yq(str(x)) for x in val)
            out.append(f"    {key}: [{items}]\n")
        else:
            out.append(f"    {key}: {yq(val)}\n")
    for key in sorted(doc):
        if key in seen or key == "pdf":
            continue
        val = doc[key]
        if isinstance(val, list):
            items = ", ".join(yq(str(x)) for x in val)
            out.append(f"    {key}: [{items}]\n")
        else:
            out.append(f"    {key}: {yq(val)}\n")
    out.append("\n")
    return out


def filter_documents(
    docs: List[Dict[str, Any]],
    *,
    access_ok: frozenset[str],
    require_url: bool,
    require_electrical: bool,
) -> List[Dict[str, Any]]:
    kept: List[Dict[str, Any]] = []
    for d in docs:
        acc = str(d.get("access", "unknown")).lower()
        if acc not in access_ok:
            continue
        if require_url and not d.get("source_url"):
            continue
        if require_electrical and not d.get("has_electrical"):
            continue
        kept.append(d)
    return kept


def write_sources_public(
    corpus_root: str,
    pdf_paths: frozenset[str],
    out_path: str,
) -> int:
    src_path = os.path.join(corpus_root, "sources.yaml")
    side = load_sidecar(src_path)
    lines = [
        "# Filtered from sources.yaml — public rebuild manifest only.\n",
        "# Regenerate with tools/filter_index_public.py --sources\n",
        "sources:\n",
    ]
    count = 0
    for pdf in sorted(pdf_paths):
        rec = side.get(pdf)
        if not rec:
            continue
        count += 1
        lines.append(f'  "{pdf}":\n')
        for k in ("url", "access", "download_method"):
            if k in rec:
                lines.append(f"    {k}: {yq(rec[k])}\n")
    with open(out_path, "w") as fh:
        fh.writelines(lines)
    return count


def write_overrides_public(
    corpus_root: str,
    pdf_paths: frozenset[str],
    out_path: str,
) -> int:
    """Copy overrides.yaml records for the kept pdfs, line for line.

    Verbatim rather than re-serialized: load_sidecar keeps quoted values raw (escapes included),
    so passing them back through yq would double-escape titles.
    """
    src_path = os.path.join(corpus_root, "overrides.yaml")
    lines = [
        "# Filtered from overrides.yaml — judgment corrections for the public rebuild.\n",
        "# Copy to <corpus>/overrides.yaml before genindex. Regenerate with\n",
        "# tools/filter_index_public.py --sources\n",
        "overrides:\n",
    ]
    count, keep = 0, False
    if os.path.exists(src_path):
        with open(src_path, errors="replace") as fh:
            for raw in fh:
                m = re.match(r'^  "([^"]+)":\s*$', raw)
                if m:
                    keep = m.group(1) in pdf_paths
                    if keep:
                        count += 1
                        lines.append(raw)
                elif keep and re.match(r"^    \w+:", raw):
                    lines.append(raw)
                elif not raw.startswith(" "):
                    keep = False
    with open(out_path, "w") as fh:
        fh.writelines(lines)
    return count


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--index",
        help="Input index.yaml (default: $AGNI_DATASHEET_ROOT/index.yaml)",
    )
    ap.add_argument(
        "--out",
        help="Output index (default: <corpus>/index.public.yaml)",
    )
    ap.add_argument(
        "--access",
        default="public,public-mirror",
        help="Comma-separated access values to keep (default: public,public-mirror)",
    )
    ap.add_argument(
        "--require-url",
        action="store_true",
        help="Drop entries with no source_url",
    )
    ap.add_argument(
        "--require-electrical",
        action="store_true",
        help="Drop entries with has_electrical: false",
    )
    ap.add_argument(
        "--sources",
        action="store_true",
        help="Also write sources.public.yaml and overrides.public.yaml beside the index output",
    )
    args = ap.parse_args()

    corpus = resolve_corpus_root()
    index_in = args.index or os.path.join(corpus, "index.yaml")
    index_out = args.out or os.path.join(corpus, "index.public.yaml")
    access_ok = frozenset(a.strip().lower() for a in args.access.split(",") if a.strip())

    preamble, docs, tail = parse_index_documents(index_in)
    kept = filter_documents(
        docs,
        access_ok=access_ok,
        require_url=args.require_url,
        require_electrical=args.require_electrical,
    )

    banner = [
        "# PUBLIC MANIFEST — subset of index.yaml for download/rebuild automation.\n",
        "# Do not hand-edit; regenerate with tools/filter_index_public.py\n",
        f"# Source: {index_in}\n",
        f"# Kept {len(kept)} / {len(docs)} documents (access in {sorted(access_ok)}",
    ]
    if args.require_url:
        banner[-1] += ", require_url"
    if args.require_electrical:
        banner[-1] += ", require_electrical"
    banner[-1] += ").\n\n"

    out_lines = banner + preamble
    out_lines.append("documents:\n")
    for doc in kept:
        out_lines.extend(document_lines(doc))
    out_lines.append(
        "# --- issues (not recomputed; see full index.yaml) -----------------------\n"
    )
    out_lines.append("issues:\n")
    out_lines.append("  note: \"Run genindex on the full corpus for duplicate/not_extracted lists.\"\n")

    def _write_line(fh, line: str) -> None:
        fh.write(line if line.endswith("\n") else line + "\n")

    os.makedirs(os.path.dirname(os.path.abspath(index_out)), exist_ok=True)
    with open(index_out, "w") as fh:
        for line in out_lines:
            _write_line(fh, line)

    print(f"wrote {index_out} ({len(kept)}/{len(docs)} documents)")

    if args.sources:
        pdfs = frozenset(str(d["pdf"]) for d in kept)
        sources_out = os.path.join(os.path.dirname(index_out), "sources.public.yaml")
        n = write_sources_public(corpus, pdfs, sources_out)
        print(f"wrote {sources_out} ({n} source records)")
        overrides_out = os.path.join(os.path.dirname(index_out), "overrides.public.yaml")
        n = write_overrides_public(corpus, pdfs, overrides_out)
        print(f"wrote {overrides_out} ({n} override records)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
