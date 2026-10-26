# datasheet-tools

Tooling and skills for the datasheet corpus. The corpus itself (PDFs, doc-IR, `index.yaml`,
`sources.yaml`, `overrides.yaml`) lives elsewhere, at `$AGNI_DATASHEET_ROOT`. Never commit a PDF
or doc-IR here. See README.md for the tool list and docs/corpus-rebuild.md for the rebuild loop.

## Commands

- `make setup`: uv venv in `.venv` + `requirements.txt` (playwright, docling) + Playwright's
  bundled Chromium, with a launch and import check at the end. Safe to re-run.
- `make pdf2doc-all`: runs Agni's `pdf2doc-all` (checkout at `AGNI_DIR`, default `../main`) with
  this repo's venv. Agni's own Makefile only finds a venv in its checkout or parent dir.
- `python3 tools/genindex.py <json out> <index.yaml out> <date> [corpus]`: reads `sources.yaml`
  and `overrides.yaml` from the corpus root, not from argv.

## Skills

`skills/` is published as a Claude Code plugin; this repo is its own marketplace
(`.claude-plugin/`). Installed skills are `/datasheet-tools:datasheet-download` and
`/datasheet-tools:datasheet-transcribe`. After editing a SKILL.md, run
`/plugin marketplace update datasheet-tools`, since the plugin is a cached copy.

## Gotchas

- **Bot-blocked vendors.** `tools/fetch_playwright_manifest.py` uses bundled Chromium: Littelfuse
  needs `--headed`; ST and LCSC don't work at all. Use the Playwright MCP via the
  datasheet-download skill for those (docs/corpus-rebuild.md has the details).
- **Public rebuild needs both sidecars.** Copy `sources.public.yaml` and `overrides.public.yaml`
  into the corpus as `sources.yaml` / `overrides.yaml` before genindex. Without overrides,
  titles, `covers`, `has_electrical` and `dir_name_mismatch_ack` fall back to heuristic guesses.
- **Diff indexes by value, not text.** `filter_index_public.py` re-quotes every scalar and drops
  comments, so `diff index.public.yaml index.yaml` is mostly noise. Parse both and compare fields.
  Expect `content_hash` / `doc_number` / `revised` changes where vendors have revised a PDF.
- `make pdf2doc-all` prints a torch "Redirects are currently not supported in MacOs" warning and
  docling "Skipping page separator extraction" notices. Both are harmless.
