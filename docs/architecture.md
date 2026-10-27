# Architecture

How Northward is put together, for anyone changing it. [Development](development.md) covers the workflow, and
[Decisions](decisions.md) records why things are the way they are (cited as D1–D50 here and in code comments).

## Overview

```
┌──────────────────────────────┐        ┌──────────────────────────────┐
│ Web UI (frontend/)           │        │ CLI (northward ...)          │
│ React, Vite, Plotly, Monaco  │        │ cli.py, persistence/commands │
└──────────────┬───────────────┘        └──────────────┬───────────────┘
               │ HTTP /api (JSON)                      │
┌──────────────▼───────────────┐                       │
│ API (api/)                   │                       │
│ FastAPI routes, job runner   │                       │
└──────────────┬───────────────┘                       │
               ├───────────────────────────────────────┘
┌──────────────▼───────────────┐        ┌──────────────────────────────┐
│ Persistence (persistence/)   │        │ data/ files                  │
│ SQLite: documents, revisions,│◄─seed──│ rules/ (master copy)         │
│ runs; repositories; DbSource │        │ profiles/example/            │
└──────────────┬───────────────┘        └──────────────┬───────────────┘
               │ ConfigSource                          │ FileSource
┌──────────────▼───────────────────────────────────────▼───────────────┐
│ Configuration (config/): Pydantic models, loader → SimulationInput   │
└──────────────┬───────────────────────────────────────────────────────┘
┌──────────────▼───────────────┐        ┌──────────────────────────────┐
│ Engine (engine/ and domain   │◄───────│ Monte Carlo (montecarlo/)    │
│ packages): one path, year by │  paths │ samplers, process pool,      │
│ year, with a ledger          │        │ telemetry, statistics        │
└──────────────────────────────┘        └──────────────────────────────┘
```

The engine never touches the database or files. It sees only a frozen `SimulationInput`, which is what makes runs
reproducible and the engine easy to test.

## Packages

Everything lives in `backend/northward/`. Tests in `tests/` mirror this layout.

| Package | Contents |
|---|---|
| `config/` | Pydantic models for every document (`household.py`, `accounts.py`, ..., `scenario.py`), rule models in `config/rules/`, timing anchors, scenario `overrides`, schema-version upgrades, config sources, and the loader. `yaml_edit.py` merges structured edits into YAML text without losing comments. |
| `ledger/` | `Transaction`, `TaxCategory`, and `Books`, through which every movement of value passes. |
| `accounts/` | Account state (balance, basis), glide-path allocation, and growth. |
| `income/` | Wages and payroll elections, Social Security, pensions and other streams. |
| `expenses/` | Spending (base, phases, categories) and debt service. |
| `policy/` | Contribution limits, contributions, withdrawals, the surplus sweep, RMDs, Roth conversions, bracket filling, and 529s. |
| `tax/` | `TaxInputs`, federal tax (`FederalTax` → `TaxReturn`), credits, state tax, and indexing. |
| `lifecycle/` | Dependent status, healthcare, mortality, and survivor transitions. |
| `engine/` | The yearly cycle (`year_step.py`), events, tax settlement, the timeline, market paths, and `simulate`. |
| `montecarlo/` | Samplers, the parallel runner, telemetry, statistics, and reports. |
| `persistence/` | SQLAlchemy models, Alembic migrations, repositories, `DbSource`, seed/export/backup, recorded runs, and the `db` and `runs` CLI commands. |
| `api/` | The FastAPI app, routes, request and response schemas, and the background job runner. |
| `fingerprint.py` | The engine version used by the run cache. |
| `cli.py` | The `northward` command. |

## From documents to a simulation

1. A **`ConfigSource`** supplies raw YAML documents by kind and name. `FileSource` reads a `data/` directory,
   `DbSource` reads the database (the latest revisions, a run's pinned revisions, or unsaved changes being validated),
   and `SnapshotSource` holds a fixed set of documents.
2. **`load_simulation_input(source, profile, scenario)`** validates each document against its model, applies the
   scenario's `overrides`, resolves the market preset, and checks cross-references (owners exist, account types
   allow their owner, and so on). All problems are collected into one `ConfigError`, each located as
   `file: path[item-id].field: message`.
3. The result is a frozen **`SimulationInput`**: the rule set, the profile, the scenario, and the resolved market
   preset. It remembers the documents it was loaded from, so it can be pickled to worker processes and hashed for the
   run cache.
4. **`simulate(sim, path=None, record=True)`** runs each year and returns the year-by-year states, the transaction
   ledger, and warnings. A `MarketPath` supplies each year's returns and inflation: constant for a deterministic run,
   sampled for a Monte Carlo path.

## The yearly cycle

`engine/year_step.py` runs eight stages each year, in this order:

1. **Estates, moves, and events.** Settle the estates of members who died last year, apply relocations, and process
   scheduled events (windfalls, home sales, inheritances, which may open inherited IRAs).
2. **Base inflows.** Wages and payroll elections, Social Security, pensions and other income, and taxable-account
   income (interest and dividends).
3. **Required distributions.** Lifetime RMDs and inherited-IRA distributions.
4. **Expenses and discretionary moves.** Spending, healthcare, 529 leftovers and education payments, debt service,
   and contributions. If cash is negative, withdraw in the scenario's order. Top up the cash reserve. Then the
   bracket-aware moves (inherited-IRA bracket filling and Roth conversions), which need the year's other income
   ([D28](decisions.md#d28-discretionary-tax-moves)).
5. **Taxes.** Federal and state tax, settled until the withdrawals made to pay them have been taxed too
   ([D11](decisions.md#d11-tax-circularity)). Anything still unpaid is recorded as a shortfall.
6. **Surplus sweep.** Invest leftover cash in the sweep targets.
7. **Allocation and growth.** Rebalance to each account's allocation (glide paths), then apply the year's returns.
8. **Record.** Save the year's state, MAGI (for IRMAA's two-year lookback), and filing status.

**The ledger.** Cash clears to zero each year ([D27](decisions.md#d27-cash-handling)). Every movement of value goes
through `Books.move`, which updates balances and, when recording, appends a `Transaction` with its tax category. Tax
totals accumulate even when recording is off (Monte Carlo), so taxes can always be computed. A test checks that
value is conserved every year for every committed scenario.

**Tax settlement.** Each year the engine builds a plain `TaxInputs` record from the ledger (`engine/taxes.py`).
`FederalTax.compute` returns a full `TaxReturn` (AGI, taxable income, each tax and credit, and marginal and effective
rates), and `compute_state_tax` does the same for the state. If the bill leaves cash negative, the engine withdraws
more, grossing up each extra withdrawal by the tax rate observed on the previous one, until the change is under $1.

## Monte Carlo

- **Sampling** (`montecarlo/samplers.py`). Each path draws from its own random streams,
  `SeedSequence(seed, spawn_key=(stream, path))`: one each for market draws, the Student-t mixing variable,
  bootstrap block starts, and deaths. So a run gives identical results however it's split across processes, any path
  can be regenerated alone, and compared scenarios share their draws. Parametric presets use correlated normals
  (Cholesky) transformed to each factor's distribution. Bootstrap presets resample circular blocks of historical years.
- **Running** (`montecarlo/runner.py`). A `ProcessPoolExecutor` runs chunks of paths with the ledger off.
  `simulate_path(sim, seed, i)` re-runs path `i` with the ledger on, reproducing its results exactly. Workers are
  spawned rather than forked ([D47](decisions.md#d47-background-jobs)).
- **Telemetry** (`montecarlo/telemetry.py`). A `(paths × years × buckets)` float32 array of balances, flows, and taxes,
  saved as `telemetry.npz` with the market draws and ages at death. Years after a path ends are NaN.
- **Statistics** (`montecarlo/stats.py`). Success criteria are evaluated on stored telemetry, so they can change
  without a rerun ([D35](decisions.md#d35-success-criteria)). The summary has the success probability, failure rates,
  percentile bands, legacy, lifetime taxes, and representative paths. `compare` pairs paths across scenarios.

The performance budget is 10,000 paths of about 50 years in under 60 seconds (`make bench`).

## Persistence

- **Tables** (`persistence/models.py`): `profiles`, `scenarios`, `rule_sets`, `documents`, `document_revisions`
  (append-only YAML text), `runs`, and `run_revisions` (the revisions each run read).
- **Repositories** (`persistence/repositories.py`): `ProfileRepo`, `ScenarioRepo`, `RuleRepo`, and `RunRepo`. All
  reads and writes go through them. A write is validated as a set: each document, then the profile and every one of
  its scenarios as they'd be after the change ([D41](decisions.md#d41-validating-writes)).
- **Seeding** (`persistence/seed.py`): rules are upserted from `data/rules/`; profiles are imported once
  ([D14](decisions.md#d14-where-each-kind-of-data-is-mastered)). Export writes the stored text back byte for byte.
- **Recorded runs** (`persistence/runs.py`): runs from the database are recorded with their pinned revisions. Monte
  Carlo runs are cached by scenario, input hash, engine version, seed, and number of paths
  ([D43](decisions.md#d43-run-cache-key)). The engine version (`fingerprint.py`) hashes the simulation source, so any
  engine change invalidates the cache.
- **Migrations** are Alembic, in `persistence/migrations/`. A test fails if the models and migrations disagree.

## API and UI

- **API** (`api/`): `create_app` builds the FastAPI app. Routes use only the repositories and the run service, never
  SQL directly. Configuration errors become 422 responses with the same issues `northward validate` prints. Request
  and response models reuse the configuration models, so the OpenAPI schema describes every document.
- **Jobs** (`api/jobs.py`): Monte Carlo runs execute one at a time on a worker thread, with state in the `runs` table
  ([D47](decisions.md#d47-background-jobs)).
- **UI** (`frontend/`): React 19, TypeScript, Vite, TanStack Query, React Router, Plotly, and Monaco with
  `monaco-yaml`. The editor validates against `/api/schemas/{kind}`. API types are generated from the committed
  `frontend/openapi.json`. `northward serve` serves the built app from `frontend/dist` on the same origin as the API.

## Things that must stay true

- **Determinism.** A seeded run is bit-for-bit reproducible across processes and worker counts. Iterate in insertion
  order, never over sets (string hashing differs between processes), and draw random numbers only from the
  per-path streams.
- **The engine is pure.** It reads a `SimulationInput` and nothing else.
- **Pydantic is the only schema.** The database stores YAML text; the editor's JSON Schemas and the API types are
  generated from the models.
- **Revisions are append-only.** Nothing overwrites a stored revision.
