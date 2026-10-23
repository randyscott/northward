VENV ?= .venv
PYTHON ?= $(VENV)/bin/python

.PHONY: install test lint format bench db migration serve api-types ui ui-dev ui-test e2e

install: $(VENV)/bin/python
	$(PYTHON) -m pip install -e ".[dev]"

$(VENV)/bin/python:
	python3 -m venv $(VENV)

test:
	$(PYTHON) -m pytest

lint:
	$(PYTHON) -m ruff check .
	$(PYTHON) -m ruff format --check .

format:
	$(PYTHON) -m ruff check --fix .
	$(PYTHON) -m ruff format .

# Phase 6 performance budget: 10,000 Monte Carlo paths of ~50 years in under 60 s.
# Reads the files, so the run isn't recorded or answered from the database's run cache.
bench:
	$(VENV)/bin/northward --data-dir data mc --profile example --scenario base --sims 10000 --out var/runs/bench

# Create (or upgrade) var/northward.db and seed it from data/.
db:
	$(VENV)/bin/northward db init
	$(VENV)/bin/northward db seed

# After changing persistence/models.py: make migration m="add a column"
migration:
	$(PYTHON) -c 'import sys; from northward.persistence.db import make_migration; make_migration(sys.argv[1])' "$(m)"

# The HTTP API on var/northward.db, at http://127.0.0.1:8000 (interactive docs at /docs).
serve:
	$(VENV)/bin/northward serve

# After changing the API: regenerate frontend/openapi.json and the frontend's types from it.
api-types:
	$(VENV)/bin/northward openapi frontend/openapi.json
	cd frontend && npm run gen:api

# The web UI (Phase 9A): build it into frontend/dist, which `northward serve` then serves.
ui:
	cd frontend && npm ci && npm run build

# Develop the UI with hot reload at http://127.0.0.1:5173 (run `make serve` alongside it for the API).
ui-dev:
	cd frontend && npm run dev

ui-test:
	cd frontend && npm run typecheck && npm test && npm run format:check

# Browser test of the whole app against a throwaway database (needs `make ui` and `npx playwright install chromium`).
e2e:
	cd frontend && npm run e2e
