# Rules

Rules are the facts every household shares: tax law, contribution limits, Social Security and RMD rules, Medicare
premiums, and the assumptions used to model markets. They live in [`data/rules/`](../../data/rules/), one file per
topic. Each file cites its primary sources in its `metadata`, and the figures are for tax year 2026.

| File | Contents |
|---|---|
| `federal_tax.yaml` | Brackets and standard deductions for every filing status, capital-gains rates, NIIT, Social Security taxability, FICA, the senior deduction, early-withdrawal penalties, and credits (child, other dependent, education, dependent care). |
| `state_tax.yaml` | State income tax rules by state code. Today: `none` and `WI`. See [State income tax](state-tax.md), which also explains how to add a state. |
| `contribution_limits.yaml` | 401(k), IRA, and HSA limits and catch-ups, Roth IRA phase-outs, the dependent-care FSA limit, the gift-tax exclusion, and the 529-to-Roth rollover cap. |
| `rmd.yaml` | RMD starting ages by birth year, and the Uniform Lifetime and Single Life tables. |
| `social_security.yaml` | Full retirement age by birth year, early-claiming reductions, delayed credits, spousal, survivor, and child benefits, the family maximum, and the earnings test. |
| `healthcare.yaml` | Medicare Part B and D premiums and IRMAA, the ACA age curve, and default healthcare cost assumptions. |
| `account_types.yaml` | How each [account type](accounts.md#account-types) is taxed and what it allows. |
| `glide_paths.yaml` | Target-date glide paths, [below](#glide-paths). |
| `market_assumptions.yaml` | Market presets, [below](#market-presets). |
| `historical_returns.yaml` | Annual US stock, bond, T-bill, and CPI figures for 1928–2025, for the historical presets. |
| `mortality.yaml` | The SSA 2023 period life table, for sampled lifespans. |

**Where rules live.** Unlike profiles, the files in `data/rules/` are the master copy, reviewed in git.
`northward db seed` stores them in the database, adding revisions only for files that changed. Rules are grouped into
**rule sets** named for their tax year (`federal_tax.yaml`'s `metadata.base_year`). A scenario uses the latest rule
set unless it pins one with `rule_set: 2026`, so a new tax year never changes old results.

**Indexing.** Dollar amounts marked `indexed: true` grow with simulated inflation each year. Amounts fixed by statute
(NIIT and Social Security taxability thresholds, the Child Tax Credit phase-out, and others) stay fixed.

## Glide paths

A glide path sets the stock share of a [target-date account](accounts.md#asset-strategies) each year:

```yaml
glide_paths:
  - id: linear_default
    kind: linear
    start_equity: 0.90          # held until `years_before` the target year
    years_before: 40
    target_equity: 0.50         # reached at the target year, then held
    post_target: null           # optional: {years_after: 7, final_equity: 0.30}
    non_equity: {bonds: 1.0, cash: 0.0}   # how the rest splits between bonds and cash
```

The stock share is `start_equity` until `target_year − years_before`. It then falls in a straight line to
`target_equity` at `target_year`, and stays there. With `post_target`, it instead keeps falling in a straight line to
`final_equity` over `years_after` more years. An account can override any of these values for itself.

## Market presets

A preset describes how stocks, bonds, cash, and inflation behave. A scenario chooses one, and can change single
values:

```yaml
market:
  preset: forward_conservative
  overrides:
    factors.stocks.mean: 0.065
```

Absolute success rates depend heavily on the assumed stock return. Comparisons between scenarios depend on it less,
because compared scenarios run on the same simulated markets, but they aren't immune: delaying Social Security looks
better when returns are lower, and Roth conversions look better when growth is higher. Rerunning an important
comparison under a second preset is a good check.

| Preset | Stocks | Bonds | Cash | Inflation |
|---|---|---|---|---|
| `forward_conservative` (default) | 7.0% ± 17% | 4.5% ± 6% | 3.0% ± 1% | 2.5% ± 1.2%, within 0–8% |
| `historical_us` | 11.85% ± 19.4% | 4.82% ± 7.9% | 3.42% ± 3.0% | 3.11% ± 3.9% |
| `pessimistic` | 5.5% ± 18% | 3.5% ± 6% | 2.5% ± 1% | 3.0% ± 1.5%, within 0–10% |
| `bootstrap` | Whole historical years, 1928–2025, resampled in blocks | | | |

Figures are annual arithmetic means ± standard deviations, nominal. `forward_conservative` compounds to roughly 5.6% a
year for stocks (about 3% after inflation), below the historical US average and in line with the more cautious
published 10-year outlooks. `historical_us` is computed from `historical_returns.yaml` (the S&P 500, 10-year
Treasuries, and 3-month T-bills), and a test keeps the two consistent. `bootstrap` resamples real years in blocks of
five, which keeps actual crashes, inflation spells, and the relationships between asset classes intact.

| Field | Meaning |
|---|---|
| `kind` | `parametric` (the default: draws from the distributions below) or `bootstrap` (resamples historical years). |
| `distribution` | The default for each factor: `lognormal` (the default; a return can't fall below −100%), `normal`, or `student_t` (fatter tails). |
| `degrees_of_freedom` | For `student_t` factors. Lower means fatter tails; must be over 2. Default 5. |
| `block_length` | For `bootstrap`: consecutive historical years per block. Default 5. |
| `factors` | For each of `stocks`, `bonds`, `cash`, and `inflation`: `mean`, `std_dev`, and optionally `distribution`, `min_bound`, and `max_bound`. |
| `correlations` | Pairwise correlations, each pair listed once: `{stocks: {bonds: 0.10}}`. Missing pairs are 0. |
| `taxable_income` | How much of a taxable account's return is paid out as income each year: `stocks.dividend_yield` and `qualified_fraction`, and `bonds.interest_yield`. The rest is price change. Cash returns are all interest. |
| `inflation_spreads` | `education` and `healthcare`: extra yearly inflation over CPI for spending indexed to them. |

**Deterministic runs** use one constant return per asset class: by default the geometric mean implied by the preset,
since the arithmetic mean overstates a typical compounded outcome. `market.deterministic_returns: arithmetic`
switches to the arithmetic mean.
