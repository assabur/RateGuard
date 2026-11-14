PYTHON ?= .venv/bin/python
RATE_GUARD ?= .venv/bin/rateguard

.PHONY: install demo ingest serve test lint db-up
install:
	python3 -m venv .venv
	$(PYTHON) -m pip install -e '.[dev]'
db-up:
	docker compose up -d postgres
demo:
	$(RATE_GUARD) demo
# Example: make ingest AS_OF=2025-01-08
AS_OF ?=
ingest:
	$(RATE_GUARD) ingest $(if $(AS_OF),--as-of $(AS_OF),)
serve:
	$(RATE_GUARD) serve
test:
	$(PYTHON) -m pytest -q
lint:
	.venv/bin/ruff check .
	.venv/bin/ruff format --check .
