# datasheet-tools

Scripts and agent skills for the **datasheet corpus**. PDFs, doc-IR (`.doc.textproto`), and generated `index.yaml` stay in a separate tree (typically [`~/work/hw/datasheets`](https://github.com/GM-InnerSource/datasheets) or your org mirror). This repo is only the tooling.

The same files still live under `tools/` and `.claude/skills/` in the legacy corpus repo for now. New work belongs here; the in-tree copies will be deprecated once callers point at this repo.

## Corpus path

All tools read the corpus via **`AGNI_DATASHEET_ROOT`** (absolute path to the directory that contains `sources.yaml`, `index.yaml`, and `<vendor>/<part>/` trees).

```bash
export AGNI_DATASHEET_ROOT=~/work/hw/datasheets
```

`genindex.py` also accepts an optional fourth CLI argument to override the env var.

## Tools

| Script | Purpose |
|--------|---------|
| `tools/genindex.py` | Regenerate `index.yaml` from doc-IR (no PDF reads) |
| `tools/filter_index_public.py` | Write `index.public.yaml` (+ optional `sources.public.yaml`) for public rebuild |
| `tools/fetch_manifest.py` | curl-fetch PDFs from `sources.public.yaml` (`direct` rows; lists `playwright` for browser pass) |
| `tools/fetch_playwright_manifest.py` | Browser-fetch TSV rows (`requirements-playwright.txt` + `playwright install chromium`) |
| `tools/sweep_pin_relations.py` | Scan doc-IR for pin-to-pin constraint candidates |
| `tools/pkindex.py` | Internal SharePoint index helper (optional) |

Example:

```bash
cd ~/work/hw/datasheet-tools
export AGNI_DATASHEET_ROOT=~/work/hw/datasheets
# <json out> <index.yaml out> <date> [corpus]; reads sources.yaml / overrides.yaml from the corpus root
python3 tools/genindex.py /tmp/idx.json "$AGNI_DATASHEET_ROOT/index.yaml" "$(date +%Y-%m-%d)"
```

## Skills

Cursor / Claude skills live under `skills/`:

- `skills/datasheet-download/` — source public PDFs into the corpus tree
- `skills/datasheet-transcribe/` — hand-transcribe cited params from PDFs

This repo is also a Claude Code plugin marketplace (`.claude-plugin/`). Install the skills from it:

```bash
/plugin install datasheet-tools --marketplace panyam/datasheet-tools
# or, from a local checkout:
/plugin marketplace add ~/projects/Agni/datasheet-tools
/plugin install datasheet-tools@datasheet-tools
```

Installed skills are namespaced: `/datasheet-tools:datasheet-download`, `/datasheet-tools:datasheet-transcribe`. For Cursor, copy or symlink `skills/*` into `~/.cursor/skills/` or the project’s `.cursor/skills/`. Skills assume `AGNI_DATASHEET_ROOT` for on-disk layout; review overlay paths (`projects/`, `designs/`) still come from your house-designs checkout.

## Docs

- `docs/corpus-rebuild.md` — download → pdf2doc → genindex loop; what the index does not cover
- `docs/NEAR_MISSES.md` — MPN / designation matching pitfalls for gap diffs
- `docs/sources.yaml.example` — shape of corpus `sources.yaml` (full file stays in the corpus)

## Confidentiality

Do not commit PDFs or customer doc-IR to this repo. C16 applies to the corpus volume, not these scripts.
