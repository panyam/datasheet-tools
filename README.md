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
| `tools/sweep_pin_relations.py` | Scan doc-IR for pin-to-pin constraint candidates |
| `tools/pkindex.py` | Internal SharePoint index helper (optional) |

Example:

```bash
cd ~/work/hw/datasheet-tools
export AGNI_DATASHEET_ROOT=~/work/hw/datasheets
python3 tools/genindex.py "$AGNI_DATASHEET_ROOT/index.yaml" \
  "$AGNI_DATASHEET_ROOT/sources.yaml" \
  "$AGNI_DATASHEET_ROOT/overrides.yaml"
```

## Skills

Cursor / Claude skills live under `skills/`:

- `skills/datasheet-download/` — source public PDFs into the corpus tree
- `skills/datasheet-transcribe/` — hand-transcribe cited params from PDFs

Install by copying or symlinking into your skills directory (e.g. `~/.cursor/skills/` or the project’s `.cursor/skills/`). Skills assume `AGNI_DATASHEET_ROOT` for on-disk layout; review overlay paths (`projects/`, `designs/`) still come from your house-designs checkout.

## Docs

- `docs/NEAR_MISSES.md` — MPN / designation matching pitfalls for gap diffs
- `docs/sources.yaml.example` — shape of corpus `sources.yaml` (full file stays in the corpus)

## Confidentiality

Do not commit PDFs or customer doc-IR to this repo. C16 applies to the corpus volume, not these scripts.
