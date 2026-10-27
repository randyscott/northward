# Development

How to work on Northward. [Architecture](architecture.md) explains how the code fits together.

## Setup

Requires Python 3.10+, and Node.js 20.19+ for the frontend.

```bash
make install                  # create .venv and install northward in editable mode with dev tools
make db                       # create var/northward.db and seed it from data/
make ui                       # install the frontend's packages and build it into frontend/dist
```

## Everyday commands

| Command | What it does |
|---|---|
| `make test` | Run the Python tests (pytest). |
| `make lint` | `ruff check` and `ruff format --check`. |
| `make format` | Apply ruff fixes and formatting. |
| `make serve` | Run the API (and the built UI) at http://127.0.0.1:8000. |
| `make ui-dev` | Run the UI with hot reload at http://127.0.0.1:5173, forwarding `/api` to `make serve`. |
| `make ui-test` | Frontend typecheck, unit tests (Vitest), and formatting check (Prettier). |
| `make e2e` | Browser tests (Playwright) against a throwaway database. Needs `make ui` first, and once: `cd frontend && npx playwright install chromium`. |
| `make bench` | Time 10,000 Monte Carlo paths of the example profile. The budget is under 60 seconds. |
| `make api-types` | Regenerate `frontend/openapi.json` and the frontend's TypeScript types. |
| `make migration m="..."` | Generate an Alembic migration after changing `persistence/models.py`. |

## Tests

Tests live in `tests/`, mirroring `backend/northward/`. They run against files in `data/` (through `--data-dir` or a
`FileSource`) or a temporary SQLite database, never your own `var/northward.db`.

Tax, Social Security, and RMD tests are hand-computed cases checked against published IRS and SSA examples. When you
change a calculation, add a case worked out by hand rather than one captured from the code's own output.

Some tests guard invariants that are easy to break by accident:

- **Every committed document** loads, validates against its JSON Schema, and conserves value in every simulated year.
- **Reproducibility:** a seeded Monte Carlo run gives identical results across worker counts and string-hash seeds,
  and a zero-variance run equals the deterministic run.
- **`tests/persistence/test_schema.py`** fails if the models and migrations disagree.
- **`tests/api/test_frontend_types.py`** fails if the API changed without `make api-types`.
- **`tests/config/test_schema_docs.py`** fails if a profile or scenario field lacks a description or a mention in
  `docs/configuration/`.

## Common changes

**Changing the API.** Run `make api-types` and commit `frontend/openapi.json` and `frontend/src/api/schema.d.ts`.
Configuration model docstrings become descriptions in the schema (and in the editor's hover text), so changing them
also needs `make api-types`.

**Changing the database models.** Run `make migration m="describe the change"`, review the generated file in
`persistence/migrations/versions/`, and commit it.

**Changing a configuration model.** Give every field a docstring, written for the person editing the YAML: it
becomes the field's description in the JSON Schema, which the editor shows on hover. Then document the field on the
matching page in [`docs/configuration/`](configuration/README.md), and run `make api-types`.
`tests/config/test_schema_docs.py` fails if a profile or scenario field has no description or isn't mentioned on its
page. Update the example profile if the change is something people will use. If old documents would no longer load,
add an upgrade in `config/versioning.py` and bump `schema_version`.

**A new state.** See [Adding a state](configuration/state-tax.md#adding-a-state).

**A new tax year.** Update the files in `data/rules/` with the new year's figures and sources (and
`metadata.base_year`), then run `northward db seed`. That creates a new rule set; scenarios pinned to the old year
keep it.

**A design decision.** Record anything a future contributor would otherwise have to rediscover in
[decisions.md](decisions.md), with the next number. Never renumber existing decisions; code cites them.

**User-visible changes** get a line under "Unreleased" in [CHANGELOG.md](../CHANGELOG.md).

## Your own data

Only the sanitized `example` profile is committed. `data/profiles/*` (except `example/`) and `var/` (the database,
run outputs, exports, and backups) are git-ignored. Don't commit a real profile, or real figures in a test.

## Frontend notes

- `frontend/.npmrc` sets `legacy-peer-deps`, because npm 10's peer resolver fails on this dependency tree. Every peer
  is listed explicitly in `package.json` instead.
- `vite.config.ts` works around `monaco-yaml`'s use of an older Monaco worker API: an alias swaps in
  `src/components/monacoWorkerManager.ts`, and a second alias maps an old import path. Without them, validation in the
  editor fails silently ("Missing requestHandler: doValidation"). Recheck both when upgrading `monaco-yaml`.
- TypeScript is held at 5.9 until `openapi-typescript` supports 7.
- There's no ESLint; TypeScript's strict mode and Prettier carry the checks.
- Charts follow a fixed categorical palette, and every chart has a table view.
