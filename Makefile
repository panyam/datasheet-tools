VENV := .venv

.PHONY: setup

# fetch_playwright_manifest.py launches p.chromium with no channel, so it needs
# Playwright's bundled Chromium (plus headless shell), not system Chrome.
setup:
	test -x $(VENV)/bin/python || uv venv $(VENV)
	uv pip install -r requirements-playwright.txt -p $(VENV)
	$(VENV)/bin/playwright install chromium
	$(VENV)/bin/python -c "from playwright.sync_api import sync_playwright as s; p = s().start(); b = p.chromium.launch(); print('playwright ok: chromium', b.version); b.close(); p.stop()"
