#!/usr/bin/env python3
"""Index of the Part Knowledge / Published mirror, and what of it is local.

The upstream corpus is 13,032 PDFs / 17 GB on SharePoint, so the mirror at
$PK_ROOT is LAZY: this tool knows about every remote file and fetches nothing.
`status` and `find` are pure local reads and need no browser. `plan` writes a
fetch list that browser-automation's `sp_fetch` action consumes, because only
that side holds the authenticated session.

  build    (re)build mirror.db from _mirror_manifest.json + 00-Index.xlsx
  scan     re-check which files are present on disk
  status   counts and bytes, local vs remote
  find     resolve a part number or filename to documents, with local state
  plan     write a fetch list (by part, supplier, or filename)
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

PK_ROOT = Path(os.environ.get("PK_ROOT", Path.home() / "work/hw/Published"))
DB = PK_ROOT / "_index/mirror.db"
DATASHEETS = PK_ROOT / "Datasheets"
MANIFEST = DATASHEETS / "_mirror_manifest.json"
XLSX = PK_ROOT / "00-Index.xlsx"


def k1(pn: str) -> str:
    """Upper-cased alnum key, the join the ESR stores use ('1N4004-E3/54' -> '1N4004E354')."""
    return "".join(c for c in (pn or "").upper() if c.isalnum())


def connect() -> sqlite3.Connection:
    DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
  rel TEXT PRIMARY KEY, sru TEXT, supplier TEXT, filename TEXT,
  remote_bytes INTEGER, local INTEGER DEFAULT 0, local_bytes INTEGER, fetched_at TEXT);
CREATE INDEX IF NOT EXISTS files_supplier ON files(supplier);
CREATE INDEX IF NOT EXISTS files_filename ON files(filename);

CREATE TABLE IF NOT EXISTS parts (
  k1 TEXT, mfr_pn TEXT, supplier TEXT, component_type TEXT, library_pn TEXT,
  catalog_pn TEXT, filename TEXT, supplier_folder TEXT, rel TEXT,
  datasheet_url TEXT, parts_on_pdf INTEGER, cache_key TEXT, source TEXT);
CREATE INDEX IF NOT EXISTS parts_k1 ON parts(k1);
CREATE INDEX IF NOT EXISTS parts_rel ON parts(rel);

CREATE TABLE IF NOT EXISTS docs (
  rel TEXT PRIMARY KEY, filename TEXT, supplier_folder TEXT, parts_on_pdf INTEGER,
  component_types TEXT, example_pns TEXT, datasheet_url TEXT, cache_key TEXT);

CREATE TABLE IF NOT EXISTS unmapped (
  cache_key TEXT PRIMARY KEY, filename TEXT, size_bytes INTEGER, rel TEXT);

CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""


def _sheet_rows(wb, name):
    ws = wb[name]
    it = ws.iter_rows(values_only=True)
    hdr = [str(c) if c is not None else "" for c in next(it)]
    for row in it:
        yield dict(zip(hdr, row))


def cmd_build(args):
    if not MANIFEST.is_file():
        sys.exit(f"no manifest at {MANIFEST}; run sp_mirror --enumerate-only first")
    con = connect()
    con.executescript(SCHEMA)

    man = json.loads(MANIFEST.read_text())
    rows = []
    for it in man["items"]:
        rel = it["rel"]
        rows.append((rel, it["sru"], rel.split("/")[0] if "/" in rel else "",
                     rel.rsplit("/", 1)[-1], it["len"]))
    con.execute("DELETE FROM files")
    con.executemany(
        "INSERT OR REPLACE INTO files(rel,sru,supplier,filename,remote_bytes) VALUES (?,?,?,?,?)", rows)
    print(f"files: {len(rows)}")

    if XLSX.is_file():
        import openpyxl
        wb = openpyxl.load_workbook(XLSX, read_only=True, data_only=True)

        n = 0
        con.execute("DELETE FROM parts")
        for r in _sheet_rows(wb, "By part"):
            pn = r.get("Manufacturer PN")
            if not pn:
                continue
            con.execute(
                "INSERT INTO parts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (k1(str(pn)), str(pn), r.get("Supplier"), r.get("Component type"),
                 r.get("Library PN"), r.get("Catalog PN"), r.get("Filename"),
                 r.get("Supplier folder"), r.get("Relative path"), r.get("Datasheet URL"),
                 r.get("Parts on this PDF"), r.get("Cache key"), r.get("Source")))
            n += 1
        print(f"parts: {n}")

        n = 0
        con.execute("DELETE FROM docs")
        for r in _sheet_rows(wb, "By document"):
            rel = r.get("Relative path")
            if not rel:
                continue
            con.execute(
                "INSERT OR REPLACE INTO docs VALUES (?,?,?,?,?,?,?,?)",
                (rel, r.get("Filename"), r.get("Supplier folder"), r.get("Parts on this PDF"),
                 r.get("Component types on this PDF"), r.get("Example PNs"),
                 r.get("Datasheet URL"), r.get("Cache key")))
            n += 1
        print(f"docs: {n}")

        n = 0
        con.execute("DELETE FROM unmapped")
        for r in _sheet_rows(wb, "Unmapped"):
            ck = r.get("Cache key")
            if not ck:
                continue
            con.execute("INSERT OR REPLACE INTO unmapped VALUES (?,?,?,?)",
                        (ck, r.get("Filename"), r.get("Size bytes"), r.get("Relative path")))
            n += 1
        print(f"unmapped: {n}")

        for k, v in (("index_xlsx_rows_parts", "25286"), ("manifest_files", str(len(rows))),
                     ("manifest_bytes", str(man["bytes"])), ("root", man["root"])):
            con.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (k, v))
    con.commit()
    cmd_scan(args)


def cmd_scan(args):
    con = connect()
    n_local = 0
    upd = []
    for r in con.execute("SELECT rel, remote_bytes FROM files"):
        p = DATASHEETS / r["rel"]
        if p.is_file():
            sz = p.stat().st_size
            upd.append((1, sz, r["rel"]))
            n_local += 1
        else:
            upd.append((0, None, r["rel"]))
    con.executemany("UPDATE files SET local=?, local_bytes=? WHERE rel=?", upd)
    con.commit()
    print(f"scanned: {n_local} local of {len(upd)}")


def cmd_status(args):
    con = connect()
    q = con.execute("SELECT COUNT(*) n, SUM(remote_bytes) b, SUM(local) l, "
                    "SUM(CASE WHEN local=1 THEN remote_bytes ELSE 0 END) lb FROM files").fetchone()
    print(f"remote : {q['n']:>6} files  {(q['b'] or 0)/1e9:8.2f} GB")
    print(f"local  : {q['l']:>6} files  {(q['lb'] or 0)/1e9:8.2f} GB "
          f"({(q['l'] or 0)/max(q['n'],1)*100:.1f}%)")
    mism = con.execute("SELECT COUNT(*) n FROM files WHERE local=1 AND local_bytes<>remote_bytes").fetchone()["n"]
    if mism:
        print(f"SIZE MISMATCH on {mism} local files (re-fetch with `plan --mismatched`)")
    print(f"parts  : {con.execute('SELECT COUNT(*) n FROM parts').fetchone()['n']} rows, "
          f"{con.execute('SELECT COUNT(DISTINCT k1) n FROM parts').fetchone()['n']} distinct k1")
    print(f"docs   : {con.execute('SELECT COUNT(*) n FROM docs').fetchone()['n']}")
    print(f"unmapped: {con.execute('SELECT COUNT(*) n FROM unmapped').fetchone()['n']}")
    print("\ntop suppliers by remote files (local/total):")
    for r in con.execute("SELECT supplier, COUNT(*) n, SUM(local) l, SUM(remote_bytes) b "
                         "FROM files GROUP BY supplier ORDER BY n DESC LIMIT 15"):
        print(f"  {r['supplier'][:34]:36s} {r['l'] or 0:>5}/{r['n']:<6} {(r['b'] or 0)/1e6:8.0f} MB")


def _find(con, term, prefix=False):
    """Exact k1 match only, unless prefix is asked for explicitly.

    A prefix match conflates devices: `BSS138` has no exact row here, and
    expanding it hits 36 orderables spanning BSS138 (50 V / 200 mA) and
    BSS138BK (60 V / 360 mA). See NEAR_MISSES.md — a false HIT silently drops a
    part from the work queue, so this biases toward the false miss and makes the
    caller ask for the fan-out.
    """
    t = k1(term)
    rows = list(con.execute(
        "SELECT p.*, f.local, f.remote_bytes FROM parts p LEFT JOIN files f ON f.rel=p.rel "
        "WHERE p.k1=? ORDER BY p.mfr_pn", (t,)))
    if rows or not prefix:
        return rows, False
    rows = list(con.execute(
        "SELECT p.*, f.local, f.remote_bytes FROM parts p LEFT JOIN files f ON f.rel=p.rel "
        "WHERE p.k1 LIKE ? ORDER BY p.mfr_pn", (t + "%",)))
    return rows, True


def cmd_find(args):
    con = connect()
    for term in args.term:
        rows, fanned = _find(con, term, prefix=args.prefix)
        note = "  PREFIX FAN-OUT — may span different devices" if fanned else ""
        print(f"\n=== {term}  ({len(rows)} part row(s)){note}")
        if not rows:
            n = con.execute("SELECT COUNT(*) n FROM parts WHERE k1 LIKE ?",
                            (k1(term) + "%",)).fetchone()["n"]
            if n and not args.prefix:
                print(f"  no exact k1 match; {n} row(s) share this prefix. "
                      f"Re-run with --prefix to see them (they may be other devices).")
            d = list(con.execute("SELECT rel, supplier_folder, parts_on_pdf, example_pns FROM docs "
                                 "WHERE filename LIKE ? LIMIT 10", (f"%{term}%",)))
            if d:
                print("  no part row; filename matches:")
                for r in d:
                    print(f"    {r['rel']}  parts={r['parts_on_pdf']}  eg {str(r['example_pns'])[:50]}")
            continue
        for r in rows:
            state = "LOCAL " if r["local"] else "remote"
            mb = (r["remote_bytes"] or 0) / 1e6
            print(f"  {r['mfr_pn']:<26} {str(r['supplier'])[:16]:<18} {str(r['component_type'] or '-')[:14]:<16} "
                  f"{state} {mb:6.2f}MB  parts_on_pdf={r['parts_on_pdf']}")
            print(f"      rel: {r['rel']}")
            if args.url:
                print(f"      url: {r['datasheet_url']}")


def cmd_plan(args):
    con = connect()
    rels = []
    if args.mismatched:
        rels += [r["rel"] for r in con.execute(
            "SELECT rel FROM files WHERE local=1 AND local_bytes<>remote_bytes")]
    for s in args.supplier or []:
        rels += [r["rel"] for r in con.execute(
            "SELECT rel FROM files WHERE supplier=? AND local=0", (s,))]
    for t in args.part or []:
        rows, fanned = _find(con, t, prefix=args.prefix)
        if fanned:
            print(f"WARNING {t}: no exact match, planning {len(rows)} prefix row(s) "
                  f"that may be different devices")
        rels += [r["rel"] for r in rows if r["rel"] and not r["local"]]
    for f in args.file or []:
        rels += [r["rel"] for r in con.execute(
            "SELECT rel FROM files WHERE (rel=? OR filename=?) AND local=0", (f, f))]
    seen, out = set(), []
    for r in rels:
        if r and r not in seen:
            seen.add(r)
            out.append(r)
    if args.limit:
        out = out[: args.limit]
    tot = con.execute(
        f"SELECT SUM(remote_bytes) b FROM files WHERE rel IN ({','.join('?' * len(out))})", out
    ).fetchone()["b"] if out else 0
    Path(args.out).write_text("\n".join(out) + ("\n" if out else ""))
    print(f"planned {len(out)} file(s), {(tot or 0)/1e6:.1f} MB -> {args.out}")
    if out:
        print("fetch with:")
        print(f"  cd ~/work/browser-automation && uv run python run.py --headless "
              f"sp_fetch --list {args.out}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build")
    sub.add_parser("scan")
    sub.add_parser("status")
    f = sub.add_parser("find")
    f.add_argument("term", nargs="+")
    f.add_argument("--url", action="store_true")
    f.add_argument("--prefix", action="store_true",
                   help="allow prefix fan-out when no exact k1 row exists")
    p = sub.add_parser("plan")
    p.add_argument("--part", action="append")
    p.add_argument("--supplier", action="append")
    p.add_argument("--file", action="append")
    p.add_argument("--mismatched", action="store_true")
    p.add_argument("--prefix", action="store_true",
                   help="allow prefix fan-out for --part (may pull other devices)")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--out", default=str(PK_ROOT / "_index/fetch.list"))
    a = ap.parse_args()
    {"build": cmd_build, "scan": cmd_scan, "status": cmd_status,
     "find": cmd_find, "plan": cmd_plan}[a.cmd](a)


if __name__ == "__main__":
    main()
