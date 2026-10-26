VENV := .venv
# Agni checkout that owns pdf2doc (datasheet/tools/pdf2doc).
AGNI_DIR ?= ../main

.PHONY: setup pdf2doc-all

# fetch_playwright_manifest.py launches p.chromium with no channel, so it needs
# Playwright's bundled Chromium (plus headless shell), not system Chrome.
setup:
	test -x $(VENV)/bin/python || uv venv $(VENV)
	uv pip install -r requirements.txt -p $(VENV)
	$(VENV)/bin/playwright install chromium
	$(VENV)/bin/python -c "from playwright.sync_api import sync_playwright as s; p = s().start(); b = p.chromium.launch(); print('playwright ok: chromium', b.version); b.close(); p.stop()"
	$(VENV)/bin/python -c "import docling.document_converter; print('docling ok')"

# Agni's Makefile only looks for a venv in $(AGNI_DIR)/.venv or its parent, so point it at ours.
pdf2doc-all:
	@[ -n "$(AGNI_DATASHEET_ROOT)" ] || { echo "set AGNI_DATASHEET_ROOT"; exit 2; }
	$(MAKE) -C $(AGNI_DIR) pdf2doc-all VENV_DIR=$(abspath $(VENV)) DATASHEET_DIR=$(AGNI_DATASHEET_ROOT)
