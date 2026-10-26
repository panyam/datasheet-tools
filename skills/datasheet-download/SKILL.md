---
name: datasheet-download
description: Identify which board-part datasheets a review overlay needs, source the public PDFs (curl for TI/direct-serve vendors; the Playwright browser for bot-blocked vendors and distributor mirrors), store them under datasheets/<vendor>/<part>/<part>.pdf, and flag product briefs/summaries/fact-sheets as <part>_BRIEF.pdf. Upstream sibling of /datasheet-transcribe (this FETCHES the PDF; that reads values into a param seed). Use when asked to "download datasheets", "source the PDFs for <board>", "get datasheets via distributor", "which datasheets do we need", or to fill datasheets/ before transcription. Triggers: "datasheet download", "download datasheets", "source datasheets", "distributor datasheet", "get the PDFs".
---

# datasheet-download

Get a board's part datasheets onto disk so `/datasheet-transcribe` can read values from them. This skill
covers WHICH parts to source, WHERE to put the PDF, HOW to fetch it (including past anti-bot walls with
the Playwright browser), and how to flag a partial doc as `_BRIEF`.

## Corpus + tools (split repos)

- **Corpus on disk:** `$AGNI_DATASHEET_ROOT` (e.g. `~/work/hw/datasheets`). Layout:
  `$AGNI_DATASHEET_ROOT/<vendor>/<part>/<part>.pdf` plus doc-IR and `sources.yaml` / `index.yaml`.
- **Scripts:** `~/work/hw/datasheet-tools` (`genindex.py`, etc.). Export `AGNI_DATASHEET_ROOT` before
  running them. Legacy copies under `datasheets/tools/` still work but are deprecated.

## Confidentiality (C16) — say it, don't hide it
Datasheets are vendor-licensed, customer-boundary data. They live ONLY under
`$AGNI_DATASHEET_ROOT/<vendor>/<PART>/`. **Never commit a PDF anywhere.** Transcribed FACTS (a number + its
citation) are fine and go in `projects/<customer>/params/` via `/datasheet-transcribe`; the PDF stays local.

## 1. Identify what's needed
The need list comes from the overlay, not a guess:
- `designs/<name>/intake.md` → "What this unblocks: datasheet-join MPNs to source" (the interface anchors +
  power/protection/clock ICs).
- `reports/<design>/` items reading **needs-data** or an honest not-automated "unseeded" (each names the
  symbol its rule wants: `VRWM`, `ILIM`, `TSD`, `TJMAX`, `UVLO`, `PPM`, `DENSITY`, CAN `VSUP`, …).
- `make datasheets-status` → what is already extracted vs missing.
Cross off parts already in `datasheets/` and `params/`. Prioritise the ones that flip a BOUND (or bindable)
review item over device_class-only anchors. Group the survivors by vendor (drives the sourcing tier).

**Cross off on an EXACT device designation, never a prefix or substring.** A false hit drops the part
from the queue silently; a false miss costs one redundant download, so bias toward the miss. A trailing
variant letter (`A`, `B`, `P`, `S`) usually means a DIFFERENT document: `SN74LVC1G14` vs `SN74LVC1G08`,
`TPS4H000B` vs `TPS4H160`, `TCA9539A` vs `TCA9539`. The conflating pairs found so far, and the matcher
guidance, are in `datasheet-tools/docs/NEAR_MISSES.md` (and a copy may still live in the corpus).
Read it before writing an automated gap diff.

## 2. Storage convention (exact)
`$AGNI_DATASHEET_ROOT/<vendor>/<part_or_family>/<part>.pdf`
- `<vendor>` lowercase (`ti`, `nxp`, `adi`, `mps`, `littelfuse`, `kec`, `epson`, `kds`, `infineon`, `ublox`).
- Folder = the board part base (the datasheet-join key, e.g. `TPS22995`, `LMQ61460`), not the family lit name.
- **PDF stem == folder name** (the `datasheets-status` walker requires it). Family datasheets are fine
  (`tps746-q1.pdf` saved as `TPS74601/TPS74601.pdf`); keep the folder keyed to the board MPN.

## 3. Sourcing tiers (try cheapest first)
**Tier A — TI, direct via curl.** `https://www.ti.com/lit/ds/symlink/<name>.pdf` with a browser UA.
The base name often 404s — try the **automotive family** + `-q1`: `tps22995h-q1`, `tcan1043a-q1`,
`tps709-q1` (covers TPS70918), `tps746-q1` (covers TPS74601), `tlv733p-q1` (covers TLV73318), `ina226-q1`.
A 404 returns a tiny HTML body; a hit is a big `%PDF`. TI also hosts some non-TI-prefixed parts (e.g. TSM24CA).

**Tier B — direct-serve via curl** (browser UA + `-e https://www.google.com/`): Epson
`download.epsondevice.com/td/pdf/...`, u-blox `content.u-blox.com/...`, and distributor/standards mirrors
that serve raw PDFs (chipdip `static.chipdip.ru/lib/...`, IHS `4donline.ihs.com/...`, kvarci, LCSC's
`datasheet.lcsc.com` asset host).

**Tier C — bot-blocked, needs the Playwright browser** (curl returns 000/403 or a tiny HTML challenge):
analog.com (Akamai), nxp.com, **st.com**, **onsemi.com**, Littelfuse `assetdocs`, KEC, Mouser
(PerimeterX), MPS `documentview`, the LCSC viewer. Use the recipe in §4.
**The two block signatures differ and only one looks like a block.** onsemi answers `403` with a small
HTML challenge body. **ST refuses the connection outright: `http=000`, zero bytes**, which reads like a
network fault or a bad URL, so it invites pointless retrying and URL-hunting. Treat `000` from a vendor
host as Tier C, not as a broken link. Verified 2026-09-07: st.com served all four ST parts fine through
Playwright, including the two `content/ccc/resource/...` deep links pulled off a report.

**Tier D — NDA-gated, no public PDF:** Marvell, Qualcomm, most Samsung LPDDR/eMMC, NXP custom SoCs, the
full editions of parts whose public doc is only a brief. Do NOT fabricate from a search summary — report
these (save-path + product-page URL + which item they'd unblock) as a sourcing ask.

The `curl` helper (Tiers A/B):
```bash
UA='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36'
dl(){ mkdir -p "$1/$2"; o="$1/$2/$3"; curl -sL --max-time 90 -A "$UA" -e 'https://www.google.com/' -o "$o" "$4"; head -c4 "$o"|grep -q '%PDF' && echo "OK $(wc -c<"$o") $o" || { echo "BAD $o"; rm -f "$o"; }; }
# dl ti TPS22995 TPS22995.pdf https://www.ti.com/lit/ds/symlink/tps22995h-q1.pdf
```

## 4. Playwright recipe (Tier C)
The `plugin-playwright-playwright` MCP tool `browser_run_code_unsafe` runs a snippet with a real Chromium
`page`. Two hard constraints learned the hard way:
- **The sandbox has no `require`, no dynamic `import`, no `fs`, and no `URL` global.** You cannot write
  files yourself. Use Playwright's own `download.saveAs(absPath)` — it writes server-side AND creates parent
  dirs. Parse origins with a regex, not `new URL()`.
- **A plain anchor to a cross-origin or inline PDF navigates instead of downloading** (no `download`
  event). The reliable trigger is an **in-page `fetch()` → blob → object-URL anchor**: it runs same-origin
  (so it clears the anti-bot cookie wall) and a `blob:` download ALWAYS fires the event.

Core downloader (navigate to the vendor origin first so cookies/challenge clear, then blob-fetch the PDF):
```js
async (page) => {
  await page.goto(ORIGIN_OR_PRODUCT_PAGE, {waitUntil:'domcontentloaded', timeout:60000}).catch(()=>{});
  await page.waitForTimeout(3000);
  const [dl] = await Promise.all([
    page.waitForEvent('download', {timeout:60000}),
    page.evaluate(async (u) => {
      const r = await fetch(u, {credentials:'include'}); if(!r.ok) throw new Error('http '+r.status);
      const b = await r.blob();
      const h = new Uint8Array(await b.slice(0,4).arrayBuffer());
      if(!(h[0]===0x25&&h[1]===0x50&&h[2]===0x44&&h[3]===0x46)) throw new Error('not pdf '+b.size); // %PDF
      const a = document.createElement('a'); a.href = URL.createObjectURL(b); a.download='x.pdf';
      document.body.appendChild(a); a.click();
    }, PDF_URL)
  ]);
  await dl.saveAs('/abs/path/to/corpus/<vendor>/<PART>/<PART>.pdf'); // under AGNI_DATASHEET_ROOT
  return 'OK';
}
```
Per-vendor quirks (the PDF_URL / navigation that works):
- **NXP:** product page `nxp.com/products/<PART>`; PDF `nxp.com/docs/en/data-sheet/<DOC>.pdf` (fact sheet =
  `.../fact-sheet/<DOC>.pdf`). Same-origin anchor-download also works here.
- **ADI (analog.com):** navigate `analog.com/` (or the product page); PDF `analog.com/media/en/technical-documentation/data-sheets/<file>.pdf`. If the exact file is unknown, open `analog.com/en/products/<part>.html`, scrape `a[href]` matching `/media/.*\.pdf/`, pick it.
- **MPS:** product page `monolithicpower.com/en/<part>-aec1.html`; scrape the `a[href]` containing
  `documentview` + `Datasheet`, then blob-fetch it.
- **Littelfuse:** navigate `littelfuse.com/`; PDF is the `assetdocs/...datasheet?assetguid=...` link (scrape
  it off the product page for series you don't have the guid for).
- **KEC:** product page `keccorp.com/en/product/product_view.asp?idx=<N>`; the datasheet is served via
  `keccorp.com/kr/product/image_product.asp?gu=1&idx=<N>` (NOT the `file_down(id,'n')` calls — those are
  package/packing images). Blob-fetch the `image_product` URL.
- **LCSC (viewer + cross-origin asset):** the `lcsc.com/datasheet/<Ccode>.pdf` link is an HTML viewer that
  loads the real PDF in an iframe. `goto` the viewer, wait ~8s, then read the asset URL off the page:
  `page.$$eval('iframe', els => els.map(e => e.src).filter(s => /^https:\/\/datasheet\.lcsc\.com\//.test(s)))`
  (shape: `https://datasheet.lcsc.com/datasheet/pdf/<hash>.pdf?productCode=<Ccode>`). Fetch that URL with the
  Tier B curl helper, or have the user open it and save it. **Do not blob-fetch it in the browser:**
  `datasheet.lcsc.com/` redirects to `www.lcsc.com`, so the fetch is cross-origin and fails CORS
  (`TypeError: Failed to fetch`). If you capture responses instead, filter to `https://datasheet.lcsc.com/`:
  Chrome's own PDF viewer also shows up as an `application/pdf` response, at a `chrome-extension://` URL.
  Verified 2026-10-26 (DSX321G / C93235).

If the exact PDF URL is unknown, prefer **scraping the product page** for the datasheet anchor over guessing
filenames. Run one vendor origin per `browser_run_code_unsafe` call to stay under the MCP timeout; do heavy
sites (analog.com) one part at a time. Close with `browser_close` when done.

**Playwright writes `.playwright-mcp/` into its CWD** (console logs plus the downloaded blob as `x.pdf`).
Run Playwright with CWD = `$AGNI_DATASHEET_ROOT` so `.playwright-mcp/` is not mistaken for a vendor;
`datasheetstatus` walks that folder as a VENDOR, so it shows up in
`make datasheets-status` as a not-extracted part. It is gitignored, so nothing is committed, but
`rm -rf .playwright-mcp` before regenerating the index or the issues rollup is wrong.

## 5. Verify every file
A download is only real if it starts with `%PDF`. Reject small HTML error/challenge pages.
```bash
head -c4 "$f" | grep -q '%PDF' || echo "NOT A PDF"
mdls -name kMDItemNumberOfPages "$f"   # page count — feeds the _BRIEF decision
```

## 6. Classify `_BRIEF`
Rename to `<part>_BRIEF.pdf` when the PDF is a **product brief, product summary, fact sheet, or preview** —
i.e. it lacks a real Electrical Characteristics / Recommended Operating Conditions section, or the full
datasheet sits behind an access program (e.g. Infineon SEMPER). Tells: very few pages, "brief"/"summary"/
"fact sheet"/"preview"/"product summary" in the title or URL path (`/brief/`), or "contact your sales office
/ NDA required for full specifications". A short-but-complete overview datasheet that DOES carry electricals
(e.g. a 10-page crystal or flash overview) keeps the plain `<part>.pdf` name — note the caveat instead of
flagging. A full datasheet that merely covers a family (`tps746-q1` for TPS74601) is NOT a brief.

## 7. Record provenance
For every file fetched, add a record to `$AGNI_DATASHEET_ROOT/sources.yaml` keyed by the `pdf` path
(`url` + `access` + `download_method`). `genindex.py` merges it into `index.yaml` as
`source_url`/`access`/`download_method` (an entry with no record shows `unknown`). Values:
`access: public | public-mirror | gated | nda`; `download_method: direct | js | playwright | none`.
Then regenerate (from `datasheet-tools`, with `AGNI_DATASHEET_ROOT` set):
`python3 tools/genindex.py /tmp/idx.json "$AGNI_DATASHEET_ROOT/index.yaml" <YYYY-MM-DD>`
(diff first; it should be additions-only). Do NOT hand-edit `index.yaml` — it is regenerated.

## 8. Report + hand off
Emit a table: `saved-path | part | source (curl/browser/mirror) | full|_BRIEF|GATED | which review item it
unblocks`. List the Tier-D gated parts as an explicit sourcing ask. Then hand off to
`/datasheet-transcribe` (`make pdf2doc-all` → read values → `params/*.textproto`), which is the step that
actually flips the review items. Do NOT commit any PDF.
