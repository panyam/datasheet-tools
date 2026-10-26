#!/usr/bin/env python3
"""Download manifest rows that need a browser (from fetch_manifest --list-playwright TSV).

Install once:
  python3 -m venv .venv && .venv/bin/pip install playwright
  .venv/bin/playwright install chromium

Usage:
  export AGNI_DATASHEET_ROOT=~/work/hw/datasheets
  .venv/bin/python tools/fetch_playwright_manifest.py /tmp/datasheet-playwright.tsv
  .venv/bin/python tools/fetch_playwright_manifest.py playwright.public.tsv --headed
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from pathlib import Path
from typing import List, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from genindex import resolve_corpus_root

BLOB_JS = """
async (pdfUrl) => {
  const r = await fetch(pdfUrl, {credentials: 'include'});
  if (!r.ok) throw new Error('http ' + r.status);
  const b = await r.blob();
  const h = new Uint8Array(await b.slice(0, 4).arrayBuffer());
  if (!(h[0] === 0x25 && h[1] === 0x50 && h[2] === 0x44 && h[3] === 0x46))
    throw new Error('not pdf ' + b.size);
  const a = document.createElement('a');
  a.href = URL.createObjectURL(b);
  a.download = 'x.pdf';
  document.body.appendChild(a);
  a.click();
}
"""


def origin(url: str) -> str:
    m = re.match(r"^(https?://[^/]+)", url)
    if not m:
        raise ValueError(f"bad url: {url}")
    return m.group(1)


def load_tsv(path: str) -> List[Tuple[str, str]]:
    rows: List[Tuple[str, str]] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t", 1)
            if len(parts) != 2:
                raise SystemExit(f"bad TSV line (need path<TAB>url): {line[:80]}")
            rows.append((parts[0].strip(), parts[1].strip()))
    return rows


def is_pdf(path: Path) -> bool:
    try:
        return path.open("rb").read(4) == b"%PDF"
    except OSError:
        return False


async def fetch_one(page, pdf_rel: str, url: str, dest: Path, *, lcsc_mode: bool) -> str:
    dest.parent.mkdir(parents=True, exist_ok=True)

    if lcsc_mode or "lcsc.com" in url:
        # Viewer page: capture real PDF URL from network, then blob-fetch on asset host.
        asset_urls: list[str] = []

        def on_response(resp):
            ct = resp.headers.get("content-type", "")
            if "application/pdf" in ct and "datasheet.lcsc.com" in resp.url:
                asset_urls.append(resp.url)

        page.on("response", on_response)
        await page.goto(url, wait_until="domcontentloaded", timeout=90000)
        await page.wait_for_timeout(8000)
        page.remove_listener("response", on_response)
        if not asset_urls:
            return "bad: no LCSC pdf response captured"
        url = asset_urls[-1]

    root = origin(url)
    await page.goto(root + "/", wait_until="domcontentloaded", timeout=90000)
    await page.wait_for_timeout(2500)

    try:
        async with page.expect_download(timeout=90000) as dl_info:
            await page.evaluate(BLOB_JS, url)
        download = await dl_info.value
        await download.save_as(str(dest))
    except Exception as e:
        return f"bad: {e}"

    if not is_pdf(dest):
        dest.unlink(missing_ok=True)
        return "bad: saved file is not PDF"
    return f"ok {dest.stat().st_size} bytes"


async def run(args) -> int:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print(
            "playwright not installed. From datasheet-tools:\n"
            "  python3 -m venv .venv && .venv/bin/pip install playwright\n"
            "  .venv/bin/playwright install chromium",
            file=sys.stderr,
        )
        return 2

    corpus = Path(resolve_corpus_root())
    rows = load_tsv(args.tsv)
    bad = 0

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=not args.headed)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
            ),
            accept_downloads=True,
        )
        page = await context.new_page()

        for pdf_rel, url in rows:
            dest = corpus / pdf_rel
            if not args.force and is_pdf(dest):
                print(f"SKIP  {pdf_rel}")
                continue
            lcsc = "lcsc.com" in url
            try:
                msg = await fetch_one(page, pdf_rel, url, dest, lcsc_mode=lcsc)
            except Exception as e:
                # Navigation errors (e.g. st.com dropping the connection) must not abort the batch.
                msg = f"bad: {str(e).splitlines()[0]}"
            print(f"{msg.split()[0].upper():4}  {pdf_rel}  {msg}")
            if msg.startswith("bad"):
                bad += 1

        await browser.close()

    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("tsv", help="path<TAB>url lines from fetch_manifest --list-playwright")
    ap.add_argument("--headed", action="store_true", help="show browser (debug anti-bot)")
    ap.add_argument("--force", action="store_true", help="re-download existing PDFs")
    args = ap.parse_args()
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
