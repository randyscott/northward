# Northward: Implementation Plan

This is the working plan for turning the design in [README.md](README.md) into a finished tool.
Update it as phases complete or decisions change. Each phase lists what it delivers and the
checks that mark it done.

_Last updated: 2026-10-23 (rev 20: published as Northward)_

> **History note.** Northward was developed as `finsim` in a private repository, and this public repository starts
> from a single commit made on 2026-10-23. Commit hashes and `phase-*` branches mentioned below belong to that private
> history. The plan's examples use the sanitized example household (Alex, Jordan, Sam); real profiles are kept out of
> git (D44).

---

## 1. Current State (as of commit `1ffa534`)

**What exists**

| Area | Status |
|---|---|
| `backend/household.py` | Loads and validates `household.yaml` using hand-written dict checks. `Member` and `Household` classes. |
| `backend/account_type.py` | Loads `account_types.yaml`, checks enums and the recursive `custom_fields` schema. |
| `backend/account.py` | Loads `accounts.yaml` and checks owner, type, and custom fields against the household and account types. `Account` has no behavior yet (TODO). |
| `backend/run.py` | Smoke script that prints the loaded objects. Works from the repo root: `python3 backend/run.py`. |
| `data/profile/*` | Household, accounts, and income filled in. `liabilities.yaml` is empty. |
| `data/rules/*` | Account types. Federal taxes for 2026 (MFJ and single only). |
| `data/scenarios/base.yaml` | Inflation and salary-growth assumptions only. |
| `frontend/` | Empty and not tracked by git. |
| Tooling | None: no `pyproject`, dependency list, tests, or linter. Python 3.10.12, pydantic 2.11.7, and numpy 2.2.6 are installed. |

**Not yet loaded or defined:** income streams, liabilities, spending/expenses, Social Security inputs
and rules, market return assumptions, glide path definitions, simulation horizon, withdrawal order,
Roth conversion levers, contribution rules, mortality, healthcare, and state tax.

### 1.1 Issues found in the existing code and config

These are fixed as part of Phase 1 unless noted otherwise.

1. ✅ *(Phase 0)* **The README layout doesn't match the repo.** The README describes `config/rules/tax_brackets.yaml`,
   `social_security.yaml`, and `scenarios/base_case.yaml`. The repo actually has `data/rules/taxes.yaml`,
   no SS file, and `data/scenarios/base.yaml`. **Decision:** keep `data/` and the current names, and update the README.
2. ✅ *(Phase 1)* **The `asset_strategy` schema doesn't match the data.** [account_types.yaml](data/rules/account_types.yaml)
   defines `custom_allocation: {stocks, bonds, cash}`. [accounts.yaml](data/profile/accounts.yaml) uses
   `kind: static_allocation` with `stocks/bonds/cash` at the top level. Nested values are never validated, so the loader doesn't catch this.
   `kind` is also not an enum.
3. ✅ *(Phase 1)* **Custom-field validation ignores `required`.** [account.py:63-68](backend/account.py#L63-L68) treats every
   declared custom field as required and never checks value types.
4. ✅ *(Phase 1)* **Dead code.** `get_account_type_by_name` raises on a miss, so the `None` check at
   [account.py:58-60](backend/account.py#L58-L60) never runs. `account_type_names` at line 56 is unused.
5. ✅ *(Phase 1)* **Joint ownership resolves to `owner=None`.** There is no explicit joint model, and
   `ownership_constraint` is never enforced (an `individual_only` account could be marked joint).
6. ✅ *(Phase 1)* **RMD age is hard-coded to 73** in the account type. Under SECURE 2.0 the RMD age depends on birth year:
   73 for people born 1951–1959 and **75 for 1960+**. Both household members fall in the 75 group. RMD age belongs in the
   rules, keyed by the owner's birth year, not on the account type.
7. ✅ *(Phase 1)* **Savings and checking use `annual_dividend_drag: true`.** They should produce interest, taxed as ordinary
   income. Brokerage dividend yield and the qualified-dividend ratio are market assumptions, not account-type flags.
8. ✅ *(Phase 1)* **`taxes.yaml` gaps.**
   - It has no MFS or HoH brackets, even though the `filing_status` enum allows both. HoH has a standard deduction but no brackets.
   - The capital-gains thresholds need checking against IRS Rev. Proc. 2025-32. The comment says "0% up to
     top of 12% bracket", but TCJA indexes LTCG thresholds separately from the ordinary brackets, and the values look wrong.
   - The OBBBA senior deduction ($6,000 per person age 65+, 2025–2028, phased out by MAGI) is missing.
   - There are no FICA parameters.
9. ✅ *(Phase 0)* **Loaders use flat imports** (`import household`), which only work when `backend/` is the script directory.
   There is no package structure.
10. ✅ *(Phase 7)* **Personal data is committed** (real names and balances in `data/profile/`). The repo has no remote, so this is low
    risk today. Phase 7 fixes this: real profiles live in the git-ignored database, and only a sanitized
    `data/profiles/example/` is committed. Git history still holds the old files, so rewrite it before adding a
    remote (the README has the command).
11. ✅ *(Phase 0)* **Uncommitted working-tree changes** (removed comment blocks in `account.py` and `household.py`) should be
    committed before Phase 0 starts.

---

## 2. Decisions

| # | Decision | Choice | Source |
|---|---|---|---|
| D1 | Config validation | **Pydantic v2.** Replace the hand-written checks. Account-type-specific fields become typed, discriminated models instead of YAML-declared `custom_fields`. | User, 2026-09-29 |
| D2 | Monte Carlo execution | **Scalar per-path engine plus a process pool.** NumPy pre-samples every return and inflation path as `(sims × years × assets)` arrays. One readable engine runs each path. The ledger is off for MC runs and on for deterministic and drill-down runs. | User, 2026-09-29 |
| D3 | Frontend | **FastAPI backend plus a React + Vite + TypeScript SPA** in `frontend/`, with Plotly.js charts. API types are generated from FastAPI's OpenAPI schema. | User, 2026-09-29 |
| D4 | Scope | **In scope:** state income tax, mortality and survivor transitions, healthcare costs (ACA, Medicare, IRMAA, HSA), and payroll tax plus contribution limits. | User, 2026-09-29 |
| D5 | State tax | **Generic engine** (flat or bracketed, with exemption flags for SS, pensions, and retirement income), plus a placeholder rule file for the user to fill in. | User, 2026-09-29 |
| D6 | Social Security input | **PIA at FRA** from the SSA statement. The engine applies claiming reductions and credits, spousal and survivor benefits, and COLA. Computing PIA from earnings history is backlog. | User, 2026-09-29 |
| D7 | Time step | **Annual**, by calendar year. `birth_month` is used for the 59½ threshold, partial-year SS in the claim year, and FRA month math. | Default |
| D8 | Dollar basis | **Nominal internally.** Real (today's dollars) values for reporting come from dividing by the cumulative simulated CPI. | Default |
| D9 | Tax indexing | Brackets and deductions are indexed by the **simulated** inflation path. Statutory fixed thresholds (NIIT, SS provisional income) stay unindexed. | Default (matches `taxes.yaml`) |
| D10 | Cost basis | **Average-cost** for taxable accounts. Specific-lot tracking and tax-loss harvesting are backlog. | Default |
| D11 | Tax circularity | Taxes are settled by a **gross-up solver**: withdraw, recompute tax, and repeat until the change is under $1 (bounded iterations), because withdrawing to pay tax creates more tax. | Default |
| D12 | Randomness | Every stochastic run takes an explicit **seed**, so any result can be reproduced exactly. | Default |
| D13 | Data storage | **Database-backed documents.** Each YAML config is stored as text in a row with typed metadata columns (profile, scenario, kind, name, schema version). Pydantic is the only schema: documents are validated on write and parsed on read. SQLAlchemy 2.0 + Alembic, starting on **SQLite**. Moving to Postgres or MySQL should only need a new connection URL. | User, 2026-09-29 |
| D14 | Where each kind of data is mastered | **Rules:** files in `data/rules/` are the master copy (reviewed in git). They are upserted into the DB by a re-runnable seed and are shared by all profiles. **Profiles and scenarios:** seeded once from `data/`, after which the DB is the master copy. `northward db export` dumps everything back to YAML for backups and diffs. | User + default, 2026-09-29 |
| D15 | Revisions | Editing a document **appends a new revision** instead of overwriting. Runs record the exact revision IDs they used, which gives undo, change diffs, and exact reruns. | Default |
| D16 | Rule versioning | Rule sets are versioned by tax year (e.g. `federal_2026`). A scenario pins a rule-set version or `latest`, so a new tax year never silently changes old results. | Default |
| D17 | Users | **Single user for now.** Multi-user with login is deferred to Phase 10. To keep that change additive, profiles carry a nullable `owner_user_id`, and all profile-scoped data access goes through a repository layer that can be scoped per user later. | User, 2026-09-29 |
| D18 | YAML round-tripping | Use **`ruamel.yaml`** wherever YAML is edited and re-serialized, so comments and key order survive. Phase 1 only reads YAML, so it uses PyYAML; ruamel.yaml arrives with editing in Phase 7. | Default |
| D19 | Spending model | **One base annual amount** does most of the work. **Categories** are added on top, each one-off, recurring every N years, or active for a window, and each anchored to a calendar year, a member's or dependent's age, or a life event. See §4.1. | User, 2026-09-29 (Q1) |
| D20 | Glide path | **Linear** equity glide path to the target year, then flat. Default endpoints: 90% equity 40+ years out, 50% at the target year. An optional post-target segment exists in the schema but is off by default. See §4.2. | User, 2026-09-29 (Q2) |
| D21 | Market assumptions | **Named presets in a rules file**, which each scenario selects and can override. The default is a moderately conservative forward-looking preset. Means are arithmetic and nominal, and sampled as correlated lognormals. See §4.3. | User, 2026-09-29 (Q3) |
| D22 | Dependents | **First-class household entities** that drive both spending (age-anchored categories) **and tax**: credits, filing status (HoH and Qualifying Surviving Spouse), 529 accounts, SS child benefits, and ACA household size. See §4.4. | User, 2026-09-29 (Q11) |
| D23 | 529 and dependent-care FSA | **Both are modeled from the start** (they exist today). 529s are accounts in `accounts.yaml`. The dependent-care FSA is a payroll election on a salary income stream, not an account. See §4.5. | User, 2026-09-29 (Q12) |
| D24 | Payroll contributions | **401(k) deferrals, the employer match, and payroll HSA contributions are salary `elections`, and they are simulated from Phase 2**, because the accumulation years are wrong without them. Deferrals can be a percent, a dollar amount, or `max` (the indexed limit, optionally including catch-ups). Traditional catch-ups name a `roth_catch_up_account` for the SECURE 2.0 Roth catch-up rule. See §4.6. | User, 2026-09-29 |
| D25 | Deterministic returns | A deterministic run uses one constant return per asset class. By default that's the **geometric mean** implied by the preset (7%/17% stocks gives about 5.7%), since the arithmetic mean overstates a typical compounded outcome. `market.deterministic_returns: arithmetic` switches it. With zero volatility the two are equal, so Phase 6's zero-variance check still holds. | Default, 2026-09-29 |
| D26 | Annual timing | In the retirement year, salary and payroll contributions (including `max` limits) are prorated by the months before the retirement birthday. Market returns apply to year-end balances, so the year's flows are effectively at the start of the year. Taxable-account income is credited on start-of-year balances. | Default, 2026-09-29 |
| D27 | Cash handling | Each year's cash clears to zero. A deficit is covered by the withdrawal order (cash accounts before selling brokerage holdings within `taxable`), and a surplus goes to `levers.surplus_sweep` targets in order. A target can stop at `up_to_balance` (a reserve). The default target is the first brokerage account. Before 59½ (65 for HSAs), withdrawals pay the additional tax unless `levers.early_withdrawals: block`. | Default, 2026-09-29 |
| D28 | Discretionary tax moves | Roth conversions and bracket-filling inherited-IRA withdrawals run **after** the year's spending and deficit withdrawals (not in Stage 3), so a fill-to-bracket amount sees all other income. The amount is solved numerically against the full tax calculation, because extra income also changes SS taxability and the senior deduction. `respect_phase_outs` also caps MAGI below the next phase-out of a benefit the household is currently getting (CTC/ODC, education credits, senior deduction). | Default, 2026-09-30 |
| D29 | Scheduled events | Expected one-time events go in an optional profile document, `events.yaml` (windfall, home sale, inheritance). Scenarios can add what-if `events`. Inheriting an IRA opens a new inherited account. | Default, 2026-09-30 |
| D30 | 529 money | Qualified withdrawals pay the beneficiary's `qualified_education` spending, leaving $4,000 out of pocket for the AOTC when it's available. What happens after the beneficiary's education ends is `levers.plan_529_leftover`: `keep` (default), `change_beneficiary`, `roth_rollover`, or `withdraw`. | Default, 2026-09-30 |
| D31 | Healthcare | Costs come from `rules/healthcare.yaml` (Medicare premiums, IRMAA, the ACA age curve, and default household assumptions). A profile's optional `health_costs.yaml` overrides the assumptions. Employer coverage (pre-tax) lasts while anyone works. Otherwise there are **unsubsidized** individual-market premiums before 65 (Q6), then Part B/D, IRMAA from MAGI two years earlier, and a supplement. Out-of-pocket costs are added, and HSAs reimburse qualified costs (by default once the owner retires). `spending.base.includes_healthcare: true` turns the model off. | User + default, 2026-09-30 |
| D32 | State tax and residence | `rules/state_tax.yaml` holds rules per state code. `household.state` picks one, and `levers.relocations` moves the household in later years. The generic engine starts from federal AGI. Wisconsin is the first full state (Q7). | User, 2026-09-30 |
| D33 | Mortality | Deterministic runs use `levers.mortality: {kind: fixed, death_ages}` (the default is none, so everyone reaches the horizon). The SSA 2023 period life table (`rules/mortality.yaml`) and a seeded sampler are ready for Phase 6. The simulation ends after the last death. | Default, 2026-09-30 |
| D34 | Social Security timing | Benefits are computed **month by month** inside each year, so claim months, deaths, survivors reaching 60, and children aging out land in the right month. | Default, 2026-09-30 |
| D35 | Success criteria | **Configurable.** By default a path succeeds when it is **never short on spending** (no year with unfunded spending or taxes beyond a $1 rounding tolerance). The other criterion is an optional **liquidity reserve floor**: year-end liquid assets (cash plus taxable accounts) never fall below an amount in today's dollars. Every enabled criterion must hold. Criteria are applied to stored telemetry after the run, so changing them doesn't need a rerun. | User, 2026-10-05 (Q8) |
| D36 | Where goals live | A new optional profile document, **`goals.yaml`**, holds the success criteria and the heirs' tax rate used for after-tax legacy. Every scenario of a profile uses it, so comparisons share one yardstick, and a scenario can still change it through `overrides`. The CLI and API can override it when computing statistics. | User, 2026-10-05 |
| D37 | Mortality in Monte Carlo | **Planning age by default:** a Monte Carlo run keeps the scenario's mortality lever, and the default `none` means everyone reaches the horizon. A new lever, `mortality: {kind: sampled}`, draws each member's death age from the SSA table per path, using common random numbers across compared scenarios. Sampled lives may run past `end_age`. In that case the horizon extends to the last death. | User, 2026-10-05 |
| D38 | Historical bootstrap | **In Phase 6.** `rules/historical_returns.yaml` holds annual 1928–2025 stocks, bonds, T-bills, and CPI (Damodaran + BLS CPI-U, with sources). The sampler resamples contiguous blocks of years (block length configurable, default 5). The `historical_us` preset is recomputed from the same data. | User, 2026-10-05 |
| D39 | Deleting profiles and scenarios | **Soft delete, plus purge.** Deleting sets `archived_at`: the item is hidden from listings, sources, and seeding until `northward db restore`. `northward db purge` permanently removes an already-deleted item with its revisions and runs. Names stay reserved until purged. | User, 2026-10-16 (Q10) |
| D40 | Editing before the API exists | **`northward db edit`** (opens `$VISUAL`/`$EDITOR` and re-offers the editor when validation fails), **`put`** (save files), and **`show`/`history`/`diff`/`revert`/`clone`**. Documents are addressed as in the data/ layout (`accounts`, `scenarios/base`). | User, 2026-10-16 |
| D41 | Validating writes | A write is a set of documents validated together: each against its model, then the profile alone and every scenario of it, loaded as they'd be after the change. Problems the change **introduces** reject it. Problems that already existed (e.g. after new rules were seeded) don't block unrelated edits. Unchanged documents add no revision. | Default, 2026-10-16 |
| D42 | Rule set names | A rule set is named for its tax year, which is `federal_tax.yaml`'s `metadata.base_year` (e.g. `2026`). `latest` is the highest year. File sources answer to `latest` and to their own year, and a scenario may write `rule_set: 2026` unquoted. | Default, 2026-10-16 |
| D43 | Run cache key | **(scenario, input hash, engine version, seed, paths)**, for completed Monte Carlo runs whose telemetry still exists. The input hash covers the documents' text but not profile, scenario, or rule-set names. The engine version is the package version plus a hash of the simulation source (everything but the CLI, API, and persistence code), so any engine change invalidates the cache without a manual version bump. | Default, 2026-10-16 |
| D44 | Real profiles in git | `data/profiles/*` is git-ignored except `example/`. The real profile was removed from the tree (and from disk) after a verified seed → export round trip; history isn't rewritten until a remote is added. | User, 2026-10-16 |
| D45 | API addressing and access | Profiles and scenarios are addressed by **name** in URLs (`/api/profiles/default/scenarios/base`), and documents by their data/ layout address (`documents/accounts`, `documents/scenarios/base`), as in the CLI. Revisions are addressed by document id. The server has **no authentication** and listens on localhost by default (D17); `northward serve --host` warns. | Default, 2026-10-19 |
| D46 | Structured edits | A document can be saved as `yaml_text` or as `data`. `data` is merged into the current text with ruamel.yaml (D18): unchanged values keep their spelling, comments, and order; list items are matched by `id`. Optional `base_revision` gives optimistic concurrency (409 when the document moved on). | Default, 2026-10-19 |
| D47 | Background jobs | Monte Carlo jobs run **one at a time** in a worker thread, each with the full process pool, whose workers are **spawned** (forking a threaded server can deadlock). The `runs` table holds queued/running/complete/failed and the running process's `pid`. At startup, runs whose process is gone are marked failed and queued runs resume. Stopping the server requeues the active run. Identical requests share one run. Progress is in memory. | Default, 2026-10-19 |
| D48 | Compare over HTTP | `POST /api/compare` is idempotent: it submits (or finds) one run per scenario on the same seed and size, returns 202 with their ids while any is unfinished, and 200 with the comparison once all are complete. | Default, 2026-10-19 |
| D49 | UI phasing | Phase 9 is split. **9A** has the whole app with a schema-aware YAML editor, and its only form is the **balance grid**. **9B** adds per-document forms. The API already accepts YAML text and structured data, so 9B needs no backend changes. Using 9A first shows which forms are worth building. | User, 2026-10-20 |
| D50 | Cash reserve (emergency fund) | `levers.cash_reserve: {account, amount}` keeps `amount` (today's dollars, indexed) in a cash or brokerage account. Withdrawals leave it in place until every other account in the withdrawal order is used up (it's the last resort, flagged in the run's warnings). Each year, once spending is covered, it's topped back up to its indexed level: from the year's cash first, then the other accounts. That way interest lagging inflation doesn't erode it. Year rows report `reserve_drawn` and `reserve_topped_up`. The liquidity floor (D35) still measures cash plus brokerage; the UI and CLI now say so. On the example's early-retirement scenario, a $50k reserve takes success from 15% to 99%, for about 2% of median legacy. | User, 2026-10-22 |

---

## 3. Target Layout

```
finance_v2/
├── pyproject.toml                # package, deps, pytest/ruff config
├── PLAN.md  README.md
├── backend/
│   └── northward/
│       ├── config/               # Pydantic models + loader
│       │   ├── base.py  anchors.py  household.py  accounts.py  income.py  liabilities.py  spending.py
│       │   ├── rules/            # account_types, federal_tax, contribution_limits, rmd, social_security,
│       │   │                     #   glide_paths, market, state_tax, healthcare
│       │   ├── scenario.py       # levers + market preset selection + overrides
│       │   ├── overrides.py      # dotted-path patches (list items addressed by id)
│       │   ├── versioning.py     # schema_version upgrade registry
│       │   ├── source.py         # ConfigSource interface: FileSource now, DbSource in Phase 7
│       │   └── loader.py         # compose rules + profile + scenario → SimulationInput
│       ├── ledger/               # Transaction, TaxCategory, Books (cash clearing, balances, log, tax totals)
│       ├── accounts/             # state.py (balances, basis), allocation.py (glide paths, returns), growth.py
│       ├── tax/                  # indexing.py, inputs.py (TaxInputs), federal.py (FederalTax, TaxReturn), credits.py, state.py
│       ├── policy/               # limits.py, withdrawal.py, sweep.py, contributions.py, rmd.py, conversions.py,
│       │                         #   bracket_fill.py, plan_529.py
│       ├── income/               # wages.py (salary + payroll elections), social_security.py, streams.py (pension/other)
│       ├── lifecycle/            # dependents.py (yearly status), survivor.py (estates), healthcare.py, mortality.py
│       ├── expenses/             # spending.py (base + categories + FSA reimbursement), debt.py (loans)
│       ├── engine/               # year_step.py (8 stages), events.py (stage 1), taxes.py (stage 5), simulate.py, timeline.py,
│       │                         #   market.py (MarketPath), context.py, state.py, results.py, export.py
│       ├── montecarlo/           # samplers.py, runner.py (pool + drill-down), telemetry.py (.npz), stats.py, report.py
│       ├── persistence/          # models.py, db.py (engine, Alembic), repositories.py, source.py (DbSource),
│       │   │                     #   seed.py (seed/export/backup), runs.py (recorded runs, cache), commands.py (CLI)
│       │   └── migrations/       # Alembic
│       ├── api/                  # FastAPI app (Phase 8)
│       ├── fingerprint.py        # engine version for the run cache
│       └── cli.py                # `northward validate|show-config|run|mc|stats|compare`, `northward db ...`, `northward runs ...`
├── tests/                        # mirrors northward/; golden-file & hand-computed cases
├── data/
│   ├── rules/                    # one rule set (base year inside each file): account_types, federal_tax, state_tax,
│   │                             #   social_security, rmd, contribution_limits, healthcare, glide_paths,
│   │                             #   market_assumptions, mortality, historical_returns
│   └── profiles/
│       ├── <real profiles>/      # git-ignored; imported once by `northward db seed`, then the DB is the master copy
│       └── example/              # sanitized example profile (+ scenarios/) for tests/demo
├── var/                          # git-ignored runtime state
│   ├── northward.db                 # SQLite database
│   ├── runs/                     # run outputs, one folder per run id (telemetry .npz, years.csv, ledger)
│   ├── export/  backups/         # `northward db export` / `northward db backup`
└── frontend/                     # React + Vite + TS (Phase 9A/9B)
```

---

## 4. Phases

Each phase ends with passing tests and a runnable demo (CLI output, then API, then UI).

### Phase 0 — Project foundation ✅ (done 2026-09-29, branch `phase-0-foundation`)

- Commit the pending working-tree changes.
- Add `pyproject.toml` with the `northward` package under `backend/`, pinned deps (pydantic, numpy, pyyaml; ruamel.yaml is added in Phase 1
  and sqlalchemy, alembic, fastapi, and uvicorn in later phases), pytest, and ruff. mypy was deferred.
- Create the package skeleton from §3 and move the existing loaders into `northward/config/` as a starting point.
- Set up `tests/` and a `make test` / `make lint` (or `just`) entry point.
- Update the README directory section to match `data/` (issue 1).

**Done when:** `pip install -e .` works, and both `pytest` (one smoke test that loads the current YAML) and `ruff` run clean.

**Outcome:** `make install|test|lint|format`. `northward show-config` (also `python -m northward show-config`) replaces
`backend/run.py`. The loaders live in `northward/config/{household,account_types,accounts}.py` and still use the old
hand-written validation until Phase 1. 4 tests pass and ruff is clean.

### Phase 1 — Configuration schema and Pydantic models ✅ (done 2026-09-29, branch `phase-1-config`)

- **Models:** `Household`/`Member`, `AccountType`, `Account` (discriminated union by type family), `IncomeStream`
  (salary, pension, other), `Liability` (amortizing, interest-only, payoff date), and a **new `Spending`** document
  (base amount plus categories, per §4.1).
- **Dependents:** `household.yaml` gains a `dependents` list (schema in §4.4). Spending categories can anchor to a dependent's age,
  and the tax, SS, and healthcare phases read each dependent's status for the year.
- **Payroll elections on salary streams:** `income.yaml` salary entries gain an optional `elections` block:
  retirement deferrals, employer match, HSA, and dependent-care FSA. See §4.5 and §4.6.
- **529 account type:** owner is a member, with a `beneficiary` dependent. Tax-free growth. Qualified withdrawals pay
  education costs tax-free. Non-qualified withdrawals tax the earnings share as ordinary income plus a 10% penalty.
- **`AssetStrategy`:** a discriminated union of `target_date{target_year, glide_path}` (default `linear_default`) and
  `static_allocation{stocks, bonds, cash}`, with weights validated to sum to 1 (issue 2). Glide paths are defined in
  `data/rules/glide_paths.yaml` (§4.2).
- **Ownership:** an explicit `owner: <member_id> | joint`, validated against `ownership_constraint` (issue 5).
- **Rules models:**
  - Federal tax: all four filing statuses plus Qualifying Surviving Spouse, the senior deduction, FICA, and a **`credits`**
    section (CTC/ACTC, Credit for Other Dependents, AOTC, Lifetime Learning, Child and Dependent Care), with per-field indexing flags.
  - RMD: Uniform Lifetime table, start age by birth year, and Single Life table for inherited accounts.
  - Contribution limits by year: 401(k) including age 50+ and age 60–63 catch-ups, IRA, HSA, and the Roth IRA income phase-out.
  - SS parameters: FRA by birth year, reduction and delayed-credit factors, spousal/survivor/child factors, and the
    family-maximum formula.
  - Healthcare and state-tax file stubs.
- **Scenario model:**
  - Horizon (start year, end age or year).
  - Macro assumptions (inflation, wage growth).
  - **Market assumptions:** a preset name from `data/rules/market_assumptions.yaml`, plus optional per-field overrides (§4.3).
    The inflation block currently in `base.yaml` moves into the preset, so that inflation is correlated with returns.
  - Levers: retirement ages, SS claim ages, withdrawal order, Roth conversion policy, and contribution policy.
  - **Overrides** (a scenario may patch any profile value, e.g. `members.alex.target_retirement_age: 62`).
- **Loader:** composes rules, profile, and scenario into one immutable `SimulationInput`, with cross-reference validation
  (owners exist, types exist, and no RMD-bearing account is joint).
- **`ConfigSource` interface:** the loader reads raw YAML documents by `(kind, name)` through this interface, never
  through file paths. Phase 1 provides `FileSource` (reads `data/`). Phase 7 adds `DbSource`. The engine, CLI, and
  tests depend only on `SimulationInput`, so they never touch the database.
- Every document carries a top-level `schema_version`. The loader has a place to register upgrade
  functions, so stored documents stay readable as the schema evolves (D13).
- Update the YAML files to the new schema. Remove `custom_fields` from `account_types.yaml`, fix issues 6–8, and
  verify the 2026 tax figures.

**Done when:** every data file loads into typed models. Bad inputs (unknown owner, weights ≠ 1, joint IRA,
missing bracket table) fail with clear errors, and each has a unit test.

**Outcome:**
- `load_simulation_input(source, profile, scenario)` returns a frozen `SimulationInput` (rule set, profile, scenario,
  resolved market preset). All problems are collected into one `ConfigError`, and each is reported as
  `file: path[item-id].field: message`. `northward validate` checks every profile/scenario; `northward show-config` prints one.
- 96 tests: model-level validation, every cross-reference check, overrides, schema upgrades, and the four named cases.
- The 2026 figures were verified against primary sources (Rev. Proc. 2025-32, Notice 2025-67, Rev. Proc. 2025-19,
  P.L. 119-21, 26 CFR 1.401(a)(9), 20 CFR 404, SSA POMS). The sources are listed in each rules file's `metadata`.
  The capital-gains thresholds in the old `taxes.yaml` were wrong (e.g. the MFJ 0% bracket top is 98,900, not 100,800).
- Changes from the plan text above:
  - Account types declare a `family` (code-defined behavior) instead of `custom_fields`, and accounts are validated
    against their family's model.
  - Data layout is `data/profiles/<profile>/` with scenarios under each profile, matching the Phase 7 ownership model.
  - `ByFilingStatus` tables default qualifying surviving spouse to the MFJ value but allow an explicit value, and use
    `null` for "ineligible".
- Still placeholders in `profiles/default`, marked `TODO(Q1/Q11/Q12)`: spending amounts, dependents, 529 accounts,
  and the FSA election.

**Rule details later phases must honor** (found while verifying the 2026 rules):
- QSS files with MFJ brackets and standard deduction, but gets unmarried thresholds for the Additional Medicare Tax,
  SS taxability, the CTC phase-out, the senior deduction, education credits, and the care credit's second stage.
- The senior deduction phases out **per person** (6% of excess MAGI from each $6,000). It is gone by MAGI $250,000 on a joint
  return, and MFS can't claim it.
- The care-credit rate steps count "each $2,000 **or fraction**" of AGI over the threshold (use ceiling division).
- The Roth catch-up rule applies from 2026: catch-ups must be Roth when prior-year FICA wages exceed $150,000 (indexed).
- Survivor benefits use a separate, later-phased full-retirement-age table (67 only for births 1962+).
- The RMD applicable age for births in 1959 is 73 only under proposed regulations. Anyone born in 1960 or later is in
  the age-75 group.
- Inherited-IRA annual RMDs use the larger of the beneficiary's and decedent's remaining life expectancy.
- Spousal benefits are based on the worker's PIA (not their delayed-credit amount), and deemed filing applies at all ages
  for anyone born 1954+.

### Phase 2 — Ledger, accounts, and deterministic engine ✅ (done 2026-09-29, branch `phase-2-engine`)

- **Ledger:** a frozen `Transaction` dataclass (`year, amount, account/source_dest, description, TaxCategory, member`).
  Extend `TaxCategory` beyond the README's four to what the tax engine needs: `WAGES, ORDINARY,
  INTEREST, QUALIFIED_DIVIDEND, LTCG, STCG, SS_BENEFIT, TAX_FREE, PENALTY, TAX_PAYMENT,
  PRE_TAX_CONTRIBUTION, NONE`. `CashBook` holds the balance and the transaction log, with an optional recording-off mode for MC.
- **Account behaviors:** `deposit`, `withdraw(amount) → Transaction[]` (tax character by wrapper; average-cost
  basis for taxable accounts), `apply_growth(returns, allocation)`, and `yield_income()` (interest, dividends).
- **Portfolio:** looks up accounts by owner, wrapper, or id. Glide-path allocation for the year.
- **`engine/year_step.py`:** implements the 8 README stages in order. Tax in this phase uses a simple
  resolver that Phase 3 replaces.
- **Wages** with salary growth, stopping at retirement (partial year by `birth_month`).
- **Payroll elections** (D24, §4.6), processed with wages in Stage 2:
  - Deferrals: `percent` of gross pay, a fixed `amount` (indexed), or `max`. `max` is the indexed elective-deferral limit
    (402(g), per person), less the member's other deferrals, plus the age-based catch-up if `include_catch_up` is set:
    50+ normally, and the larger amount in the years the member turns 60-63. Limits round down to the rules' rounding step.
  - Roth catch-up rule: when the member's prior-year wages exceed the indexed threshold, the catch-up goes to
    `roth_catch_up_account` instead of a traditional account.
  - Employer match from the tiers, on the employee's deferrals as a share of pay. It is always deposited pre-tax.
  - HSA: the indexed self-only or family limit (plus the 55+ catch-up if set), less the employer amount.
  - Tax character: traditional deferrals, HSA payroll contributions, and the FSA reduce taxable wages. HSA payroll
    contributions and the FSA are also excluded from FICA wages. Roth deferrals reduce neither.
  - Elections stop at the salary's end (retirement by default).
- **Spending and liabilities:** base amount plus active categories for the year (§4.1), indexed per category; loan
  amortization and payoff. The ledger records each category as its own transaction so the UI can break spending down.
- **Withdrawal waterfall:** configurable order (default Taxable → Deferred → Roth, with HSA last), with
  pre-59½ access blocked or penalized per config.
- **Surplus sweep:** by configurable priority, and only into accounts that allow contributions.
- **Deterministic mode:** fixed returns and inflation from the scenario. Output is a year-by-year state table plus the full ledger (CSV/JSON)
  via `northward run`.

**Done when:** a hand-computed 3-year, 1-person, 2-account case matches to the cent. The full household runs
to age 95 without errors. A two-earner household's contributions hit the published limits in 2026: one member defers
$24,500 traditional plus an $8,000 Roth catch-up, the other defers $24,500 Roth, and the HSAs total $4,400 each, one
including a $500 employer amount. The catch-up rises to $11,250 in the years its member turns 60-63. Cash is conserved: Σ credits − Σ debits = Δ(cash + account balances) − growth.

**Outcome:**
- `simulate(sim, path=None, record=True)` runs the eight stages each year and returns per-year `YearState`s, the
  transaction ledger, and warnings. `northward run --profile P --scenario S [--out DIR] [--format csv|json] [--no-ledger]`
  prints a summary and writes `years.csv` (flows, taxes, balances, spending by category) and `ledger.csv`.
- The engine reads market outcomes from a `MarketPath`, so Phase 6 only has to supply sampled paths.
- The tax resolver (`tax/simple.py`) covers ordinary brackets, the standard deduction (plus the 65+ amount), capital-gains
  stacking, FICA (SS wage base, Medicare, Additional Medicare), and the early-withdrawal and HSA additional taxes. Settlement
  iterates until the tax on withdrawals made to pay tax is negligible (the D11 solver, now in place).
- 141 tests. They include the hand-computed 3-year case (to the cent), the 2026 contribution limits and the 60-63
  catch-up on a two-earner household, and a check that value is conserved every year for every committed scenario.
- Also checked against a full real household's 2026 elections and a hand-computed tax. The run's FSA warning (a
  dependent-care FSA forfeited because no spending was tagged `dependent_care`) showed the warnings at work.

**Phase 2 simplifications that later phases lift:**
- ~~Phase 3~~ ✅: capital losses and carryforwards, NIIT, SS taxability, the senior deduction, and credits are in place.
- ~~Phase 4~~ ✅: RMDs, Social Security, Roth conversions, scheduled events, 529 withdrawals, and IRA limits/deductibility are in place.
- Phase 5:
  - No healthcare costs.
  - No mortality: `death` anchors never occur.
- Backlog:
  - Roth withdrawals are always tax- and penalty-free (no contribution-basis or 5-year tracking).
- Approximations:
  - A penalty age counts as reached for the whole year it falls in.
  - The first year's Roth catch-up test uses the current salary as the prior-year wages.

### Phase 3 — Federal tax, payroll, and settlement ✅ (done 2026-09-30, branch `phase-3-tax`)

- **Ordinary income:** progressive brackets, standard deduction plus the age-65 additional, the senior deduction with MAGI phase-out,
  and pre-tax contributions excluded from wages.
- **LTCG and qualified dividends** stacked on top of ordinary taxable income. **NIIT** on investment income above the MAGI threshold.
- **SS taxability** using provisional income (the 0/50/85% tiers, unindexed).
- **10% early-withdrawal penalty** (and 20% on non-medical HSA withdrawals before 65).
- **FICA:** SS wage base, Medicare, and Additional Medicare 0.9%, per earner.
- **Inflation indexing** of the thresholds listed in `indexing.applies_to`, using the simulated CPI.
- **Dependent status per year** (§4.4): decides which dependents qualify for which credit, and whether HoH or QSS is available.
- **Credits**, applied after the regular tax plus the LTCG tax:
  - Child Tax Credit (under 17), with the refundable Additional CTC portion.
  - Credit for Other Dependents (17+ dependents, full-time students under 24).
  - American Opportunity Credit (first 4 years of post-secondary; 40% refundable) and Lifetime Learning Credit. The engine
    automatically picks the better of the two per student. Expenses come from spending categories tagged `qualified_education`,
    minus any amount paid from a 529, since the same dollars can't be used for both.
  - Child and Dependent Care Credit (under 13), from categories tagged `dependent_care`. The dependent-care FSA
    election is excluded from wages for both income tax and FICA, and the FSA amount is subtracted from the expenses that can
    count toward the credit (§4.5).
  - Each credit has its own MAGI phase-out, with the indexing flag set per the statute (for example, the CTC phase-out thresholds are
    not indexed). Nonrefundable credits are limited to tax liability, applied in IRS order.
- **Gross-up solver** (D11) so that tax-driven withdrawals converge. Credit phase-outs are part of the loop.
- **Tax report per year:** AGI, MAGI, taxable income, marginal and effective rates (including the extra marginal rate
  caused by credit phase-outs), credits claimed per dependent, and a breakdown by component. Phase 4 uses these for
  bracket-fill conversions, and Phase 5 uses them for IRMAA and ACA.

**Done when:** results match IRS worked examples and a few hand-checked returns, including an LTCG case that straddles the
0%/15% boundary, NIIT, 85% SS taxability, a CTC phase-out case, an AOTC-vs-529 coordination case, and a HoH return. Every
solver case converges within the iteration limit.

**Outcome:**
- **Structure:** the engine builds a plain `TaxInputs` record each year (`engine/taxes.py`). `FederalTax.compute`
  (`tax/federal.py`) returns a full `TaxReturn`:
  - Income: AGI, taxable Social Security, capital gains after the loss limit, and the carryforward.
  - Deductions: standard deduction, senior deduction, and taxable income.
  - Tax: ordinary and capital-gains tax, the credits breakdown (with per-dependent attribution), income tax after
    credits, NIIT, FICA, and the additional taxes.
  - Rates: marginal (measured on $100 more ordinary income, so it includes phase-out effects) and effective.
  - `years.csv` carries all of these.
- **Credits** (`tax/credits.py`), applied in IRS order: the care credit (expense cap reduced by FSA benefits, and limited to the lower
  earner's earned income), AOTC (40% refundable) and LLC, then CTC and ODC with the refundable ACTC. Refundable credits
  can produce a refund, which is paid to cash.
- **Dependent status** is derived each year (`lifecycle/dependents.py`). HoH or QSS without a qualifying dependent
  falls back to single, with a warning.
- **Capital losses** offset $3,000 a year ($1,500 MFS), and the rest carries forward across years.
- **Settlement** grosses up each extra withdrawal by the tax rate observed on the previous one (a secant step). It converges in 3-5
  rounds (previously up to 13), even at 37% plus the 10% penalty or inside a phase-out. A gross-up can overshoot by a few
  dollars, and the excess is swept.
- **Tests:** 177. That includes 29 hand-checked 2026 returns covering every "done when" case plus the senior-deduction phase-out and
  marginal rate, the care-credit rate breakpoints, capital losses, and dependent-status rules.
- Also checked against a full real household's 2026 return (AGI, child tax credit, NIIT, marginal and effective rates).

**Phase 3 simplifications:**
- MAGI equals AGI for every provision (no foreign-income or tax-exempt-interest adjustments).
- Every dependent and member is assumed to have a valid SSN.
- Qualifying relatives' gross-income and support tests aren't modeled.
- The care credit's student and disabled-spouse earned-income exception isn't modeled.
- The standard deduction is always taken (itemizing is backlog).
- AOTC is used whenever a student is in their first four student years.
- 529 money isn't subtracted from education expenses yet, since Phase 4 adds 529 withdrawals and the $4,000 AOTC optimization.

### Phase 4 — Retirement income and policy rules ✅ (done 2026-09-30, branch `phase-4-retirement-income`)

- **Social Security:**
  - PIA at FRA per member, from `household.yaml` `members[].social_security.pia_at_fra` (monthly, today's dollars).
  - Claim age in years and months, with the early reduction (5/9% and 5/12% per month) and 8%/yr delayed credits up to 70.
  - Spousal benefit, up to 50% of the other spouse's PIA, reduced if claimed early.
  - COLA tied to simulated inflation.
  - The earnings test when claiming before FRA while still working.
  - **Child benefits:** a dependent under 18 (or under 19 and still in high school, or disabled before 22) of a worker
    who has claimed gets up to 50% of that worker's PIA. There is also a child-in-care spouse benefit (no age-62 minimum while caring for a child
    under 16). Both are capped by the family maximum. This matters here because the members are 7 years apart and may still have
    minor children when the older member claims.
  - Survivor logic is added in Phase 5.
- **RMDs:** start age by birth year and the Uniform Lifetime divisor. Stage 3 forces the distribution and credits it to cash.
- **Inherited IRA (non-spouse):**
  - Spawned by a scheduled event.
  - 10-year full liquidation, with annual RMDs in years 1–9 when the decedent had already started RMDs.
  - Strategy options: even, back-loaded, or bracket-aware.
- **Roth conversions:** fixed amount per year, or fill to the top of a target bracket (e.g. 22%), over a year window.
  Taxes can be paid from taxable accounts or from the converted amount. An optional **"respect phase-outs"** guard caps a
  conversion so that it doesn't push MAGI past a credit phase-out (AOTC, CTC) or, later, an ACA or IRMAA threshold.
- **Contributions** (payroll deferrals, match, and HSA already run from Phase 2):
  - IRA/Roth IRA contributions, with the income phase-out and the traditional-IRA deduction phase-out.
  - The §415(c) cap on employee plus employer additions.
  - HSA family-coverage rules: if either spouse has family coverage, one shared family limit is split between the spouses.
  - **529** target contributions per beneficiary, with the per-beneficiary gift-tax-exclusion guard.
  - All limits come from the rules and are indexed.
- **529 withdrawals:** pay `qualified_education` categories for the beneficiary first, then other funds. Leftover balance
  options: change the beneficiary to another dependent, roll to the beneficiary's Roth IRA (lifetime cap, 15-year account-age
  rule), or take a non-qualified withdrawal.
- **Pensions and other income streams** with start age and COLA.
- **Scheduled events:** windfalls, home sale, large one-off expenses, and inheritance.

**Done when:** SS benefit amounts match the SSA calculator for sample PIAs and claim ages, including a family-maximum case with child benefits. RMD amounts match IRS tables.
The 22% bracket-fill conversion lands within $1 of the bracket top. Contributions never exceed limits.

**Outcome:**
- **Social Security** (`income/social_security.py`):
  - Benefits are computed monthly from each member's PIA in start-year dollars and grow with CPI.
  - Own benefit with early reduction or delayed credits. SSA's published percentages match exactly (70% at 62 through 124% at 70 for FRA 67).
  - Spousal benefit, which starts when both have filed and pays the excess over the spouse's own PIA (32.5% at 62).
  - Child-in-care spouse benefit and child benefits, all capped by the family maximum ($3,435.50 for a $2,000 PIA).
  - The earnings test, with the withheld months credited back at FRA.
  - Benefits to members are taxed through the Phase 3 SS-taxability rules. Child benefits are the children's income.
- **RMDs** (`policy/rmd.py`):
  - Taken from the prior year-end balance at the owner's applicable age (75 for 1960+ births).
  - Employer plans wait while the owner still works there.
  - Inherited IRAs follow the 10-year rule, with annual RMDs from the Single Life table when the decedent had begun them. `levers.inherited_ira` picks
    `even` (default), `minimum_then_final`, or `fill_bracket`.
- **Roth conversions** (`policy/conversions.py`): fixed amount or fill-to-bracket (D28). Tax is paid from taxable accounts or withheld from the conversion
  (the withheld part is a distribution, penalized before 59½). Accounts pair automatically (a traditional IRA, then other
  traditional accounts, into the same owner's Roth IRA, then Roth 401(k)), or use explicit `pairs`.
- **Contributions** (`policy/contributions.py` and `income/wages.py`):
  - IRA limit with the 50+ catch-up, capped at earned income (spousal IRA for MFJ).
  - Roth IRA phase-out, and traditional-IRA deductibility for covered workers or their spouses (deductions reduce AGI).
  - §415(c) cap on employer additions.
  - One family HSA limit shared equally when either spouse has family coverage.
  - A 529 gift-exclusion warning.
- **529s** (`policy/plan_529.py`): qualified withdrawals (D30) are subtracted from the expenses that can earn education credits, plus the leftover policies.
- **Scheduled events** (`engine/events.py`, D29):
  - Windfalls (tax-free, ordinary, or gain).
  - Home sales (§121 exclusion $250k/$500k, selling costs, optional mortgage payoff).
  - Inheritances (cash, stepped-up brokerage, or a new inherited IRA).
- **Tests:** 222, covering every "done when" case plus the earnings test, inherited-IRA schedules, the phase-out guard, IRA
  limits and phase-outs, §415(c), family HSA, 529 AOTC coordination and leftovers, and events.
- **On a full household:** benefits start in the claim month (a partial first year), RMDs start at 75 for members
  born after 1959, and surpluses from then on are swept to the brokerage account.

**Phase 4 simplifications:**
- The PIA is treated as today's dollars indexed by CPI. Real wage growth before 62 isn't added.
- Benefit months are whole months from the claim month (the day-of-month rules are ignored). The earnings test withholds only the
  earner's own and spousal benefits, not family benefits on their record.
- Inherited-IRA RMDs use only the beneficiary's life expectancy (the decedent's isn't known).
- Nondeductible IRA basis isn't tracked, so later withdrawals are fully taxed. IRA eligibility uses the MAGI known at contribution time.
- The 529-to-Roth rollover ignores the 5-year contribution lookback and assumes the beneficiary has enough earned income.
- Home sales assume the §121 ownership and use tests are met.

### Phase 5 — State tax, healthcare, mortality, and survivor ✅ (done 2026-09-30, branch `phase-5-lifecycle`)

- **State tax (generic):**
  - A `state_tax.yaml` with `kind: none | flat | progressive`, brackets per filing status, and a standard
    deduction or exemption.
  - Flags for SS exemption, a retirement-income exclusion (amount and age), and capital gains treated as ordinary.
  - An optional **529 contribution deduction** (cap per return or per beneficiary, with carryforward on or off), since many states
    offer one.
  - Placeholder file included. State-tax settlement joins the gross-up loop.
  - A scenario can switch states in a given year (relocation).
- **Healthcare:**
  - **Pre-65:** employer premium while working, then ACA benchmark premium with a MAGI-based subsidy (the cliff rules are configurable,
    since subsidy law is policy-dependent). **Household size includes dependents** for the federal-poverty-level calculation, and
    children may qualify for CHIP instead (a configurable flag).
  - **65+:** Medicare Part B/D premiums plus **IRMAA** tiers using MAGI from two years earlier (so the engine keeps MAGI history).
  - **Out-of-pocket medical spending** with its own healthcare inflation rate. HSA withdrawals pay it tax-free.
- **Mortality:**
  - Each member gets a fixed death age (deterministic) or a death age sampled from the SSA period life table (MC).
  - Seeded, and sampled independently per spouse.
- **Survivor transitions:**
  - Filing status: the year of death stays MFJ. If the survivor has a dependent child, they file **Qualifying Surviving Spouse** for the
    next 2 years (MFJ brackets and deduction), then **Head of Household** while a qualifying dependent remains, then Single.
    With no dependent child, the survivor files Single from the next year.
  - The survivor keeps the larger of the two SS benefits.
  - SS **surviving-child benefits** (75% of the deceased's PIA per eligible child) and the **mother's/father's benefit** for a
    survivor caring for a child under 16, all capped by the family maximum.
  - The deceased's IRA and 401(k) roll to the survivor as their own (RMDs re-based to the survivor's age).
  - Joint accounts pass to the survivor with stepped-up basis on the deceased's share.
  - Spending is reduced by a configurable survivor factor.

**Done when:**
- A scenario with a death in year N shows the filing-status switch, SS switch, account retitling, and IRMAA
  lookback all happening in the correct years.
- With a minor child, the same scenario shows MFJ → QSS (2 years) → HoH → Single, and child survivor benefits
  that stop at the correct age.
- A state set to `none` produces zero state tax.
- A flat-rate state matches a hand calculation.

**Outcome:**
- **State tax** (`tax/state.py`, D32):
  - Covers flat or bracketed states, SS exemption, a capital-gain exclusion, ordered retirement-income exclusions (pooled for couples,
    optional AGI cliffs, and a credit-barring choice evaluated both ways), an after-tax health-premium subtraction, the 529
    deduction with carryforward, fixed or sliding standard deductions, exemptions, the married-couple and care credits, and a state share of federal
    additional taxes.
  - State tax is part of the year's bill, the settlement loop, and the marginal rate.
  - **Wisconsin 2026** comes from DOR primary sources: 3.5/4.4/5.3/7.65% brackets, the sliding deduction (with HoH's single floor), $700/$250 exemptions,
    SS exempt, the 30% gain exclusion, the age-67 subtraction ($24k each, pooled to $48k, forfeits credits), the $5k age-65 subtraction,
    the premium subtraction, the 529 deduction ($5,280 per beneficiary, carryforward), the married-couple credit, the care credit, and 33% of federal penalties.
    Marital property gets a double step-up.
  - Profiles can now live in WI.
- **Healthcare** (`lifecycle/healthcare.py`, D31): 2026 Part B $202.90, IRMAA tiers per filing status (with the top tier frozen until 2028),
  the KFF $625/month age-40 benchmark on the federal age curve, and default assumptions (KFF/CMS-based, all overridable). HSA
  contributions stop at Medicare.
- **Mortality and survivors** (`lifecycle/survivor.py`, D33, D34):
  - Filing status runs MFJ in the year of death, then QSS for 2 years with a dependent child, then HoH, then Single.
  - The survivor gets the larger of their own benefit and the survivor benefit (with the widow's limit and the reduction for an early start). Mother's/father's
    and surviving-child benefits (75%) are paid under the family maximum.
  - Accounts pass to the survivor (RMDs then follow the survivor's age). Brokerage accounts are stepped up: half of joint accounts, or both halves under
    community property.
  - Pensions continue at their survivor fraction, base spending is multiplied by `survivor_multiplier` (default 0.75), and
    salary, Social Security, and healthcare stop at death.
- **Tests:** 253. They include hand-checked Wisconsin returns (matching DOR's shortcut formula), the survivor sequence with SS amounts by year,
  IRMAA after a death, healthcare by stage of life, a flat-state hand calculation, relocation, and community-property basis. A new
  example scenario (`survivor`) exercises a death and a relocation in the committed-scenario checks.

**Phase 5 simplifications:**
- No ACA premium subsidies (Q6). The current-law credit (400% FPL cliff) is in the backlog.
- IRMAA has no life-changing-event appeal after a death or retirement.
- The survivor claims the survivor benefit as soon as eligible (no deliberate delay to FRA).
- Earnings-test withholding isn't applied to survivor or family benefits.
- Wisconsin items not modeled:
  - The school property tax credit and the itemized-deduction credit.
  - The $5,000 cap on the dependent-care exclusion (a $2,500 addback above it).
  - 529 recapture on non-qualified withdrawals.
  - Rounding of indexed amounts to $10.
  - Wisconsin capital-loss carryovers kept separately from federal ones.
- Qualifying surviving spouses use Wisconsin's head-of-household amounts (an assumption).
- Medigap premiums grow with healthcare inflation only (no extra attained-age increases).

### Phase 6 — Monte Carlo and telemetry ✅ (done 2026-10-05, branch `phase-6-montecarlo`)

- **Samplers:**
  - Correlated multivariate normal, lognormal, or Student-t draws for equities, bonds, cash, and inflation (Cholesky), using the distribution and bounds
    of each factor in the scenario's market-assumption preset (§4.3).
  - Historical block-bootstrap sampler (D38), which resamples contiguous blocks of real years from `data/rules/historical_returns.yaml`
    (stocks, bonds, T-bills, CPI; source: Damodaran's annual returns dataset plus BLS CPI-U). Resampling whole years keeps
    real crash, inflation, and correlation patterns intact. The `historical_us` preset is recomputed from this data.
  - Output is pre-sampled `(sims × years × factors)` arrays built from a `SeedSequence`.
- **Mortality (D37):** the scenario's lever applies as in deterministic runs. `mortality: {kind: sampled}` draws death ages per
  path from the SSA table (by member `sex`, or the average of both tables), from its own seeded stream so compared scenarios share
  the same lifespans. The horizon extends to the last sampled death when that falls after `end_age`.
- **Runner:**
  - A `ProcessPoolExecutor` fans paths out in chunks, with the ledger off.
  - Any single path can be re-run with the ledger on for drill-down (same seed and path index gives an identical result).
- **Telemetry:**
  - A 3D array `(sims × years × buckets)`. Buckets include total and per-wrapper balances, income, spending,
    federal/state/FICA tax, IRMAA, conversions, RMDs, and a shortfall flag.
  - Stored as `.npz`.
- **Goals (D35, D36):** an optional profile `goals.yaml` with the success criteria (`no_shortfall`, on by default with a $1 tolerance;
  an optional `liquidity_floor` in today's dollars) and the heirs' tax rate for after-tax legacy.
- **Statistics:**
  - Percentile bands (10/25/50/75/90) in nominal and real dollars.
  - Probability of success under the goals' criteria, which are evaluated from telemetry, so the CLI can override them without a rerun.
    Reports the failure rate for each criterion, plus the distribution of the first failure year.
  - Terminal and legacy wealth, both nominal and after-tax to heirs (deferred balances haircut by a configurable rate).
  - Lifetime taxes.
- **Scenario comparison:** run N scenarios on the **same** sampled paths (common random numbers) so differences such as
  claiming at 62 vs 70 come from the decisions, not from sampling noise.

**Done when:**
- A run with zero variance equals the deterministic engine output.
- A seeded run is bit-for-bit reproducible.
- 10,000 paths × ~50 years finish in under 60 s on this machine. That target sets the performance budget. If it's missed, profile first,
  then consider Numba or selective vectorization.

**Outcome:**
- **Samplers** (`montecarlo/samplers.py`):
  - Each path draws from its own streams, `SeedSequence(seed, spawn_key=(stream, path))`, for market normals, the Student-t mixing
    variable, bootstrap block starts, and death draws. A run therefore gives identical results however it's split across
    processes, any path can be regenerated alone, and compared scenarios share their draws. Streams are consumed in year order,
    so a longer horizon only adds years.
  - Parametric presets: correlated normals (Cholesky, with an eigen fallback for semi-definite matrices) drive `lognormal`
    factors (matching the arithmetic mean and std dev), `normal` factors, and `student_t` factors. The `student_t` factors share one
    chi-square mixing draw per year (a multivariate t, so crashes coincide), use the preset's `degrees_of_freedom` (default 5),
    and are scaled so the std dev still matches. Draws are clipped to each factor's bounds and floored at −99%. A zero std dev gives
    exactly the mean.
  - Bootstrap: `kind: bootstrap` presets resample circular blocks of `block_length` years (default 5; every year equally likely)
    from `rules/historical_returns.yaml`. That file holds 1928–2025 S&P 500 total returns, 10-year Treasury returns, and average 3-month
    T-bill yields from Damodaran's dataset, and December-to-December CPI-U from BLS (via FRED), which matches Damodaran's inflation
    column within 0.06 points. The loader fills a bootstrap preset's factors and correlations from the history for deterministic
    runs, and rejects overrides of them. `historical_us` is now these statistics as a parametric preset: stocks 11.85%/19.4%,
    bonds 4.82%/7.9%, T-bills 3.42%/3.0%, inflation 3.11%/3.9%. A test keeps it in step with the data.
- **Mortality** (`lifecycle/mortality.py`, D37): `{kind: sampled}` inverts the life table at one uniform draw per member, starting
  from the member's exact age on January 1 of the start year. A deterministic run of a sampled scenario uses each member's life
  expectancy. `Timeline` and `simulate` accept per-path death ages.
- **Runner** (`montecarlo/runner.py`): a `ProcessPoolExecutor` over chunks of paths, with the ledger off.
  `simulate_path(sim, seed, i)` re-runs path `i` with the ledger on and reproduces its telemetry row exactly. `SimulationInput`
  now records the documents it was loaded from (`SnapshotSource`) and pickles by reloading them, because Pydantic's parametrized
  generics don't pickle. Workers therefore work under any process start method, and Phase 7's input hash can use the snapshot.
- **Telemetry** (`montecarlo/telemetry.py`): 27 buckets per year:
  - price level and members alive
  - net worth, assets, liabilities, and liquid assets
  - balances per wrapper (taxable, deferred, Roth, HSA, 529)
  - income, wages, SS, and pensions
  - spending, healthcare, IRMAA, and debt service
  - federal, state, FICA, and total tax
  - RMDs, conversions, withdrawals, and shortfall

  Years after a path ends are NaN. Results are saved as `telemetry.npz` (float32, about 43 MB for 10,000 paths) along with the market
  draws and death ages.
- **Goals and statistics** (`config/goals.py`, `montecarlo/stats.py`, D35, D36):
  - `goals.yaml` (optional, overridable by scenarios and CLI flags) sets `no_shortfall` (with a $1 tolerance), an optional
    `liquidity_floor` (today's dollars, optionally from an anchor), and `legacy.heirs_tax_rate` (default 25%, applied to
    traditional and HSA balances).
  - The summary reports:
    - success probability and failure rate per criterion
    - the first-failure-year distribution
    - nominal and real percentile bands for every bucket
    - terminal net worth, after-tax legacy, and lifetime taxes
    - representative path indices for drill-down
  - `compare` pairs paths across scenarios: success gained or lost, legacy and tax differences, and P(legacy higher).
- **CLI:** `northward mc`, `northward stats <run>` (re-scores saved telemetry, e.g. `--liquidity-floor`, `--allow-shortfall`), `northward
  compare --scenario a --scenario b`, `northward run --path N --seed S`, and `make bench`.
- **Social Security COLAs never go negative:** benefits follow a ratcheted price level, since bootstrapped history includes
  deflation years.
- **Performance:**
  - Hoisting per-plan month arithmetic and the yearly family maximum out of the monthly Social Security loop, and skipping years
    before anyone files, cut a path from 23 to 18.4 ms with identical results.
  - 10,000 paths of the default profile (52 years) take 41 s on 6 cores (45 s wall including saving).
  - 10,000 bootstrap paths with sampled lifespans take 41 s.
- **Tests:** 298, up from 253. New tests cover:
  - sampler moments, correlations, Student-t tails, bounds, and stream prefix stability
  - the bootstrap block structure
  - zero variance equal to the deterministic run (base and survivor scenarios)
  - bit-for-bit reproducibility across worker counts, and drill-down equality
  - common random numbers across scenarios
  - sampled lifespans extending the horizon
  - hand-built telemetry for each success criterion, legacy, bands, and paired comparison
  - the historical data and presets, goals validation, and the COLA ratchet
  - the CLI commands
- **New example data:** an example `goals.yaml` (with a liquidity floor from Alex's retirement), a defaults-only one for the
  default profile, and an example scenario, `historical_lifespans`, that combines the bootstrap with sampled lifespans.

**Phase 6 simplifications:**
- Correlations are imposed on the underlying normals, so lognormal factors' correlations are very slightly weaker than specified
  (within 0.01 for the presets).
- Student-t draws are of arithmetic returns, floored at −99%.
- Only market returns, inflation, and (optionally) lifespans are random. Wage growth, healthcare and education spreads, and
  dividend/interest yields are fixed relative to the sampled CPI and returns, including under the bootstrap.
- In the bootstrap, bonds are 10-year Treasuries (constant maturity) and cash is the average T-bill yield.
- The life table is a 2023 period table without mortality improvement, the spouses' lifespans are independent, and a death falls
  in the middle of its year of age.
- Tax brackets and other indexed amounts follow deflation down. Only Social Security has a no-negative-COLA ratchet.
- `northward stats` reloads the profile and scenario from the current data to resolve goal anchors. *(Phase 7: `northward stats <run id>` uses the run's pinned revisions.)*
- Per-path warnings (e.g. tax non-convergence) aren't aggregated in Monte Carlo summaries. Use drill-down to see a path's warnings.

### Phase 7 — Persistence (database-backed configuration) ✅ (done 2026-10-16, branch `phase-7-persistence`)

- **Schema (SQLAlchemy 2.0 + Alembic, SQLite at `var/northward.db`):**

  | Table | Contents |
  |---|---|
  | `profiles` | `id`, `name`, `owner_user_id` (nullable, unused until Phase 10), timestamps. |
  | `scenarios` | `id`, `profile_id`, `name`, `rule_set_id` (or `latest`), `parent_scenario_id` (for clones). |
  | `rule_sets` | `id`, `name`, `tax_year`, `source_hash`. Shared across profiles. |
  | `documents` | `id`, `kind` (household, accounts, income, expenses, liabilities, scenario, federal_tax, state_tax, ...), `profile_id` / `scenario_id` / `rule_set_id` (exactly one set), `name`. |
  | `document_revisions` | `id`, `document_id`, `revision`, `yaml_text`, `schema_version`, `content_hash`, `created_at`, `note`. Append-only (D15). |
  | `runs` | `id`, `scenario_id`, `kind` (deterministic/MC), `seed`, `n_sims`, `engine_version`, `input_hash`, the pinned revision IDs, `status`, summary stats (JSON), and a path to the telemetry `.npz` in `var/runs/`. |

- **Repository layer:** all reads and writes go through repositories (`ProfileRepo`, `ScenarioRepo`, `RuleRepo`,
  `RunRepo`). Each write validates the YAML through the Phase 1 Pydantic models before storing it, so an invalid document never
  lands in the DB. The repositories are also where per-user scoping plugs in later (D17).
- **`DbSource`** implements `ConfigSource`, so the loader builds the same `SimulationInput` from the DB as from
  files. A parity test proves this.
- **CLI:**
  - `northward db init` / `northward db migrate`: create or upgrade the schema.
  - `northward db seed`: idempotent. It upserts rule sets from `data/rules/` (a new revision only when the content hash changes)
    and imports profiles and scenarios only if they aren't already present.
  - `northward db export [--profile X]`: writes YAML back out in the `data/` layout.
  - `northward run --profile X --scenario Y`: runs from the DB. File mode remains for tests.
- **Run cache:** a run with the same `input_hash` + `seed` + `engine_version` returns the stored result.
- **Data hygiene (issue 10):**
  - Create `data/profiles/example/` with sanitized values.
  - Seed the real profile into the DB, then remove `data/profile/` from git and add it to `.gitignore`. Git history
    still holds it, so rewrite history before adding any remote.
  - Git-ignore `var/`.
- **Backups:** `northward db export` plus a copy of the SQLite file. A cron or backup recipe goes in the README.

**Done when:**
- Seed, then export, then diff against `data/` shows no semantic differences.
- A `FileSource` and a `DbSource` run of the same profile give identical results.
- Editing a document creates revision N+1, and a run pinned to revision N still reproduces exactly.
- An invalid write is rejected with the Pydantic error.
- Alembic migrations run cleanly from an empty DB.

**Outcome:**
- **Schema** (`persistence/models.py`, migration `0001`): the six planned tables plus `run_revisions`, which links each run to the
  revisions it read. Constraints are named so later SQLite migrations can use Alembic's batch mode.
  - A `documents` row has exactly one owner (a CHECK constraint).
  - Foreign keys are enforced on SQLite.
  - Timestamps are UTC.
  - Two planned columns were left out, because the documents already hold them and a copy could drift:
    `scenarios.rule_set_id` (the scenario's own `rule_set` field is authoritative) and `documents.name` (the kind
    and owner identify a document).
- **Repositories** (`persistence/repositories.py`): `ProfileRepo`, `ScenarioRepo`, `RuleRepo`, and `RunRepo`.
  - `ProfileRepo.save` validates a set of changes together before writing anything (D41).
  - Soft delete, restore, and purge (D39).
  - Clones remember their parent.
  - `ProfileRepo` and `DbSource` take an `owner_user_id` for Phase 10 (None means single-user).
- **`DbSource`** (`persistence/source.py`) reads the latest revisions, a run's pinned revisions, or an overlay of unsaved
  text (used to validate a change). `RawDocument` now carries the revision id it came from. Each `SnapshotSource` has a
  name-independent `content_hash()` and lists `revision_ids()`. Parity tests check that all four example scenarios load
  equal inputs and produce identical years, ledgers, and warnings from files and from the database. Monte Carlo
  telemetry also matches.
- **Seed, export, backup** (`persistence/seed.py`): `seed` upserts rules (a revision only when content changes, a new
  rule set for a new tax year, D42) and imports missing profiles and scenarios. It reports profiles that fail validation
  rather than storing them. After a rules change it re-validates every stored profile. `export` writes the stored text,
  so the round trip is byte for byte. `backup` is an export plus an SQLite online-backup copy.
- **Recorded runs** (`persistence/runs.py`): deterministic and Monte Carlo runs from the database are recorded with
  status, summary (JSON), output folder, timings, and pinned revisions. Monte Carlo runs are cached (D43), and failed
  runs are marked `failed`. `load_run_input` rebuilds a run's exact inputs.
- **CLI:** commands read the database unless given `--data-dir`. New options are `--db URL` / `$NORTHWARD_DATABASE_URL`
  and `--runs-dir`.
  - `northward db init|migrate|seed|export|backup|list|show|history|diff|edit|put|revert|clone|delete|restore|purge`.
  - `northward runs list|show|rerun`.
  - `northward db list --profile P` lists every document kind a profile can have (its latest revision, or that an
    optional one doesn't exist yet), with a description, plus its scenarios with their own descriptions.
  - `northward mc --no-cache`, `northward stats <run id>` (goals from the run's pinned revisions), and
    `northward run --from-run N --path P` (drill-down on the run's own inputs).
  - `make db` seeds, `make migration m=...` autogenerates a migration, and `make bench` uses file mode so the cache
    can't answer it.
- **Fix: results depended on the process's string hash seed.** Social Security iterated over a set of member ids, so
  cash postings, and the last bits of some sums, followed `PYTHONHASHSEED`, which differs between processes. Phase 6's
  bit-for-bit checks ran within one process, so they never saw it. Iteration now follows insertion order, and a
  subprocess test runs under three hash seeds.
- **Data hygiene:**
  - The real profile was seeded into `var/northward.db`.
  - Its export matched `data/` byte for byte, and a backup was kept in `var/backups/pre-untrack/`.
  - It was then removed with `git rm`, and `data/profiles/*` (except `example/`) is git-ignored (D44).
  - Git history still holds it.
- **Performance:** unchanged. 10,000 paths take 41.7 s. A validated write takes about 1 s for a profile with four
  scenarios, since every scenario is loaded before and after the change.
- **Tests:** 371, up from 298. They cover:
  - migrations from empty, models in sync with migrations, downgrade and upgrade, constraints
  - seed idempotence, rule revisions, a new tax year with a pinned scenario, deleted and invalid profiles, the
    byte-for-byte round trip, backup
  - every repository write path and rejection, pre-existing problems, soft delete, purge, clone, owner scoping
  - source parity, pinned and overlay sources, name-independent hashes
  - recording, every cache-miss condition, exact reproduction after an edit, failed runs
  - every new CLI command, including `db edit` through a scripted `$EDITOR`

**Phase 7 simplifications:**
- An optional profile document can't be deleted, only replaced (e.g. with `schema_version: 1` alone, which is the
  same as absent).
- Profiles and scenarios can't be renamed yet (Phase 8's PATCH endpoints).
- Rule sets can't be deleted. Old ones stay for scenarios and runs that pin them.
- A run that's killed (rather than failing with an exception) stays `running`. Phase 8's job runner will reconcile
  these.
- Run cache entries aren't shared between scenarios with identical inputs (e.g. a fresh clone), and a larger run isn't
  reused for a smaller request.
- `RunRepo` isn't owner-scoped yet. Runs are reached through their scenario's profile.

### Phase 8 — FastAPI application layer ✅ (done 2026-10-19, branch `phase-8-api`)

Endpoints:

| Endpoint | Purpose |
|---|---|
| `POST /api/validate` | Validate a config document or payload. |
| `GET/POST/PATCH/DELETE /api/profiles[/{id}]` | Manage profiles. |
| `GET/PUT /api/profiles/{id}/documents/{kind}` | Read or save a profile document (YAML text or structured JSON). Saving creates a revision. |
| `GET /api/documents/{id}/revisions[/{rev}]` | Revision history, a single revision, and diffs between revisions. |
| `GET/POST/PATCH/DELETE /api/profiles/{id}/scenarios[/{sid}]` | Manage scenarios, including cloning. |
| `GET /api/rule-sets[/{id}]` | Browse the shared rules (read-only through the API, since files are the master copy per D14). |
| `POST /api/simulate/deterministic` | Synchronous run that returns the table and ledger. |
| `POST /api/simulate/montecarlo` | Starts a background job and returns a `run_id`. |
| `GET /api/runs[/{id}]` | Run history, status, and progress. |
| `GET /api/runs/{id}/results` | Summary stats and bands. |
| `GET /api/runs/{id}/paths/{i}` | Drill-down ledger for one path (re-run with the ledger on). |
| `POST /api/compare` | Compare scenarios on common random numbers. |

Other work:
- Payloads reuse the Phase 1 Pydantic models, so there is a single source of truth.
- Handlers go through the Phase 7 repositories only, never direct SQL.
- Job execution uses an in-process worker pool (enough for single-user local use). Run state and results persist in the `runs` table.
- Include the OpenAPI schema export for frontend type generation.

**Done when:** API tests with `TestClient` and a temporary SQLite DB cover every endpoint, and a Monte Carlo run can be
started, polled, fetched, and found again in run history after a server restart.

**Outcome:**
- **App** (`api/app.py`, `create_app`):
  - Errors map to statuses. Configuration problems are 422 with the same issues `northward validate` prints; unknown
    items are 404; conflicts are 409; bad values are 400.
  - Operation ids are the handlers' names (`list_profiles`, ...), for readable generated clients.
  - The OpenAPI schema also carries every configuration document model, which is how payloads reuse the Phase 1
    models (their `data` is exactly what those models validate).
  - `northward serve` and `northward openapi`, plus `make serve` and `make openapi`.
- **Endpoints** (`api/routes/config.py`, `api/routes/runs.py`): everything in the table above, plus:
  - `GET /api/health`, `GET /api/schemas/{kind}`, and batch `PUT /api/profiles/{p}/documents`
  - revision restore, rename (`PATCH`), restore after delete, and `copy_from` for new profiles
  - `POST /api/runs/{id}/cancel`, and `buckets` and goal overrides on results
  - Deleting is the Phase 7 soft delete, and `?purge=true` purges.
  - Handlers use only the repositories and the run service.
  - Responses replace NaN with null, because JSON has none.
- **Structured edits** (`config/yaml_edit.py`, D46): unchanged data returns the stored text byte for byte, a changed
  value rewrites only its line, and list items keep their comments through reorders and inserts. A type-aware
  comparison keeps `true` → `1` from being dropped as "unchanged" (Python counts `True == 1`).
- **Jobs** (`api/jobs.py`, D47):
  - The run service was split into `find_cached`, `queue_monte_carlo`, `execute_monte_carlo`, `cancel_queued`, and
    `reconcile`, with `RunCancelled` and `RunInterrupted` raised from the progress callback. The CLI still uses
    `monte_carlo()`.
  - Migration `0002` adds `runs.pid`.
  - `run_monte_carlo` takes `mp_context`, and a stopped run cancels its remaining chunks instead of finishing them.
  - Manually checked with a real server: an interrupted 3,000-path run went back to `queued` and completed after a
    restart.
- **Refactors:**
  - `GoalsDoc.with_overrides` (shared by the CLI and the API)
  - `ProfileRepo.check` (dry-run validation), `copy`, and `rename`; `ScenarioRepo.rename`
  - `document_model`, and `runs.remove_outputs`
  - `make migration` now numbers migrations `0003_...`
  - `northward/__main__.py` is guarded, so spawned workers don't rerun the CLI.
- **Tests:** 429, up from 371. They include:
  - every endpoint through `TestClient` on a temporary SQLite database
  - start, poll, fetch, and history after a restart
  - shutdown requeue and resume, abandoned runs marked failed, cancelling queued and running runs
  - shared pending runs, pending-then-complete compares
  - a run through spawned worker processes that matches an in-process run
  - comment-preserving merges, and the OpenAPI schema (paths, models, unique operation ids, resolvable refs)
  - The persistence fixtures moved to `tests/conftest.py`.
- **Dependencies:** fastapi, uvicorn, ruamel.yaml, and httpx2 for the test client (Starlette now prefers it over
  httpx).

**Phase 8 simplifications:**
- No authentication or CORS. Phase 9 can serve the SPA from the same origin or add a dev proxy.
- One job at a time. A queued run waits behind the active one, however small it is.
- Stopping the server waits for the active run's in-flight chunks, which can take several seconds.
- Progress isn't visible for runs started by the CLI or another server process.
- A cancel request waits for the run to stop.
- Compare works on runs of the scenarios' current inputs. Comparing arbitrary stored runs isn't supported.
- Inserted list items can lack the blank line that separates the others.

### Phase 9A — React SPA with a YAML editor (`frontend/`) ✅ (done 2026-10-20, branch `phase-9a-ui`)

Everything in the UI except per-document forms (D49). Documents are edited as YAML, with the schema's help.

- **Project:**
  - Vite + React + TypeScript, with API types generated from `northward openapi` by `openapi-typescript`.
  - TanStack Query for fetching and polling, and Plotly.js for charts.
  - In development, Vite proxies `/api` to `northward serve`. A production build is served by `northward serve` from the
    same origin, so no CORS is needed.
- **Profile management:** create (from another profile, or blank), switch, copy, rename, delete, and restore. The
  overview lists every document a profile can have, with descriptions, and its scenarios.
- **YAML editor** (Monaco + `monaco-yaml`, fed `/api/schemas/{kind}`):
  - Completion, hover documentation, and schema errors as you type.
  - Saving shows the server's cross-document problems on the lines they point at.
  - Saves pass `base_revision`, so an edit made in another tab is never overwritten.
- **Revision history:** a list of revisions, side-by-side diffs, and restore.
- **Balance grid:** the one form in 9A. It updates every account's balance (and cost basis where it applies) in one
  save, e.g. from quarterly statements.
- **Scenarios:** clone, rename, delete, and edit (including `overrides`) in the YAML editor. Run them
  deterministically or with Monte Carlo.
- **Results dashboard:**
  - Probability of success, with live goal overrides (no rerun).
  - Percentile cone of net worth (real/nominal toggle).
  - Stacked balances by wrapper.
  - Annual taxes by type.
  - Income sources by year.
  - Median-path year table and ledger with filters, plus drill-down into any percentile path.
- **Run history:** reopen past results without re-running; progress and cancel for active runs.
- **Comparison view:** overlay two to four scenarios (e.g. SS at 62/67/70 or a conversion strategy), with a delta
  table.

**Done when:** a user can create a profile, edit a lever, run Monte Carlo, and compare two scenarios entirely in the
browser, and all of it is still there after restarting the app. An automated browser test does exactly that.

**Outcome:**
- **Stack** (`frontend/`, exact versions pinned):
  - Vite 8, React 19, TypeScript 5.9 (`openapi-typescript` doesn't support 7 yet), TanStack Query 5, and React
    Router 7.
  - Plotly (`plotly.js-dist-min` behind a small wrapper; `react-plotly.js` predates React 19), Monaco 0.57 with
    `monaco-yaml`, Vitest 4 (5 needs Node 22), and Playwright.
  - `.npmrc` sets `legacy-peer-deps`, since npm 10's peer resolver crashes on this tree. Every peer is listed
    explicitly instead.
  - Node 20.19 or newer is required (`engines`).
- **Serving:** `northward serve` serves `frontend/dist` from the same origin as the API, with a single-page-app
  fallback. Unknown `/api/...` paths still 404 as JSON. `--ui-dir` picks the build. In development, Vite proxies
  `/api`.
- **API types:** `frontend/openapi.json` and the types generated from it are committed. `make api-types` regenerates
  them, and a Python test fails when they're stale. The app's model types use openapi-fetch's `Readable` view of each
  schema, so they match responses exactly.
- **Backend additions:**
  - Path drill-down responses carry the path's per-year telemetry buckets, so the dashboard's wrapper, tax, and
    income charts come from one coherent path.
  - `GET /api/runs/{id}/years` reopens a deterministic run (recomputed from its pinned inputs).
  - `CompareRequest` lost an unused `use_cache`.
- **JSON Schemas fixed for the editor.** Four models convert input before validating, so their schemas were narrower
  than what they accept, and the editor flagged valid documents:
  - claim ages written as `67`
  - `rule_set: 2026`
  - `liabilities:` with no entries
  - rates written as `"5/9%"`

  `also_accepts` and `WithJsonSchema` now describe those inputs. A new test checks every committed document against
  its JSON Schema.
- **Monaco 0.57 workarounds** (in `vite.config.ts`):
  - Editor features such as completion and hovers come only with the package root, not `editor.api`. Its language
    grammars still load lazily.
  - `monaco-yaml`'s worker helper (`monaco-worker-manager`) still uses the old `createWebWorker` options and an
    old import path. Monaco silently fell back to its plain worker, and validation failed with "Missing
    requestHandler: doValidation". `src/components/monacoWorkerManager.ts` replaces it via an alias, and a second
    alias maps the old path. Recheck both when upgrading `monaco-yaml`.
- **Charts** follow the data-viz palette:
  - The reference categorical slots (validated light and dark), in fixed order.
  - Hairline axes, unified crosshair tooltips, and HTML legends in text colors (none for one series).
  - Every chart has a table view, which is also the required relief for three light-mode colors under 3:1 contrast.
  - Series keep their colors when others are hidden.
  - Results refetch in place (dimmed) when the goal overrides change.
- **Tests:**
  - 12 Vitest unit tests: issue-location mapping, formatting, balance parsing, real/nominal conversion, and chart
    table views.
  - Two Playwright tests: the "done when" journey, including the live schema error, a cross-document problem marked
    on its line, Monte Carlo, comparison, and a server restart; and the balance grid, through diff and restore.
  - Python: 458 tests, up from 429.

**Phase 9A simplifications:**
- No in-app navigation guard for unsaved edits, only the browser's leave-page prompt. React Router's blocker needs
  its data router.
- Monaco's diff view switches to inline below about 900px of width.
- Rule documents are viewed without their schema (read-only anyway).
- The ledger table shows at most 500 rows; filters narrow it.
- No ESLint: TypeScript strict mode and Prettier carry the checks.

### Phase 9B — Document forms

Forms beside the YAML view of the same document (a toggle; both save through the same API, so no backend work).
In order of how often they're likely to be used:

1. Scenario levers: retirement and claiming ages, Roth conversions, withdrawal order, mortality.
2. Household and income (salaries and their payroll elections, pensions, other income).
3. Spending categories and events.
4. Accounts beyond the balance grid (account types, asset strategies, 529 details).

Reusable widgets for anchors (a year, a member's or dependent's age, or an event) and for the schema's
discriminated unions. Liabilities, health costs, and goals stay YAML-only unless the forms above prove worth
extending. Inline validation errors come from the API, as in 9A.

**Done when:** the levers, household, income, spending, and events documents can be edited in forms, and every form
round-trips (a form save of unchanged data adds no revision, and YAML comments survive form edits).

### Phase 10 — Multi-user and authentication (deferred)

Not scheduled. It depends on D17 holding through Phases 7–9.

- Add a `users` table. Start using `profiles.owner_user_id`, and scope every repository query by the current user.
- Authentication: local accounts (argon2 password hashes) with session cookies, or OIDC with an external identity provider. Decide when
  the phase starts.
- Authorization: owner-only to start. Sharing a profile read-only or editable with another user is a possible follow-on.
- Rule sets stay global, with an admin role managing them.
- Move from SQLite to Postgres if several users will run jobs at once. Move the job queue out of process (e.g. RQ or Celery) if needed.
- Deployment work: HTTPS, secrets handling, and backups for a hosted DB.

### Backlog (not scheduled)

- Compute PIA from earnings history (AIME, bend points, projected future earnings) (D6).
- Tax-law policy modifiers, such as the commented-out `future_tax_hike` in `base.yaml`, and TCJA/OBBBA sunset scenarios.
- Dynamic spending rules (guardrails, Guyton-Klinger), specific-lot basis, tax-loss harvesting, and Roth 5-year rules.
- Annuities and long-term care, and QCDs from IRAs after age 70½.
- Itemized deductions (SALT, mortgage interest, charitable), and the Wisconsin itemized-deduction and school property tax credits.
- ACA premium tax credit under current law (400% FPL cliff, Rev. Proc. 2025-25 percentages) as an optional switch; it interacts
  with Roth conversions in early-retirement scenarios.
- IRMAA life-changing-event appeals; survivor claiming strategies (delaying the survivor benefit or switching later).
- Financial-aid modeling (the FAFSA Student Aid Index uses income from two years earlier plus assets, so Roth conversions and realized gains
  during those years reduce aid), kiddie tax, UTMA/UGMA custodial accounts, and EITC.
- Import account balances from brokerage CSV/OFX exports into a new account-document revision.
- Mortality improvement (cohort life tables, or a configurable improvement factor) and correlated spousal lifespans.
- Stochastic wage growth and healthcare inflation. A floor on deflation-driven decreases of indexed tax amounts.
- Aggregated per-path warnings in Monte Carlo summaries.

---

### 4.1 Design Note: Spending Model (Q1)

A `spending.yaml` per profile (replacing the `Expense` idea in the first draft of this plan):

```yaml
spending:
  base:
    amount: 90000               # today's dollars per year
    index: general              # general | education | healthcare | none
    retirement_change: 0.0      # optional, e.g. -0.10 from the first full year both members are retired
    phases:                     # optional multipliers on base by reference member's age
      reference: alex
      bands:
        - {until_age: 75, multiplier: 1.00}
        - {until_age: 85, multiplier: 0.85}
        - {multiplier: 0.75}
  categories:                   # added on top of base
    - id: sam_household             # childcare, activities, food, etc.
      amount: 15000
      start: {year: 2026}
      end:   {dependent: sam, age: 17}
    - id: sam_daycare
      amount: 10000
      tags: [dependent_care]        # feeds the Child and Dependent Care Credit / FSA
      end:   {dependent: sam, age: 5}
    - id: sam_college
      amount: 30000
      index: education
      tags: [qualified_education]   # feeds AOTC/LLC and 529 qualified withdrawals
      beneficiary: sam
      start: {dependent: sam, age: 18}
      end:   {dependent: sam, age: 21}    # inclusive
    - id: car_replacement
      amount: 40000
      every_years: 8
      start: {year: 2029}
      end:   {member: alex, age: 85}
    - id: early_retirement_travel
      amount: 12000
      start: {event: retirement, member: alex}
      end:   {member: alex, age: 80}
    - id: roof
      amount: 20000
      once: {year: 2031}
```

- **Timing anchors:** `{year}`, `{member, age}`, `{dependent, age}`, or `{event: retirement | death, member}`.
  An `end` is optional and inclusive. `every_years` repeats from `start`. `once` is a single year.
- **Indexing:** amounts are in today's dollars (the simulation start year). `general` follows simulated CPI.
  `education` and `healthcare` follow CPI plus a configurable spread (defined in the market preset), so they stay
  correlated with inflation in Monte Carlo. `none` keeps a fixed nominal amount.
- **Tags:** `qualified_education` (requires `beneficiary`) and `dependent_care` link spending to tax credits and 529 withdrawals
  (§4.4). An untagged category is plain spending.
- **Validation:** anchors must reference existing members or dependents, `end` must not precede `start`, `every_years ≥ 1`, and
  tagged categories must name a valid beneficiary. `start` is optional and defaults to the simulation start year.
- **Healthcare overlap:** once Phase 5 models healthcare costs, `base` should exclude them. A `base.includes_healthcare: false`
  flag (default) documents this, and the Phase 5 docs call it out.
- **Survivor:** after a death, `base` is scaled by the survivor factor (Phase 5). Categories are unaffected unless they are
  anchored to the deceased member, in which case their `end` still applies.

### 4.2 Design Note: Glide Path (Q2)

`data/rules/glide_paths.yaml`:

```yaml
glide_paths:
  - id: linear_default
    kind: linear
    start_equity: 0.90          # held at or before (target_year - years_before)
    years_before: 40
    target_equity: 0.50         # reached at target_year, then held flat
    post_target: null           # optional: {years_after: 7, final_equity: 0.30}
    non_equity: {bonds: 1.0, cash: 0.0}   # how the non-equity share splits
```

- Equity share in year `y`: `start_equity` until `target_year − years_before`, then a straight line to `target_equity`
  at `target_year`, then flat (or a second straight line to `final_equity` if `post_target` is set).
- Recomputed every year in Stage 7. Balances are rebalanced to the new weights before returns are applied (no drift within a year).
- Accounts may override any field inline (`asset_strategy: {kind: target_date, target_year: 2040, target_equity: 0.40}`).

### 4.3 Design Note: Capital Market Assumptions (Q3)

**Why these numbers matter:** the absolute probability of success depends heavily on the assumed average stock return. The
comparisons this tool is built for (SS at 62 vs 70, Roth conversions, drawdown order) are **less** sensitive, because
each scenario runs on the same sampled paths. They are not insensitive, though. For example, delaying SS looks better
when expected returns are lower, and conversions look better when growth is higher. Rather than trusting one set of numbers,
the tool ships a few named presets and makes it easy to rerun a comparison under another one.

**Asset classes (v1):** `stocks` (US total market), `bonds` (US aggregate / intermediate Treasury), `cash`, and `inflation`
(CPI) as a fourth correlated factor. Adding international stocks, TIPS, and similar classes is backlog.

**Default preset `forward_conservative`** (arithmetic, nominal, annual):

| Factor | Mean | Std dev | Taxable-account income treatment |
|---|---|---|---|
| Stocks | 7.0% | 17% | 1.5% dividend yield, 95% qualified. The rest is unrealized price gain. |
| Bonds | 4.5% | 6% | 4.0% interest (ordinary). The rest is price change. |
| Cash | 3.0% | 1% | All interest (ordinary). |
| Inflation | 2.5% | 1.2% | Bounded to [0%, 8%] (the current `base.yaml` values). |
| Education / healthcare spread | +2.0% / +2.5% over CPI | — | Used by spending indexing (§4.1) and Phase 5. |

Correlations: stocks–bonds 0.10, stocks–cash 0.00, stocks–inflation −0.10, bonds–cash 0.30, bonds–inflation −0.20,
cash–inflation 0.50.

A 7% arithmetic mean with 17% volatility compounds to roughly 5.6% a year (about 3% real). That is below the
historical US average, in line with the more cautious published 10-year outlooks, and a sensible default for planning.

**Other presets:**
- `historical_us`: 1928–2025 US averages computed from `historical_returns.yaml`: stocks 11.85%/19.4%, 10-year Treasuries
  4.82%/7.9%, T-bills 3.42%/3.0%, and inflation 3.11%/3.9% (bounded to its historical range). A test keeps the two consistent.
- `pessimistic`: stocks 5.5%/18%, bonds 3.5%/6%, inflation 3.0%/1.5%.
- `bootstrap` (`kind: bootstrap`): resamples blocks of whole historical years (D38). Its factors and correlations are computed from
  the history.

**Implementation notes:**
- By default, each factor is sampled as a correlated lognormal whose arithmetic mean and std dev match the preset, so a return
  can never fall below −100%. A factor (or a whole preset) can instead use `normal` or `student_t` (fat tails, with
  `degrees_of_freedom`). Those draws are floored at −99%.
- Presets live in rules (shared and versioned, per D14 and D16). A scenario chooses one with `market: {preset: forward_conservative}`
  and may override single values.
- The Phase 9 comparison view gets a "rerun under another preset" action.

### 4.4 Design Note: Dependents (Q11)

`household.yaml`:

```yaml
dependents:
  - id: sam
    name: "..."
    birth_year: 2014
    birth_month: 6
    relationship: child           # child | other_relative
    lives_with_household_until_age: 22
    full_time_student_ages: [18, 21]   # inclusive; extends dependency to under 24, drives AOTC/LLC
    disabled: false               # removes age limits (dependency, SS child benefit)
    child_of: [alex, jordan]      # for SS child benefits (which workers' records apply)
```

**Status for the year.** Each year the engine derives these from the dependent's age at year end. The age tests themselves are
parameters in the rules file.

| Status | Rule | Used by |
|---|---|---|
| `ctc_eligible` | Under 17 | Child Tax Credit |
| `qualifying_child` | Under 19, or under 24 and a full-time student, or disabled, and living with the household | ODC, HoH, QSS, CDCC dependency |
| `care_eligible` | Under 13, or disabled | Child and Dependent Care Credit / FSA |
| `education_credit_years` | The first 4 years of `full_time_student_ages` get AOTC. Later years get LLC. | AOTC / LLC |
| `ss_child_eligible` | Under 18, or 18 and still in high school, or disabled before 22 | SS child and survivor benefits |
| `in_care_under_16` | Under 16, or disabled | SS child-in-care spouse and mother's/father's benefit |
| `aca_household_member` | Is a tax dependent | ACA household size |

**Tax treatment summary** (all amounts and thresholds live in the rules file with indexing flags, and must be verified against IRS
publications when the 2026 rules are filled in):
- CTC per qualifying child under 17, with a refundable portion. Phase-out starts at statutory MAGI thresholds that are not indexed.
- $500 Credit for Other Dependents (nonrefundable) for dependents not eligible for the CTC.
- AOTC (up to $2,500 per student, 40% refundable) or LLC (up to $2,000 per return), with MAGI phase-outs.
- Child and Dependent Care Credit on capped expenses, less any dependent-care FSA exclusion (§4.5).
- HoH or QSS filing status where eligible (Phase 5 survivor logic). Married couples keep MFJ.

**Who claims the dependent:** always the household. Split custody or divorced-parent claiming isn't modeled.

### 4.5 Design Note: 529 Plans and Dependent-Care FSA (Q12)

**529 accounts** (`accounts.yaml`):

```yaml
  - id: sam_529
    owner: jordan                # account owner (a member)
    type: plan_529
    beneficiary: sam             # must be a dependent (or a member, for adult education)
    balance: 25000
    cost_basis: 18000            # contributions to date; drives the earnings share of non-qualified withdrawals
    opened_year: 2017            # drives the 15-year rule for the 529-to-Roth rollover
    asset_strategy: {kind: target_date, target_year: 2032}   # enrollment-year glide path
  # contributions are a scenario/contribution-policy lever, e.g. {account: sam_529, amount: 5000, until: {dependent: sam, age: 17}}
```

- **Growth:** tax-free. It uses the same glide-path machinery, with `target_year` set to the start of college.
- **Withdrawals:** matched each year to the beneficiary's `qualified_education` spending. The engine first leaves enough out-of-pocket
  expense to maximize the AOTC (up to $4,000 per student), then pays the rest from the 529. Non-qualified withdrawals tax the
  earnings share (via `cost_basis`) as ordinary income plus a 10% penalty.
- **Leftover balance:** a scenario option chooses between changing the beneficiary to another dependent, a Roth IRA rollover for the
  beneficiary (lifetime cap and annual IRA limit from rules; the account must be 15+ years old), or a non-qualified withdrawal.
- **Owner death:** the account passes to the surviving spouse (Phase 5), and the beneficiary is unchanged.
- **Tax:** there is no federal deduction for contributions. The state deduction comes from the state rules file (Phase 5). Contributions over the
  annual gift-tax exclusion per beneficiary give a validation warning. The 5-year election isn't modeled.

**Dependent-care FSA** (a payroll election on a salary stream in `income.yaml`):

```yaml
  - id: jordan_salary
    owner: jordan
    type: salary
    amount: 120000
    elections:
      dependent_care_fsa:
        annual: 5000
        until: {dependent: sam, age: 12}   # optional; the engine also stops it once no dependent is care-eligible
```

- **Wages:** the election is excluded from wages for income tax and FICA.
- **Reimbursement:** it is credited to cash against `dependent_care` spending in the same year. The FSA is use-it-or-lose-it, so if the
  election is larger than that spending, the excess is forfeited and a warning is logged.
- **Limits:** the household limit comes from the rules file (it increased for 2026; verify the amount, and the half-limit for MFS). The combined elections of both
  spouses are checked against it.
- **Interaction with the credit:** the Child and Dependent Care Credit uses `min(expenses, credit cap) − FSA amount`, floored at 0.
- **End of the election:** it stops at retirement of the electing member, when no care-eligible dependent remains, or at `until`,
  whichever comes first.

### 4.6 Design Note: Payroll Elections (Q5)

Salary entries in `income.yaml`:

```yaml
  - id: alex_salary
    owner: alex
    type: salary
    amount: 160000
    elections:
      retirement_deferrals:
        - account: alex_401k             # a traditional or Roth 401(k)-type account owned by this member
          max: true                      # or percent: 0.10, or amount: 20000 (today's dollars)
          include_catch_up: true
          roth_catch_up_account: alex_roth_401k    # required for traditional accounts with catch-ups
      employer_match:
        account: alex_401k
        tiers: [{match: 1.0, up_to: 0.06}]         # e.g. [{match: 1.0, up_to: 0.03}, {match: 0.5, up_to: 0.05}]
      hsa: {account: alex_hsa, coverage: self_only, max: true, employer: 500}
```

Validation rules:
- A deferral gives exactly one of `percent`, `amount`, or `max`. Each salary allows only one `max` deferral, and so
  does each member across all salaries, since the limit is per person.
- Every election account must exist, belong to the salary's owner, and accept that kind of contribution.
- A traditional deferral with catch-ups must name a Roth `roth_catch_up_account`.

**HSA coverage:** both default-profile members are modeled as self-only, each contributing the self-only maximum
($4,400 each for 2026, $8,800 combined). If you are actually on a family HDHP, the family limit ($8,750) is shared
between the two HSAs. To model that, set `coverage: family` on both and split it (Phase 4 enforces the shared limit).

---

## 5. Open Questions

Resolve these when the relevant phase starts.

| # | Question | Needed by |
|---|---|---|
| ~~Q1~~ | ~~Spending structure?~~ **Resolved:** base amount plus phased or periodic categories (D19, §4.1). | Phase 2 |
| ~~Q2~~ | ~~Glide path shape?~~ **Resolved:** linear, 90% → 50% over 40 years, then flat (D20, §4.2). | — |
| ~~Q3~~ | ~~Market assumptions?~~ **Resolved:** presets per §4.3, default `forward_conservative` (D21). | — |
| ~~Q4~~ | ~~Social Security inputs?~~ **Resolved:** each member's PIA at full retirement age (`members[].social_security.pia_at_fra`, today's dollars, from the SSA statement), with claiming ages as scenario levers (D6). | — |
| ~~Q5~~ | ~~Contribution elections?~~ **Resolved:** payroll elections on each salary: deferrals as a percent, amount, or `max` (with catch-ups and the Roth catch-up account), employer match tiers, and payroll HSA contributions (§4.6). | Phase 2 |
| ~~Q6~~ | ~~Retiree coverage and ACA subsidies?~~ **Resolved:** employer coverage while anyone works, then unsubsidized individual-market premiums before Medicare (D31). The current-law ACA credit is in the backlog. | — |
| ~~Q7~~ | ~~Which state?~~ **Resolved:** a generic state engine with per-state rules; Wisconsin is the first state implemented in full, and relocations are supported (D32). | — |
| ~~Q8~~ | ~~Definition of "success"?~~ **Resolved:** configurable. The default is never short on spending, and an optional liquidity reserve floor can be added (D35, D36). | — |
| ~~Q9~~ | ~~Where do edited scenarios persist?~~ **Resolved:** in the database as revisioned YAML documents (D13–D15). | — |
| ~~Q10~~ | ~~Soft or hard delete?~~ **Resolved:** soft delete with restore, plus an explicit purge (D39). | — |
| ~~Q11~~ | ~~Model dependents?~~ **Resolved:** yes, for both spending and tax (D22, §4.4). | Phase 2 |
| ~~Q12~~ | ~~Do 529s or a dependent-care FSA exist?~~ **Resolved:** both are modeled (D23, §4.5). | Phase 2 / 4 |
