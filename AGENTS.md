# AGENTS.md

Guidance for AI coding agents (and people) working in this repository.

## What this is

Northward is a retirement-planning tool: a Python engine that simulates a household year by year (taxes, Social
Security, RMDs, healthcare, survivors), Monte Carlo on top of it, a SQLite store of revisioned YAML documents, a
FastAPI server, and a React UI. Start with [docs/architecture.md](docs/architecture.md); the rest of the docs are
indexed in [docs/README.md](docs/README.md).

## Layout

```
backend/northward/   Python package (config, engine and domain packages, montecarlo, persistence, api, cli.py)
tests/               pytest, mirroring backend/northward/
frontend/            React + TypeScript + Vite app; frontend/openapi.json and src/api/schema.d.ts are generated
data/rules/          Shared rules (tax law, limits, market presets). Master copy, reviewed in git
data/profiles/example/   The only committed profile: a sanitized example used by tests and demos
docs/                User and developer documentation
var/                 Git-ignored runtime state: the database, run outputs, backups. Never commit it
```

## Commands

```bash
make install         # once: .venv with dev tools
make test            # pytest; run before finishing any Python change
make lint            # ruff check + format check; `make format` fixes
make ui-test         # frontend typecheck, Vitest, Prettier
make api-types       # after any API or config-model change (including docstrings); a test fails if stale
make migration m="..."   # after changing persistence/models.py
make bench           # Monte Carlo performance budget: 10,000 paths under 60 s
```

Use `.venv/bin/northward` (or `.venv/bin/python -m northward`) for the CLI. Pass `--data-dir data` to run against the
committed files instead of the user's database.

## Rules of the road

- **Don't read, modify, or commit `var/`** or any profile other than `data/profiles/example/`. The database holds the
  user's real financial data.
- **Keep runs deterministic.** Don't iterate over sets where order affects results; draw randomness only from the
  per-path streams in `montecarlo/samplers.py`. Seeded runs must reproduce bit for bit across processes.
- **The engine is pure.** Engine and domain code read a `SimulationInput` only, never files or the database.
- **Pydantic models are the only schema.** Don't duplicate validation in the API or UI; the editor's JSON Schemas and
  the API types are generated from the models.
- **Rule figures need sources.** Tax and benefit figures in `data/rules/` cite primary sources in each file's
  `metadata`. Tests for calculations use hand-computed cases, not the code's own output.
- **Decisions are numbered.** Code comments cite [docs/decisions.md](docs/decisions.md) by number (D1–D50). Don't
  renumber; add new decisions at the next number.
- **Config fields are documented twice.** Every field of a config model gets a docstring (shown in the editor on
  hover) and a mention on its page in `docs/configuration/`. `tests/config/test_schema_docs.py` checks both.
- **Docs describe the present.** When behavior changes, update the relevant page in `docs/` (configuration changes go
  in `docs/configuration/`) and add a line to CHANGELOG.md under "Unreleased". Don't add history or phase narratives
  to the docs.

## Style

- Python 3.10+, ruff, 120-character lines. Match the surrounding code: short module docstrings, comments that say why.
- Config models subclass `StrictModel` (unknown keys are errors; instances are frozen).
- Frontend: TypeScript strict mode and Prettier; no ESLint.
