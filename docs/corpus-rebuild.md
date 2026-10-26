# Corpus rebuild from the index

The corpus **`index.yaml`** is a catalog of documents (paths, hashes, covers/variants, access). It is **not** a one-click replay of PartSpecs, connectsmith spreadsheets, or review seeds.

## What the index can drive

| Step                  | Input                                        | Tool / skill                                                                                   |
|-----------------------|----------------------------------------------|------------------------------------------------------------------------------------------------|
| Pick public docs only | `index.yaml`                                 | `tools/filter_index_public.py` → `index.public.yaml` (+ optional `sources.public.yaml`, `overrides.public.yaml`)        |
| Download PDFs         | `source_url`, `download_method`, `pdf:` path | `skills/datasheet-download` or curl/Playwright                                                 |
| doc-IR                | PDF on disk                                  | Agni `pdf2doc` / workspace `make pdf2doc-all`                                                  |
| Refresh index         | doc-IR on disk                               | `tools/genindex.py` (needs `sources.yaml`, `overrides.yaml` for provenance and judgment fixes) |

Set **`AGNI_DATASHEET_ROOT`** to the corpus directory (see repo README).

```bash
export AGNI_DATASHEET_ROOT=~/datasheets # or path to your datasheets folder
export AGNI_DATASHEET_TOOLS_ROOT=~/datasheet-tools # or path to your datasheet-tools checkout folder
```

## Five-step loop (full internal corpus)

1. **Manifest** — Use the full `index.yaml` or a filtered `index.public.yaml` as the list of `pdf:` paths to restore.
2. **Download** — For each entry with a `source_url`, fetch into `$AGNI_DATASHEET_ROOT/<pdf>`. Skip `access: nda` and entries with no URL unless you have another source.
3. **Extract** — Run pdf2doc on missing or stale doc-IR (`*.doc.textproto` beside each PDF).
4. **Regenerate index** — From `datasheet-tools`:

   ```bash
   python3 tools/genindex.py /tmp/idx.json \
     "$AGNI_DATASHEET_ROOT/index.yaml" \
     "$(date +%Y-%m-%d)"
   ```

   Diff before commit; deterministic fields come from doc-IR. Provenance merges from **`sources.yaml`**; corrections from **`overrides.yaml`**.

5. **Params (separate track)** — Use **`variants`** / **`covers`** in the index to find which PDF applies to a BOM MPN. Seeding **`projects/<customer>/params/*.textproto`** is still per-board and per-symbol (hand transcribe or future derive). The index does not list which Agni symbols to fill.

## Public-only manifest

For mirrors or automation that must not depend on gated/NDA files:

```bash
python3 tools/filter_index_public.py --sources --require-url
```

Defaults keep `access: public` and `public-mirror`. Flags:

- **`--require-url`** — drop rows with no `source_url`
- **`--require-electrical`** — drop briefs / non-param docs (`has_electrical: false`)
- **`--access`** — override the allowlist (comma-separated)

Outputs default to **`index.public.yaml`**, **`sources.public.yaml`** and **`overrides.public.yaml`** under the corpus root. They do not remove PDFs already in git; they define what a public rebuild should fetch.

## Download everything in `sources.public.yaml`

Set the corpus root, then run the batch fetcher from **datasheet-tools** (manifest can live in the tools repo or under the corpus):

```bash
cd $AGNI_DATASHEET_TOOLS_ROOT

# Preview
python3 tools/fetch_manifest.py --manifest sources.public.yaml --dry-run

# curl all download_method: direct rows (skips valid PDFs already on disk)
python3 tools/fetch_manifest.py --manifest sources.public.yaml

# Only curl; write playwright rows for a follow-up browser pass
python3 tools/fetch_manifest.py --manifest sources.public.yaml --direct-only \
  --list-playwright /tmp/datasheet-playwright.tsv
```

**`direct`** entries are fetched with curl (browser user-agent, same idea as the download skill). **`playwright`** / **`js`** entries need a browser.

### Playwright batch (local Chromium)

One-time setup in **datasheet-tools**:

```bash
cd $AGNI_DATASHEET_TOOLS_ROOT
make setup   # uv venv + requirements.txt (playwright, docling) + bundled Chromium
```

Run against the TSV (CWD can be anywhere; corpus from `AGNI_DATASHEET_ROOT`):

```bash
.venv/bin/python tools/fetch_playwright_manifest.py /tmp/datasheet-playwright.tsv
```

Use **`--headed`** if a vendor blocks headless Chromium. **`--force`** re-fetches existing PDFs.

The script visits each URL’s **origin** first (cookie wall), then **blob-fetch** + `save_as` into `$AGNI_DATASHEET_ROOT/<pdf path>`. LCSC rows use the viewer → network capture path from the download skill.

What the script can and can't reach (2026-10-26): Littelfuse needs `--headed`. **ST** refuses the
bundled Chromium (`ERR_HTTP2_PROTOCOL_ERROR` after the first hit) and **LCSC** fails CORS (its asset
host's root redirects to `www.lcsc.com`, and headless now gets a 403 on the viewer). Fetch those two
through the Playwright MCP instead (next section), which drives a full Chrome.

### Playwright via MCP (Claude Code or Cursor)

If you use the **Playwright MCP** plugin instead, ask the agent to run **`browser_run_code_unsafe`** once **per row** (or per vendor origin), with **`saveAs`** set to the absolute path under `AGNI_DATASHEET_ROOT`. Use the blob-fetch snippet in **`skills/datasheet-download/SKILL.md` §4. The MCP writes `.playwright-mcp/` (logs plus each blob as `x.pdf`) into its CWD. Run it from **`$AGNI_DATASHEET_ROOT`** and it shows up as a fake vendor in the walkers. Run it from this repo and it lands here, where `.gitignore` covers it.

After PDFs land:

```bash
cd $AGNI_REPO_ROOT   # Agni lane checkout
make setup              # once: docling venv for pdf2doc
make pdf2doc-all        # writes <part>/<stem>.doc.textproto beside each PDF
make datasheets-status  # confirms extracted / stale
make pdf2doc-all    # runs Agni pdf2doc (AGNI_DIR, default ../main) with this repo's venv
# Provenance + judgment corrections; without overrides.yaml, titles/covers/has_electrical
# fall back to the generator's heuristic guesses.
cp sources.public.yaml "$AGNI_DATASHEET_ROOT/sources.yaml"
cp overrides.public.yaml "$AGNI_DATASHEET_ROOT/overrides.yaml"
python3 tools/genindex.py /tmp/idx.json \
  "$AGNI_DATASHEET_ROOT/index.yaml" "$(date +%Y-%m-%d)"
```

## PartSpec textprotos (what Checksmith / Agni rules use)

There are **two different** textproto layers. Do not confuse them.

| File | Where | Consumed by |
|------|--------|-------------|
| **`*.doc.textproto`** | Corpus next to PDF (`ti/LM1117/LM1117.doc.textproto`) | doc-IR / future **derive/**; index generation |
| **`*.textproto` PartSpec** | `projects/<customer>/params/` (or another `--params` dir) | **`param(mpn, SYMBOL, …)`** rules, review checklist, Checksmith via `PRANA` `--params` mount |

**Connectsmith** pull-up / IO-map data lives in **xlsx + JSON under Prana `tools/connectsmith/`**. It is **not** PartSpec and does not come from the corpus pipeline.

### Production path today (hand seed)

Automated **derive/** (doc-IR → PartSpec) exists in Agni but is **recipe-limited**; bulk extraction for your full public set is not a one-command product yet. The supported path matches **`skills/datasheet-transcribe`**:

1. **Board MPNs** — exact `Manufacturer PN` strings from the netlist (join key for `component.mpn`).
2. **Which symbols** — from the review overlay: start from existing **`mock-*.textproto`** / per-part seeds in `projects/.../params/` and from checklist items that call `param(mpn, TSD, …)`, `supply-exceeds-abs-max`, etc. Seeding a symbol enrols that MPN in every design-wide query that mentions it (see skill §5b).
3. **Read the sheet** — use doc-IR or PDF; record values with **`method: "hand"`** and full **`prov { page, table_or_figure, doc_ref }`**.
4. **Write PartSpec** — one file per part (often lowercase stem); **`mpn:` must match the netlist exactly** (ordering code, not family name from `index.yaml` `covers`).

Example shape (real seed):

```textproto
mpn: "TPS4H000BQPWPRQ1"
device_class: "efuse"
docs { id: "slvsd73b" title: "..." locator: "datasheets/ti/TPS4H000B/TPS4H000B.pdf" }
parameters {
  symbol: "TSD"
  limit_kind: LIMIT_KIND_CHARACTERISTIC
  value { max: 175 }
  unit: "degC"
  prov { doc_ref: "slvsd73b" page: 7 table_or_figure: "7.5 Electrical Characteristics -- T(SD) ..." method: "hand" confidence: 1.0 }
}
```

5. **Verify load** (no design required):

```bash
# Make sure agni is installed
agni params TPS4H000BQPWPRQ1 --params <path_to_params>
```

6. **Run review / Checksmith** with the same params mount (Prana `make serve` mounts `projects/.../params`, or `agni review --params ...`).

Use **`index.yaml` `variants`** to map a BOM MPN to the right PDF/doc-IR; use **`params/`** to store the numbers the engine checks.

### Later: derive/

When recipes cover a vendor family, **`derive.Run(doc-IR, recipes, patches, Identity)`** can emit PartSpec + manifest gaps. Today that is tested on fixtures (e.g. BSS138), not wired as `make derive-all` over the public corpus. Prefer hand seed for checklist-driven symbols until derive coverage is explicit.

## What this does not rebuild

- **PartSpec seeds** — keyed by exact MPN in `params/`; values and citations are not in the index.
- **Connectsmith / checksmith HTML curation** — IO map xlsx, IOMUX xlsx, `pullup_data/*.json`, IC validator Python under Prana `tools/connectsmith/`.
- **SemiAtlas / Part Knowledge mirror** — `pkindex.py` and SharePoint fetch (see HANDOFF docs in the corpus repo if present).
- **Review checklist items** — Agni review YAML and project overlays live in house-designs repos.

## MPN → document lookup (manual)

1. Take the exact BOM / netlist **Manufacturer PN**.
2. Scan index **`variants`** (ordering codes) for a case-insensitive match.
3. If none, check **`covers`** (family names on the sheet) and open the corresponding **`pdf:`**.
4. Seed **`PartSpec.mpn`** with that same ordering code (Agni join is exact; see `docs/NEAR_MISSES.md`).

## Access field reference

Merged from **`sources.yaml`** into each index document:

| `access` | Meaning |
|----------|---------|
| `public` | Vendor-hosted download |
| `public-mirror` | Distributor or third-party mirror |
| `gated` | Full sheet restricted; file may be a brief |
| `nda` | No public document |
| `unknown` | No `sources.yaml` record |
