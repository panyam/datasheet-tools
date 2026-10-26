
setup:
	uv venv .venv && uv pip install -r requirements-playwright.txt -p .venv
	.venv/bin/playwright install chrome
