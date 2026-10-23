# Northward

Northward is a retirement-planning tool for one household. It simulates the years ahead one at a time, with
taxes, Social Security, RMDs, Roth conversions, healthcare, and survivor transitions. It then runs thousands of
Monte Carlo paths to show how likely a plan is to hold up, and lets you compare decisions such as claiming Social
Security at 62 or 70 on the same simulated markets. It runs locally: a Python engine and API, a database of your
documents, and a web app.

It's planning software, not financial advice; check anything important with a professional.

- [Development](#development): install it, run it, and use the CLI.
- [Web UI](#web-ui), [HTTP API](#http-api), and [Database](#database).
- [PLAN.md](PLAN.md): the phased plan, decisions, and design notes.

Licensed under the [MIT License](LICENSE).

---

## Architecture & Design

## 1. Executive Summary & Core Decisions

This document establishes the architecture for a localized, modular, and event-driven financial simulation engine. The platform evaluates multi-decade retirement scenarios—specifically stress-testing decisions such as Social Security claiming strategies (e.g., age 62 vs. 70), asset drawdown sequences, dynamic tax bracket arbitrage (Roth conversions), and complex lifecycle transitions (e.g., inherited IRAs, spousal mortality).

### Key Architectural Decisions to Date

1. **Configuration-as-Code (Declarative YAML):**
* Eliminates procedural hardcoding. Financial rules, household demographics, account specifications, and scenario levers are decoupled into distinct YAML configuration files validated via **Pydantic**.
* Separates static regulatory rules (IRS brackets, SECURE Act provisions) from baseline state (accounts, debt) and scenario-specific inputs (claiming ages, scheduled conversions).


2. **Dual Stochastic/Deterministic Architecture:**
* **Market & Macro Dynamics (Stochastic):** Equities, fixed income, and inflation operate as probabilistic distributions sampled via NumPy vectors across thousands of Monte Carlo runs.
* **Legislative & Policy Dials (Discrete/Deterministic):** Tax codes, bracket changes, and statutory policies are treated as environmental constraints or scenario-triggered policy modifiers, rather than random noise.


3. **Event-Driven Cash Clearing (`CashBook` & `Transaction` Model):**
* Replaced circular cash-flow calculations with a centralized checking/clearing ledger pattern.
* Every movement of value produces an immutable `Transaction` recording `amount`, `source_dest`, human-readable `description`, and a typed `TaxCategory` (`ORDINARY`, `CAPITAL_GAINS`, `NONE`, `TAX_PAYMENT`).
* Cash deficits prompt ordered liquidations; cash surpluses execute deterministic end-of-year sweeps into tax-advantaged or taxable storage accounts.


4. **Dynamic Asset Allocation (Target-Date Glide Paths):**
* Asset allocation is modeled as a function of time rather than static ratios.
* `TargetDateAccount` instances recalculate equity vs. bond exposure annually based on retirement target dates, automatically shifting account volatility within the Monte Carlo framework.


5. **Household Spousal Asynchrony:**
* Primary and spouse are tracked as independent entities with individual birth dates, earnings records, and target retirement ages.
* Accommodates asynchronous Social Security claiming, staggered RMD onset (ages 73/75), individual account ownership constraints (IRAs, 401ks, HSAs), and survivor tax status shifts (Married Filing Jointly transitioning to Single).



---

## 2. System Architecture & Component Hierarchy

```
┌────────────────────────────────────────────────────────────────────────┐
│                              Frontend UI                               │
│            (Streamlit Dashboard or Modern Web SPA + Plotly)            │
│    - Scenario toggles & visual editor                                  │
│    - Percentile distribution cones (10th, 50th, 90th) & tabular ledgers│
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ HTTP / REST (JSON or YAML payload)
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                            FastAPI Backend                             │
│    - Endpoint: POST /api/simulate                                      │
│    - Pydantic schema parsing & strict validation                       │
│    - Orchestrates simulation lifecycle across worker threads           │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                        Simulation Rules Engine                         │
│  ┌───────────────────────┐                    ┌──────────────────────┐ │
│  │ YAML Config Loader    │                    │ CashBook Ledger      │ │
│  │ (Rules, Profile, Runs)│                    │ (Credits / Debits)   │ │
│  └───────────┬───────────┘                    └──────────▲───────────┘ │
│              │                                           │             │
│              ▼                                           │             │
│  ┌───────────────────────┐                    ┌──────────┴───────────┐ │
│  │ Portfolio / Accounts  │ ──Transactions───> │ Federal / State Tax  │ │
│  │ State Machine         │                    │ Resolver Engine      │ │
│  └───────────────────────┘                    └──────────────────────┘ │
│              │                                                         │
│              └───────────────► NumPy Vectorizer ───────────────────────┘
│                                (Monte Carlo Matrix Runner)

```

---

## 3. Configuration Directory Specification

Configuration is YAML documents in the `data/` layout. Every document starts with `schema_version`, and all documents
are validated with Pydantic models in `backend/northward/config/`. See [PLAN.md](PLAN.md) for the design notes behind each
file.

The documents are stored in a database (`var/northward.db`, see [Database](#database)). The files under `data/rules/` are
the master copy of the rules and are reviewed in git. Profiles and scenarios are imported from `data/profiles/` once,
after which the database is their master copy. Only the sanitized `example` profile is committed; real profiles are
git-ignored and exist only in the database (and its exports and backups).

```
data/
├── rules/                          # Shared by all profiles (reviewed in git; `northward db seed` stores them)
│   ├── account_types.yaml          # Tax/behavior definitions (401k, IRA, Roth, HSA, brokerage, cash, inherited IRA, 529)
│   ├── federal_tax.yaml            # 2026 brackets, deductions, LTCG, NIIT, SS taxability, FICA, penalties, credits
│   ├── contribution_limits.yaml    # 401(k)/IRA/HSA limits, Roth phase-outs, dependent-care FSA, gift, 529->Roth
│   ├── rmd.yaml                    # Applicable ages, Uniform Lifetime and Single Life tables, inherited 10-year rule
│   ├── social_security.yaml        # FRA, reductions, credits, spousal/survivor/child rules, family max, earnings test
│   ├── glide_paths.yaml            # Linear target-date equity glide paths
│   ├── market_assumptions.yaml     # Capital-market-assumption presets (returns, volatility, correlations, inflation;
│   │                               #   lognormal, normal, or Student-t draws, or a historical block bootstrap)
│   ├── historical_returns.yaml     # US stocks, 10-year Treasuries, T-bills, and CPI-U by year, 1928-2025
│   ├── state_tax.yaml              # State income tax rules by state code (none, WI)
│   ├── healthcare.yaml             # Medicare premiums and IRMAA, ACA age curve, default health cost assumptions
│   └── mortality.yaml              # SSA 2023 period life table (for sampled lifespans)
└── profiles/
    ├── <profile>/                  # A profile's documents (real profiles: in the database only, git-ignored)
    │   ├── household.yaml          # Members, dependents, filing status, state of residence
    │   ├── accounts.yaml           # Account instances, owners, balances, asset strategies
    │   ├── income.yaml             # Salary/pension/other streams and payroll elections (optional)
    │   ├── liabilities.yaml        # Amortizing and interest-only debt (optional)
    │   ├── spending.yaml           # Base spending plus phased/periodic categories
    │   ├── events.yaml             # One-time events: windfalls, home sales, inheritances (optional)
    │   ├── health_costs.yaml       # Overrides of the default healthcare cost assumptions (optional)
    │   ├── goals.yaml              # Monte Carlo success criteria and the heirs' tax rate (optional)
    │   └── scenarios/
    │       └── base.yaml           # Horizon, market preset, macro, levers, profile overrides
    └── example/                    # Sanitized, fully featured household used by tests and demos (committed)
```

---

## Development

Requires Python 3.10+.

```bash
make install                  # create .venv and install northward in editable mode with dev tools
make db                       # create var/northward.db and seed it from data/ (northward db init && northward db seed)
make test                     # run pytest
make lint                     # ruff check + format check
make format                   # apply ruff fixes and formatting
make bench                    # time 10,000 Monte Carlo paths (budget: under 60 s)
.venv/bin/northward validate     # validate every stored profile and scenario (or --profile/--scenario)
.venv/bin/northward show-config --profile example --scenario base   # print a loaded configuration summary
.venv/bin/northward run --profile default --scenario base          # deterministic run, recorded -> var/runs/<run id>/
```

Commands read the database unless `--data-dir DIR` points them at a `data/` tree, which is how tests and `make bench`
run. File-mode runs aren't recorded. The database URL is `--db URL`, else `$NORTHWARD_DATABASE_URL`, else
`sqlite:///var/northward.db`.

Monte Carlo (Phase 6):

```bash
# 5,000 paths (default) with seed 1, recorded as a run -> var/runs/<run id>/{telemetry.npz,summary.json,bands.csv}
.venv/bin/northward mc --profile default --scenario base --sims 5000 --seed 1
# Re-score a stored run under other success criteria, without rerunning (a run number, or a run directory)
.venv/bin/northward stats 12 --liquidity-floor 50000
# Re-run one path of a stored run (e.g. a representative path from the summary) with the full ledger
.venv/bin/northward run --from-run 12 --path 123
# Compare scenarios on the same draws (common random numbers); the first scenario is the baseline
.venv/bin/northward compare --profile example --scenario base --scenario early_retire_roth_fill
```

Every path draws from its own seeded streams, so a run is reproducible bit for bit whatever the number of worker
processes, and any path can be regenerated alone. Success means never being short on spending unless the profile's
`goals.yaml` (or a CLI flag) adds a liquidity floor: year-end cash plus brokerage, in today's dollars (retirement
accounts and HSAs don't count). To hold an emergency fund that withdrawals leave alone until everything else is
spent, set `levers.cash_reserve: {account: <a cash or brokerage account>, amount: <today's dollars>}`. Set `levers.mortality: {kind: sampled}` to draw lifespans from the
life table instead of planning to `end_age`.

Source lives in `backend/northward/` and tests in `tests/`.

### Database

SQLite through SQLAlchemy 2.0, with Alembic migrations (`backend/northward/persistence/`). Each document is YAML text, and
editing it appends a revision instead of overwriting it. A write is validated before it's stored: the document against
its Pydantic model, then the whole profile and every scenario of it as they'd be after the change. A change that
introduces a problem is rejected with the same errors `northward validate` gives.

```bash
northward db init                # create var/northward.db (or upgrade it: northward db migrate)
northward db seed                # upsert data/rules; import profiles/scenarios that aren't stored yet (re-runnable)
northward db list [--deleted]    # rule sets, profiles, scenarios
northward db list --profile default   # a profile's documents (and optional ones it lacks) with descriptions

# Documents are addressed as in the data/ layout: accounts, household, ..., scenarios/<name>
northward db edit --profile default accounts --note "Q3 statements"   # $VISUAL/$EDITOR; saves revision N+1 if valid
northward db edit --profile default accounts scenarios/base           # several documents, validated together
northward db put --profile default accounts.yaml scenarios/what_if=/tmp/what_if.yaml   # save files as revisions
northward db show --profile default accounts [--revision 3]           # or --rule-set 2026 federal_tax
northward db history --profile default [accounts]
northward db diff --profile default accounts [OLD [NEW]]              # default: the last two revisions
northward db revert --profile default accounts --revision 3           # saves revision 3's text as a new revision
northward db clone --profile default base retire_at_60                # a new scenario from an existing one
northward db delete --profile default --scenario retire_at_60         # soft delete; `northward db restore` undoes it
northward db purge --profile default --scenario retire_at_60          # permanent, once deleted (asks to confirm)
```

A new profile can be created from files with `northward db put --create --profile NAME FILE...`, or by adding it under
`data/profiles/` and running `northward db seed`.

Rule sets are named for their tax year (`federal_tax.yaml`'s `metadata.base_year`). Seeding changed rule files adds
revisions to that year's rule set, and a new tax year becomes a new rule set. A scenario uses the latest unless it pins
one (`rule_set: 2026`), so a new tax year never changes old results.

**Runs.** Every run from the database is recorded with the exact document revisions it read. Asking for a Monte Carlo
run that matches a stored one (same scenario inputs, engine code, seed, and number of paths) returns the stored result;
`--no-cache` reruns it.

```bash
northward runs list [--profile P] [--scenario S]
northward runs show 12           # details, pinned revisions, headline results
northward runs rerun 12          # run again on the pinned revisions and confirm the results are identical
```

**Backups.** `northward db backup` writes an export of every document (in the data/ layout) plus a consistent copy of the
SQLite file to `var/backups/<timestamp>/`. `northward db export [DIR] [--profile P]` writes the documents alone. Run
outputs in `var/runs/` can be regenerated from the database. To back up nightly at 2 a.m. into a synced folder, add
this with `crontab -e`:

```cron
0 2 * * * cd /path/to/finance_v2 && .venv/bin/northward db backup ~/Backups/northward/$(date +\%Y\%m\%d) >/dev/null
```

To restore, copy a backup's `northward.db` to `var/northward.db`, which keeps every revision and run. Seeding an empty
database from a backup's `data/` directory (`northward db init && northward db seed ~/Backups/northward/20261016/data`) restores
only the latest revisions.

**Your data stays out of git.** Only the sanitized `example` profile is committed: `data/profiles/*` (except
`example/`) and `var/` (the database, run outputs, exports, and backups) are git-ignored. Real profiles live in the
database, so back it up as above rather than committing it.

After changing `persistence/models.py`, generate a migration with `make migration m="describe the change"`, review it,
and commit it. `tests/persistence/test_schema.py` fails if the models and migrations disagree.

### HTTP API

`northward serve` (or `make serve`) runs the API on the database at http://127.0.0.1:8000, with interactive docs at
`/docs`. It has no authentication, so it listens on localhost only unless you pass `--host`.
`northward openapi [FILE]` writes the OpenAPI schema. It includes the configuration document models (`AccountsDoc`,
`ScenarioDoc`, ...), so generated client types describe each document's `data`.

| Endpoint | Purpose |
|---|---|
| `GET /api/health` | Engine version and database schema revision. |
| `GET/POST /api/profiles`, `GET/PATCH/DELETE /api/profiles/{profile}`, `POST .../restore` | List, create (from documents or `copy_from`), rename, delete, restore, and purge (`?purge=true`) profiles. |
| `GET /api/profiles/{profile}/documents`, `PUT` (batch) | Every document a profile can have, including optional ones it doesn't have yet. Save several at once, validated together. |
| `GET/PUT /api/profiles/{profile}/documents/{address}` | Read or save one document (`accounts`, `scenarios/base`) as `yaml_text` or structured `data`. |
| `GET /api/documents/{id}[/revisions[/{rev}]]`, `.../diff`, `POST .../revisions/{rev}/restore` | Revision history, an old revision, diffs, and restoring a revision. |
| `GET/POST /api/profiles/{profile}/scenarios`, `GET/PATCH/DELETE .../{scenario}`, `POST .../restore` | Scenarios: create from content or `clone_from`, rename, delete, restore, purge. |
| `GET /api/rule-sets[/{name}[/documents/{kind}]]` | The shared rules (read-only: data/rules is their master copy). |
| `GET /api/schemas/{kind}`, `POST /api/validate` | A document kind's JSON Schema. Check one document, or a set of changes as saving them would, without saving. |
| `POST /api/simulate/deterministic` | Run and record a deterministic simulation; returns the year table and the ledger. |
| `POST /api/simulate/montecarlo` | Queue a Monte Carlo run (202), or get an identical stored one (200, `cached: true`). |
| `GET /api/runs[/{id}]`, `POST /api/runs/{id}/cancel` | Run history, status, and progress; cancel a queued or running run. |
| `GET /api/runs/{id}/results` | Statistics and percentile bands (`buckets=`, `bands=false`), with one-off goal overrides (`liquidity_floor=`, ...). |
| `GET /api/runs/{id}/paths/{i}` | Re-run one path on the run's pinned inputs, with the ledger. |
| `POST /api/compare` | Compare scenarios on the same draws. Queues missing runs (202); repeat the request until it returns 200. |

**Saving structured data.** A `PUT` with `data` is merged into the document's current YAML text, so comments, key
order, and formatting survive. Only changed values are rewritten, and list items with an `id` keep their comments
when reordered. Pass `base_revision` (the revision you started editing from) to get a 409 instead of overwriting a
newer save.

**Errors.** Each error response has a `detail` message. Configuration problems are 422 responses with `issues`
(`origin`, `location`, `message`, as `northward validate` prints them), and nothing is saved. A missing item is 404, a
conflict is 409 (e.g. a name in use, purging an item that isn't deleted, or a stale `base_revision`), and a bad value
is 400. Malformed requests get FastAPI's usual 422 with a `detail` list.

**Monte Carlo jobs** run one at a time in the background, each using every CPU. Their state is in the `runs` table:
- Stopping the server puts the active run back in the queue. The next start resumes queued runs.
- A run whose process died is marked failed.
- Identical requests share a run.

### Web UI

The browser app (Phase 9A) lives in `frontend/`: React, TypeScript, and Vite, with Plotly charts and the Monaco
editor. It needs Node.js 20.19 or newer.

```bash
make ui                       # install the frontend's packages and build it into frontend/dist
make serve                    # then open http://127.0.0.1:8000: the app and the API, from one server
```

- **Profiles:** create one (blank, or a copy of another), switch between them, rename, delete, and restore. The
  overview lists every document a profile can have, with a description, and its scenarios.
- **Documents** are edited as YAML in an editor that knows each document's schema. It offers completion, shows
  descriptions on hover, and underlines problems as you type. When saving finds a problem, the editor marks the line
  it points at, and it lists problems in other documents the change would break. Every save is a revision. The
  History tab shows diffs between any two revisions and can restore one.
- **Balances:** a grid of every account's balance (and cost basis), saved as one revision without touching the rest
  of the file.
- **Scenarios:** clone, rename, and delete them, edit them (including `overrides`), and run them deterministically or
  with Monte Carlo.
- **Results:**
  - probability of success, with success criteria you can change without rerunning
  - a percentile cone of net worth (today's or nominal dollars)
  - one path in detail (median or any other), with balances by account type, taxes by type, income by source, the
    year-by-year table, and the ledger
  - every chart can switch to a table of its numbers
- **Run history** reopens past results without rerunning. **Compare scenarios** runs two to four scenarios on the
  same paths and shows the differences.

Developing the UI:

```bash
make serve                    # the API, in one terminal
make ui-dev                   # the UI with hot reload at http://127.0.0.1:5173 (forwards /api to the API)
make ui-test                  # typecheck, unit tests (Vitest), and formatting (Prettier)
cd frontend && npx playwright install chromium   # once, for the browser tests
make e2e                      # browser tests against a throwaway database (build first: make ui)
make api-types                # after changing the API: regenerate frontend/openapi.json and the TypeScript types
```

`tests/api/test_frontend_types.py` fails when the API changes without `make api-types`.

---

## 4. Annual Timeline Simulation Lifecycle

For every simulated year $t$ within each iteration $i$, the engine executes the following linear stages:

```
[Start of Year Tick]
        │
        ▼
1. INGEST SCHEDULED EVENTS
   - Spawn new accounts (e.g., non-spouse inherited IRAs).
   - Inject windfalls, real estate liquidations, or one-off capital expenses.
        │
        ▼
2. BASE INFLOW GENERATION
   - Credit active wages, Social Security benefits, and pensions to CashBook.
   - Taxable accounts run dividend pass-throughs (reinvesting cash and logging capital gains).
        │
        ▼
3. EXECUTE MANDATORY POLICIES & CONVERSIONS
   - Process SECURE Act 10-year inherited IRA liquidation distributions.
   - Process Required Minimum Distributions (RMDs) for accounts reaching statutory ages.
   - Execute scenario-defined Roth conversions (e.g., filling brackets up to 22%).
        │
        ▼
4. EXPENSE SATISFACTION & DEFICIT RESOLUTION
   - Debit lifestyle spending (adjusted by cumulative inflation) and fixed debt service.
   - If CashBook balance < 0: Walk account withdrawal priority (Taxable → Deferred → Roth).
        │
        ▼
5. TAX CALCULATION & IRS SETTLEMENT
   - Index tax brackets and deductions by cumulative inflation.
   - Stack Capital Gains on top of Ordinary Taxable Income; evaluate NIIT surtaxes.
   - Debit final calculated tax bill from CashBook; clear any secondary liquidity deficits.
        │
        ▼
6. SURPLUS SWEEP
   - If CashBook balance > 0: Sweep excess capital into investment accounts 
     (Tax-advantaged limits prioritized when pre-retirement; taxable brokerage post-retirement).
        │
        ▼
7. ASSET ALLOCATION & MARKET GROWTH
   - Update Target Date glide path equity/bond weights for the upcoming year.
   - Apply stochastic equity and bond return vectors to all surviving balances.
        │
        ▼
8. TELEMETRY CAPTURE
   - Write year-end state to master 3D tracking array: (Simulations × Years × Buckets).

```

---

## 5. Development Roadmap & Implementation Phases

The phased roadmap, decisions, design notes, and open questions are maintained in [PLAN.md](PLAN.md).
