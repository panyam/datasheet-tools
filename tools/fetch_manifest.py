#!/usr/bin/env python3
"""Download PDFs listed in a sources sidecar (e.g. sources.public.yaml) into the corpus tree.

Uses curl for download_method direct (and public-mirror when marked direct). Entries marked
playwright are skipped here; they need the browser recipe in skills/datasheet-download (or
run with --list-playwright and fetch those separately).

Usage:
  export AGNI_DATASHEET_ROOT=<your datasheets folder>
  python3 tools/fetch_manifest.py --manifest path_to_your_sources.yaml
  python3 tools/fetch_manifest.py --dry-run
  python3 tools/fetch_manifest.py --direct-only
  python3 tools/fetch_manifest.py --list-playwright /tmp/playwright.urls
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from genindex import load_sidecar, resolve_corpus_root

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
)


def is_pdf(path: Path) -> bool:
    try:
        with path.open("rb") as f:
            return f.read(4) == b"%PDF"
    except OSError:
        return False


def curl_fetch(url: str, dest: Path, *, dry_run: bool) -> tuple[str, str]:
    """Return (status, detail). status: ok | bad | skip | dry."""
    if dest.exists() and is_pdf(dest):
        return "skip", "already present"
    if dry_run:
        return "dry", url
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    cmd = [
        "curl",
        "-sL",
        "--max-time",
        "120",
        "-A",
        UA,
        "-e",
        "https://www.google.com/",
        "-o",
        str(tmp),
        url,
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        tmp.unlink(missing_ok=True)
        err = (e.stderr or b"").decode(errors="replace")[:200]
        return "bad", err or "curl failed"
    if not is_pdf(tmp):
        size = tmp.stat().st_size if tmp.exists() else 0
        tmp.unlink(missing_ok=True)
        return "bad", f"not a PDF ({size} bytes)"
    tmp.replace(dest)
    return "ok", f"{dest.stat().st_size} bytes"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--manifest",
        help="sources.yaml-shaped file (default: sources.public.yaml in cwd, then corpus root)",
    )
    ap.add_argument("--dry-run", action="store_true", help="Print actions only")
    ap.add_argument(
        "--direct-only",
        action="store_true",
        help="Fetch only direct/js entries; do not error on playwright rows",
    )
    ap.add_argument(
        "--force",
        action="store_true",
        help="Re-download even when a valid PDF already exists",
    )
    ap.add_argument(
        "--list-playwright",
        metavar="FILE",
        help="Write playwright-needed rows as: pdf_path<TAB>url",
    )
    args = ap.parse_args()

    corpus = resolve_corpus_root()
    manifest = args.manifest
    if not manifest:
        for candidate in (
            Path.cwd() / "sources.public.yaml",
            Path(__file__).resolve().parents[1] / "sources.public.yaml",
            Path(corpus) / "sources.public.yaml",
            Path(corpus) / "sources.yaml",
        ):
            if candidate.is_file():
                manifest = str(candidate)
                break
    if not manifest or not os.path.isfile(manifest):
        raise SystemExit(
            "No manifest found. Pass --manifest or place sources.public.yaml in the "
            "corpus root or datasheet-tools repo root."
        )

    rows = load_sidecar(manifest)
    if not rows:
        raise SystemExit(f"No entries parsed from {manifest}")

    playwright_queue: list[tuple[str, str]] = []
    stats = {"ok": 0, "skip": 0, "bad": 0, "dry": 0, "playwright": 0, "no_url": 0}

    for pdf_rel, rec in sorted(rows.items()):
        url = (rec.get("url") or "").strip()
        method = (rec.get("download_method") or "unknown").lower()
        dest = Path(corpus) / pdf_rel

        if not url:
            stats["no_url"] += 1
            print(f"NO_URL  {pdf_rel}")
            continue

        if method in ("playwright", "js"):
            stats["playwright"] += 1
            playwright_queue.append((pdf_rel, url))
            if not args.direct_only:
                print(f"PLAYWRIGHT  {pdf_rel}  ({method})")
            continue

        if method not in ("direct", "unknown"):
            stats["playwright"] += 1
            print(f"SKIP_METHOD {method}  {pdf_rel}")
            continue

        if not args.force and dest.exists() and is_pdf(dest):
            stats["skip"] += 1
            print(f"SKIP  {pdf_rel}")
            continue

        status, detail = curl_fetch(url, dest, dry_run=args.dry_run)
        stats[status if status in stats else "bad"] += 1
        tag = status.upper()
        print(f"{tag:4}  {pdf_rel}  {detail}")

    if args.list_playwright:
        with open(args.list_playwright, "w") as fh:
            for pdf_rel, url in playwright_queue:
                fh.write(f"{pdf_rel}\t{url}\n")
        print(f"wrote {len(playwright_queue)} playwright rows to {args.list_playwright}")

    print(
        f"\ndone: ok={stats['ok']} skip={stats['skip']} bad={stats['bad']} "
        f"dry={stats['dry']} playwright={stats['playwright']} no_url={stats['no_url']} "
        f"(manifest={manifest}, corpus={corpus})"
    )
    if stats["playwright"] and not args.direct_only:
        print(
            "Playwright rows were not fetched. Re-run with --direct-only after curl pass, "
            "or use --list-playwright and skills/datasheet-download (Tier C) for those URLs."
        )
    return 1 if stats["bad"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
