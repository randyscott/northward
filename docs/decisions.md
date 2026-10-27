# Design decisions

The decisions that shape Northward, with the reasons for them. Each has a permanent number (D1–D50). Code comments
cite these numbers, so a decision that changes is edited in place (or marked superseded) rather than renumbered.
New decisions take the next number.

Decisions are grouped by topic below, so the numbers aren't in order.

- [Scope and architecture](#scope-and-architecture)
- [Simulation conventions](#simulation-conventions)
- [What is modeled, and how](#what-is-modeled-and-how)
- [Monte Carlo](#monte-carlo)
- [Data and persistence](#data-and-persistence)
- [API and UI](#api-and-ui)

## Scope and architecture

### D1. Configuration validation

**Pydantic v2** models validate every configuration document. Behavior that depends on an account's type comes from
typed, discriminated models in code, not from schemas declared in YAML. _(2026-09-29)_

### D2. Monte Carlo execution

**One readable, scalar engine runs each path, and a process pool runs many paths at once.** NumPy pre-samples every
return and inflation path as `(paths × years × factors)` arrays. The transaction ledger is off for Monte Carlo runs
and on for deterministic runs and single-path drill-downs. _(2026-09-29)_

### D3. Frontend

**A FastAPI backend plus a React + Vite + TypeScript single-page app** in `frontend/`, with Plotly.js charts. The
frontend's API types are generated from FastAPI's OpenAPI schema. _(2026-09-29)_

### D4. Scope

**In scope:** state income tax, mortality and survivor transitions, healthcare costs (ACA, Medicare, IRMAA, HSA),
and payroll tax plus contribution limits. _(2026-09-29)_

### D17. Users

**Single user for now.** Multi-user support with login is on the [roadmap](roadmap.md). To keep that change additive,
profiles carry a nullable `owner_user_id`, and all profile-scoped data access goes through a repository layer that can
be scoped per user later. _(2026-09-29)_

## Simulation conventions

### D7. Time step

**Annual**, by calendar year. `birth_month` is used for the age 59½ threshold, partial-year Social Security in the
claim year, and full-retirement-age month arithmetic. _(2026-09-29)_

### D8. Dollar basis

**Nominal internally.** Values in today's dollars, for reporting, come from dividing by the cumulative simulated CPI.
_(2026-09-29)_

### D9. Tax indexing

Brackets and deductions are indexed by the **simulated** inflation path. Fixed statutory thresholds (NIIT, Social
Security provisional income) stay unindexed. _(2026-09-29)_

### D10. Cost basis

**Average cost** for taxable accounts. Tracking specific lots and tax-loss harvesting aren't modeled. _(2026-09-29)_

### D11. Tax circularity

Taxes are settled by a **gross-up solver**, because withdrawing money to pay tax creates more tax. The solver
withdraws, recomputes the tax, and repeats until the change is under $1, with a limit on the number of rounds.
_(2026-09-29)_

### D12. Randomness

Every stochastic run takes an explicit **seed**, so any result can be reproduced exactly. _(2026-09-29)_

### D25. Deterministic returns

A deterministic run uses one constant return per asset class. By default that's the **geometric mean** implied by
the market preset (7% mean and 17% volatility for stocks gives about 5.7%), since the arithmetic mean overstates a
typical compounded outcome. `market.deterministic_returns: arithmetic` switches it. With zero volatility the two are
equal, so a zero-variance Monte Carlo run still matches the deterministic run. _(2026-09-29)_

### D26. Timing within a year

In the retirement year, salary and payroll contributions (including `max` limits) are prorated by the months before
the retirement birthday. Market returns apply to year-end balances, so the year's flows effectively happen at the
start of the year. Taxable-account income is credited on start-of-year balances. _(2026-09-29)_

### D27. Cash handling

Each year's cash clears to zero.

- A **deficit** is covered by the withdrawal order. Within `taxable`, cash accounts are used before brokerage
  holdings are sold.
- A **surplus** goes to the `levers.surplus_sweep` targets in order. A target can stop at `up_to_balance` (a
  reserve). The default target is the first brokerage account.
- Before age 59½ (65 for HSAs), withdrawals pay the additional tax unless `levers.early_withdrawals: block` is set.

_(2026-09-29)_

### D28. Discretionary tax moves

Roth conversions and bracket-filling inherited-IRA withdrawals run **after** the year's spending and deficit
withdrawals, so a fill-to-bracket amount sees all of the year's other income.

The amount is solved numerically against the full tax calculation, because extra income also changes how much Social
Security is taxable and the senior deduction. `respect_phase_outs` also caps MAGI below the next phase-out of a benefit
the household currently gets (the Child Tax Credit and Credit for Other Dependents, education credits, and the senior
deduction). _(2026-09-30)_

### D34. Social Security timing

Benefits are computed **month by month** within each year. That way, claim months, deaths, survivors reaching 60,
and children aging out each land in the right month. _(2026-09-30)_

## What is modeled, and how

### D5. State tax

A **generic state engine** covers flat and bracketed taxes, with exemption flags for Social Security, pensions, and
retirement income. Each state's rules live in a rules file. _(2026-09-29)_

### D6. Social Security input

The input is each member's **Primary Insurance Amount (PIA) at full retirement age**, from their SSA statement. The
engine applies claiming reductions and credits, spousal and survivor benefits, and cost-of-living adjustments.
Computing the PIA from earnings history isn't supported yet. _(2026-09-29)_

### D19. Spending model

**One base annual amount** does most of the work. **Categories** are added on top. Each category happens once,
repeats every N years, or is active for a window. Each is anchored to a calendar year, a member's or dependent's age,
or a life event. See [spending.yaml](configuration/spending.md). _(2026-09-29)_

### D20. Glide path

The equity glide path is **linear** down to the target year, then flat. The default runs from 90% equity 40 or more
years out to 50% at the target year. An optional segment that keeps declining after the target is available but off
by default. See [glide paths](configuration/rules.md#glide-paths). _(2026-09-29)_

### D21. Market assumptions

**Named presets live in a rules file.** Each scenario selects one and can override single values. The default preset
is moderately conservative and forward-looking. Means are arithmetic and nominal, and returns are sampled as
correlated lognormals by default. See [market presets](configuration/rules.md#market-presets). _(2026-09-29)_

### D22. Dependents

Dependents are **first-class members of the household**. They drive spending (through age-anchored categories) **and
tax**:

- credits
- filing status (Head of Household, Qualifying Surviving Spouse)
- 529 accounts
- Social Security child benefits
- ACA household size

See [household.yaml](configuration/household.md#dependents). _(2026-09-29)_

### D23. 529 plans and dependent-care FSAs

**Both are modeled.** 529 plans are accounts in `accounts.yaml`. The dependent-care FSA is a payroll election on a
salary, not an account. See [529 accounts](configuration/accounts.md#529-accounts) and
[payroll elections](configuration/income.md#payroll-elections). _(2026-09-29)_

### D24. Payroll contributions

**401(k) deferrals, the employer match, and payroll HSA contributions are elections on a salary.** They are part of
the simulation from the start, because the years of saving are wrong without them.

- Deferrals can be a percent, a dollar amount, or `max` (the indexed limit, optionally including catch-ups).
- A traditional deferral with catch-ups names a `roth_catch_up_account`, for the SECURE 2.0 rule that some catch-ups
  must be Roth.

See [payroll elections](configuration/income.md#payroll-elections). _(2026-09-29)_

### D29. Scheduled events

Expected one-time events (a windfall, home sale, or inheritance) go in an optional profile document, `events.yaml`.
Scenarios can add what-if `events` of their own. Inheriting an IRA opens a new inherited account. _(2026-09-30)_

### D30. 529 money

Qualified withdrawals pay the beneficiary's `qualified_education` spending. They leave $4,000 a year to be paid out of
pocket while the American Opportunity Tax Credit is available, so the household can claim it.

What happens to money left after the beneficiary's education ends is set by `levers.plan_529_leftover`:

- `keep` (the default)
- `change_beneficiary`
- `roth_rollover`
- `withdraw`

_(2026-09-30)_

### D31. Healthcare

Costs come from `rules/healthcare.yaml`: Medicare premiums, IRMAA, the ACA age curve, and default household
assumptions. A profile's optional `health_costs.yaml` overrides the assumptions.

- **While anyone works:** employer coverage, paid pre-tax.
- **Before 65 otherwise:** **unsubsidized** individual-market premiums.
- **From 65:** Medicare Parts B and D, IRMAA based on MAGI from two years earlier, and a supplement.

Out-of-pocket costs are added. HSAs reimburse qualified costs (by default, once the owner retires). Setting
`spending.base.includes_healthcare: true` turns the healthcare model off. _(2026-09-30)_

### D32. State tax and residence

`rules/state_tax.yaml` holds rules for each state code. `household.state` picks one, and `levers.relocations` moves
the household in later years. The state engine starts from federal AGI. Wisconsin is the first state implemented in
full. _(2026-09-30)_

### D33. Mortality in deterministic runs

Deterministic runs use `levers.mortality: {kind: fixed, death_ages}`. The default is none, so everyone reaches the
end of the plan. The simulation ends after the last death. For Monte Carlo, see [D37](#d37-mortality-in-monte-carlo).
_(2026-09-30)_

### D50. Cash reserve (emergency fund)

`levers.cash_reserve: {account, amount}` keeps `amount` (today's dollars, indexed) in a cash or brokerage account.

- **Withdrawals leave it alone** until every other account in the withdrawal order is used up. Drawing on it is the
  last resort, and the run's warnings flag it.
- **Each year, once spending is covered, it's topped back up** to its indexed level: from the year's cash first, then
  from the other accounts. That way, interest that lags inflation doesn't erode it.
- Year rows report `reserve_drawn` and `reserve_topped_up`.

The liquidity floor ([D35](#d35-success-criteria)) still measures cash plus brokerage. On the example profile's
early-retirement scenario, a $50,000 reserve takes success from 15% to 99%, at a cost of about 2% of median legacy.
_(2026-10-22)_

## Monte Carlo

### D35. Success criteria

**Configurable.** By default a path succeeds when it is **never short on spending**: no year has unfunded spending or
taxes beyond a $1 rounding tolerance.

The other criterion is an optional **liquidity floor**: year-end liquid assets (cash plus taxable accounts) never fall
below an amount in today's dollars. Every enabled criterion must hold.

Criteria are applied to the stored results after the run, so changing them doesn't need a rerun. _(2026-10-05)_

### D36. Where goals live

An optional profile document, **`goals.yaml`**, holds the success criteria and the heirs' tax rate used to value an
after-tax legacy. Every scenario of a profile uses it, so comparisons share one yardstick. A scenario can still change
it through `overrides`, and the CLI and API can override it when computing statistics. _(2026-10-05)_

### D37. Mortality in Monte Carlo

**Planning age by default.** A Monte Carlo run keeps the scenario's mortality lever, and the default (`none`) means
everyone reaches the end of the plan.

`mortality: {kind: sampled}` draws each member's age at death from the SSA life table for each path. Compared scenarios
get the same draws. Sampled lives may run past `end_age`, in which case the plan extends to the last death.
_(2026-10-05)_

### D38. Historical bootstrap

`rules/historical_returns.yaml` holds annual stocks, bonds, T-bill, and CPI figures for 1928–2025 (from Damodaran's
dataset and BLS CPI-U, with sources). The bootstrap sampler resamples contiguous blocks of years (the block length is
configurable; the default is 5). The `historical_us` preset is computed from the same data. _(2026-10-05)_

## Data and persistence

### D13. Data storage

**Documents are stored in a database.** Each YAML document is stored as text in a row, with typed metadata columns
(profile, scenario, kind, schema version). Pydantic is the only schema: documents are validated on write and parsed on
read. The stack is SQLAlchemy 2.0 and Alembic, on **SQLite**. Moving to Postgres or MySQL should need only a new
connection URL. _(2026-09-29)_

### D14. Where each kind of data is mastered

- **Rules:** the files in `data/rules/` are the master copy, reviewed in git. A re-runnable seed upserts them into the
  database, and all profiles share them.
- **Profiles and scenarios:** imported from `data/` once, after which the database is the master copy.
  `northward db export` writes everything back out as YAML for backups and diffs.

_(2026-09-29)_

### D15. Revisions

Editing a document **appends a new revision** instead of overwriting it. Runs record the exact revisions they used.
That gives undo, change diffs, and exact reruns. _(2026-09-29)_

### D16. Rule versioning

Rule sets are versioned by tax year (named as in [D42](#d42-rule-set-names)). A scenario pins a rule set
(`rule_set: 2026`) or uses `latest`, so a new tax year never silently changes old results. _(2026-09-29)_

### D18. YAML round-tripping

**`ruamel.yaml`** is used wherever YAML is edited and written back, so comments and key order survive. PyYAML is used
where documents are only read. _(2026-09-29)_

### D39. Deleting profiles and scenarios

**Soft delete, plus purge.** Deleting sets `archived_at`. The item is hidden from listings, sources, and seeding
until `northward db restore` brings it back. `northward db purge` permanently removes an already-deleted item, with its
revisions and runs. Names stay reserved until purged. _(2026-10-16)_

### D40. Editing from the command line

`northward db edit` opens `$VISUAL` or `$EDITOR` and re-opens the editor when validation fails. `put` saves files.
`show`, `history`, `diff`, `revert`, and `clone` round out the set. Documents are addressed as in the `data/` layout
(`accounts`, `scenarios/base`). _(2026-10-16)_

### D41. Validating writes

A write is a set of documents validated together. Each document is checked against its model; then the profile, and
every scenario of it, are loaded as they would be after the change.

- Problems the change **introduces** reject it.
- Problems that already existed (for example, after new rules were seeded) don't block unrelated edits.
- Unchanged documents add no revision.

_(2026-10-16)_

### D42. Rule set names

A rule set is named for its tax year: `federal_tax.yaml`'s `metadata.base_year` (for example, `2026`). `latest` is
the highest year. A file source answers to `latest` and to its own year, and a scenario may write `rule_set: 2026`
without quotes. _(2026-10-16)_

### D43. Run cache key

Completed Monte Carlo runs are cached by **(scenario, input hash, engine version, seed, paths)**, as long as their
results still exist on disk.

- The input hash covers the documents' text, but not the profile, scenario, or rule-set names.
- The engine version is the package version plus a hash of the simulation source (everything but the CLI, API, and
  persistence code). Any engine change therefore invalidates the cache without a manual version bump.

_(2026-10-16)_

### D44. Real profiles stay out of git

`data/profiles/*` is git-ignored except `example/`. Real profiles live only in the database (and its exports and
backups). _(2026-10-16)_

## API and UI

### D45. API addressing and access

Profiles and scenarios are addressed by **name** in URLs (`/api/profiles/default/scenarios/base`). Documents are
addressed by their `data/` layout address (`documents/accounts`, `documents/scenarios/base`), as in the CLI.
Revisions are addressed by document id.

The server has **no authentication** and listens on localhost by default ([D17](#d17-users)). `northward serve
--host` prints a warning. _(2026-10-19)_

### D46. Structured edits

A document can be saved as `yaml_text` or as `data`. `data` is merged into the current text with ruamel.yaml
([D18](#d18-yaml-round-tripping)): unchanged values keep their spelling, comments, and order, and list items are
matched by `id`. An optional `base_revision` gives optimistic concurrency: the save fails with 409 if the document
has changed since. _(2026-10-19)_

### D47. Background jobs

Monte Carlo jobs run **one at a time** in a worker thread, and each uses the full process pool. The pool's workers
are **spawned**, because forking a threaded server can deadlock.

- The `runs` table holds each run's state (queued, running, complete, or failed) and the running process's `pid`.
- At startup, runs whose process is gone are marked failed, and queued runs resume.
- Stopping the server puts the active run back in the queue.
- Identical requests share one run. Progress is kept in memory.

_(2026-10-19)_

### D48. Compare over HTTP

`POST /api/compare` can be repeated safely. It submits (or finds) one run per scenario, all with the same seed and
size. It returns 202 with their ids while any is unfinished, and 200 with the comparison once all are complete.
_(2026-10-19)_

### D49. UI in two steps

The UI was built in two steps. The first has the whole app, with a schema-aware YAML editor, and its only form is the
**balance grid**. The second adds per-document forms ([roadmap](roadmap.md)). The API already accepts both YAML text
and structured data, so the forms need no backend changes. Using the YAML editor first shows which forms are worth
building. _(2026-10-20)_
