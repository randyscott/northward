# accounts.yaml

Every account the household owns: who owns it, what type it is, its current balance, and how it's invested.

```yaml
schema_version: 1

accounts:
  - id: alex_401k
    owner: alex
    type: traditional_401k
    balance: 420000
    asset_strategy: {kind: target_date, target_year: 2040}

  - id: joint_brokerage
    owner: joint
    type: brokerage
    balance: 150000
    cost_basis: 110000
    asset_strategy: {kind: static_allocation, stocks: 0.70, bonds: 0.25, cash: 0.05}

  - id: joint_savings
    owner: joint
    type: savings
    balance: 45000
    interest_rate: 0.035
```

Balances are as of the start of the scenario's first year. The web UI's **Balances** page updates every account's
balance (and cost basis) in one save, for example from quarterly statements.

## Fields every account has

| Field | Meaning |
|---|---|
| `id` | Used by income elections, levers, events, and the results to refer to the account. |
| `owner` | A member id, or `joint`. IRAs, 401(k)s, HSAs, 529s, and inherited IRAs can't be joint. |
| `type` | An account type from `rules/account_types.yaml` (below). |
| `balance` | Current balance in dollars. |

## Account types

The type decides how money going in and out is taxed, whether RMDs apply, and which other fields the account needs.

| `type` | Tax treatment | Other fields |
|---|---|---|
| `traditional_401k`, `traditional_ira` | Tax-deferred: withdrawals are ordinary income; RMDs apply | `asset_strategy` |
| `roth_401k`, `roth_ira` | Roth: withdrawals are tax-free (contribution basis and the 5-year rules aren't tracked); no lifetime RMDs | `asset_strategy` |
| `hsa` | Tax-free for qualified medical costs | `asset_strategy` |
| `brokerage` | Taxable: dividends, interest, and realized gains are taxed each year | `asset_strategy`, `cost_basis` |
| `checking`, `savings` | Taxable interest | `interest_rate` (optional) |
| `inherited_ira_non_spouse` | Inherited traditional IRA: the 10-year rule applies | `asset_strategy`, `inherited_year`, `decedent_started_rmds` |
| `plan_529` | Tax-free for qualified education | `asset_strategy`, `beneficiary`, `cost_basis`, `opened_year` |

Withdrawals from traditional, non-inherited 401(k)s and IRAs before age 59½, and non-medical HSA withdrawals before 65,
pay the additional tax unless `levers.early_withdrawals: block` skips them. Inherited IRAs are exempt; Roth withdrawals
are modeled as tax- and penalty-free at any age, so neither is skipped by `block`. Account types are defined in
`rules/account_types.yaml`; a new type can be added there if it behaves like one of the families above.

| Field | Meaning |
|---|---|
| `cost_basis` | For a brokerage account, the total cost basis of its holdings (average-cost basis is used). For a 529, total contributions to date, which decides the taxable earnings share of a non-qualified withdrawal. |
| `interest_rate` | For checking and savings, a fixed annual rate. Without it, the account earns the market preset's cash return. |
| `inherited_year` | The year the IRA was inherited. The 10-year clock starts from it. |
| `decedent_started_rmds` | Whether the original owner had started RMDs. If so, annual RMDs are required in years 1–9 as well. |

An inherited IRA usually doesn't appear here: an `inheritance` event in `events.yaml` opens one when it happens. List
it here only if it has already been inherited.

## Asset strategies

`asset_strategy` sets how an investment account is split between stocks, bonds, and cash. The account is rebalanced
to that mix every year before returns are applied.

The strategy's `kind` is `static_allocation` or `target_date`.

**Static allocation.** A fixed mix whose weights sum to 1:

```yaml
asset_strategy: {kind: static_allocation, stocks: 0.80, bonds: 0.20}   # cash defaults to 0
```

| Field | Default | Meaning |
|---|---|---|
| `stocks` | required | Share in stocks. |
| `bonds` | required | Share in bonds. |
| `cash` | `0` | Share in cash. |

**Target date.** A mix that becomes more conservative as `target_year` approaches, following a
[glide path](rules.md#glide-paths):

```yaml
asset_strategy: {kind: target_date, target_year: 2040}                       # the default glide path
asset_strategy: {kind: target_date, target_year: 2040, target_equity: 0.60}  # with one value changed
```

| Field | Default | Meaning |
|---|---|---|
| `target_year` | required | Usually the owner's retirement year, or a 529 beneficiary's first college year. |
| `glide_path` | `linear_default` | A glide path id from `rules/glide_paths.yaml`. |
| `start_equity`, `years_before`, `target_equity` | the glide path's | Override one part of the glide path for this account only. |
| `post_target` | the glide path's | Keep reducing the stock share after the target year: `{years_after: 7, final_equity: 0.30}` reaches `final_equity` `years_after` years later. |

## 529 accounts

```yaml
  - id: sam_529
    owner: jordan
    type: plan_529
    beneficiary: sam              # a dependent (or a member, for adult education)
    balance: 62000
    cost_basis: 41000             # contributions to date
    opened_year: 2013             # for the 15-year rule on rollovers to a Roth IRA
    asset_strategy: {kind: target_date, target_year: 2030}
```

- **Growth** is tax-free.
- **Contributions** are a scenario lever (`levers.contributions`), not part of the account. Contributions over the
  annual gift-tax exclusion per beneficiary give a warning.
- **Withdrawals** pay the beneficiary's spending tagged `qualified_education` ([spending](spending.md#tags)). While the
  American Opportunity credit is available, the first $4,000 of expenses each year is left to be paid out of pocket,
  so the household can claim the credit.
- **A non-qualified withdrawal** taxes the earnings share as ordinary income, plus a 10% penalty.
- **Money left over** after the beneficiary's education ends is handled by the scenario's `levers.plan_529_leftover`:
  `keep` (the default), `change_beneficiary` (to another dependent), `roth_rollover` (to the beneficiary's Roth IRA,
  within the lifetime cap and annual IRA limit; the account must be 15 or more years old), or `withdraw`.
- **If the owner dies**, the account passes to the surviving spouse, and the beneficiary stays the same.
- **State tax:** a state deduction for contributions comes from the state's rules (Wisconsin has one).
