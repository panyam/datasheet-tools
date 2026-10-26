# Corpus rebuild from the index

The corpus **`index.yaml`** is a catalog of documents (paths, hashes, covers/variants, access). It is **not** a one-click replay of PartSpecs, connectsmith spreadsheets, or review seeds.

## What the index can drive

| Step                  | Input                                        | Tool / skill                                                                                   |
|-----------------------|----------------------------------------------|------------------------------------------------------------------------------------------------|
| Pick public docs only | `index.yaml`                                 | `tools/filter_index_public.py` → `index.public.yaml` (+ optional `sources.public.yaml`)        |
| Download PDFs         | `source_url`, `download_method`, `pdf:` path | `skills/datasheet-download` or curl/Playwright                                                 |
| doc-IR                | PDF on disk                                  | Agni `pdf2doc` / workspace `make pdf2doc-all`                                                  |
| Refresh index         | doc-IR on disk                               | `tools/genindex.py` (needs `sources.yaml`, `overrides.yaml` for provenance and judgment fixes) |

Set **`AGNI_DATASHEET_ROOT`** to the corpus directory (see repo README).

## Five-step loop (full internal corpus)

1. **Manifest** — Use the full `index.yaml` or a filtered `index.public.yaml` as the list of `pdf:` paths to restore.
2. **Download** — For each entry with a `source_url`, fetch into `$AGNI_DATASHEET_ROOT/<pdf>`. Skip `access: nda` and entries with no URL unless you have another source.
3. **Extract** — Run pdf2doc on missing or stale doc-IR (`*.doc.textproto` beside each PDF).
4. **Regenerate index** — From `datasheet-tools`:

   ```bash
   export AGNI_DATASHEET_ROOT=~/work/hw/datasheets
   python3 tools/genindex.py /tmp/idx.json \
     "$AGNI_DATASHEET_ROOT/index.yaml" \
     "$(date +%Y-%m-%d)"
   ```

   Diff before commit; deterministic fields come from doc-IR. Provenance merges from **`sources.yaml`**; corrections from **`overrides.yaml`**.

5. **Params (separate track)** — Use **`variants`** / **`covers`** in the index to find which PDF applies to a BOM MPN. Seeding **`projects/<customer>/params/*.textproto`** is still per-board and per-symbol (hand transcribe or future derive). The index does not list which Agni symbols to fill.

## Public-only manifest

For mirrors or automation that must not depend on gated/NDA files:

```bash
export AGNI_DATASHEET_ROOT=~/work/hw/datasheets
python3 tools/filter_index_public.py --sources --require-url
```

Defaults keep `access: public` and `public-mirror`. Flags:

- **`--require-url`** — drop rows with no `source_url`
- **`--require-electrical`** — drop briefs / non-param docs (`has_electrical: false`)
- **`--access`** — override the allowlist (comma-separated)

Outputs default to **`index.public.yaml`** and **`sources.public.yaml`** under the corpus root. They do not remove PDFs already in git; they define what a public rebuild should fetch.

## Download everything in `sources.public.yaml`

Set the corpus root, then run the batch fetcher from **datasheet-tools** (manifest can live in the tools repo or under the corpus):

```bash
export AGNI_DATASHEET_ROOT=~/work/hw/datasheets
cd ~/work/hw/datasheet-tools

# Preview
python3 tools/fetch_manifest.py --manifest sources.public.yaml --dry-run

# curl all download_method: direct rows (skips valid PDFs already on disk)
python3 tools/fetch_manifest.py --manifest sources.public.yaml

# Only curl; write playwright rows for a follow-up browser pass
python3 tools/fetch_manifest.py --manifest sources.public.yaml --direct-only \
  --list-playwright /tmp/datasheet-playwright.tsv
```

**`direct`** entries are fetched with curl (browser user-agent, same idea as the download skill). **`playwright`** / **`js`** entries are not automated in this script. Use the **`datasheet-download`** skill (Playwright MCP, Tier C vendors) on the TSV, one vendor origin per call, with CWD = `$AGNI_DATASHEET_ROOT` and save paths = `<pdf>` from the first column.

After PDFs land:

```bash
cd ~/work/hw   # or wherever pdf2doc Makefile lives
make pdf2doc-all    # or per-file pdf2doc
export AGNI_DATASHEET_ROOT=~/work/hw/datasheets
python3 ~/work/hw/datasheet-tools/tools/genindex.py /tmp/idx.json \
  "$AGNI_DATASHEET_ROOT/index.yaml" "$(date +%Y-%m-%d)"
```

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
