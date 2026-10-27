# Scenarios

A scenario (`scenarios/<name>.yaml`) is one plan for a profile: the years to simulate, the market assumptions, the
decisions being tested (**levers**), and any what-if changes. A profile has at least one scenario, usually `base`,
and variations of it to compare. Clone a scenario to start a variation
(`northward db clone --profile P base new_name`, or **Clone** in the web UI).

```yaml
schema_version: 1
description: "Alex retires at 58; fill the 22% bracket with Roth conversions until SS; delay SS to 70."

horizon:
  start_year: 2026
  end_age: 95

market:
  preset: forward_conservative
  overrides:
    factors.stocks.mean: 0.065

levers:
  ss_claim_ages:
    alex: 70
    jordan: {years: 67, months: 6}
  withdrawal_order: [taxable, roth, deferred, hsa]
  cash_reserve: {account: joint_savings, amount: 50000}
  roth_conversions:
    kind: fill_bracket
    bracket_rate: 0.22
    start_year: 2036
    end_year: 2047
    respect_phase_outs: true

overrides:
  household:
    members.alex.target_retirement_age: 58
  spending:
    spending.base.amount: 80000
```

| Field | Default | Meaning |
|---|---|---|
| `description` | none | What the scenario tests, shown in listings. |
| `rule_set` | `latest` | The rules to use: `latest`, or a tax year such as `2026`. Pin a year to keep results fixed when a new tax year's rules arrive. |
| `horizon` | required | The years simulated, [below](#horizon). |
| `market` | the default preset | Market assumptions, [below](#market). |
| `macro` | | Economic assumptions outside the market preset, [below](#macro). |
| `levers` | | The decisions being tested, [below](#levers). |
| `events` | none | What-if one-time events, in addition to the profile's own. Same format as [events.yaml](events.md). |
| `overrides` | none | Changes to profile documents for this scenario only, [below](#overrides). |

## horizon

| Field | Default | Meaning |
|---|---|---|
| `start_year` | required | The first simulated year. Account balances are as of its start, and "today's dollars" means its dollars. |
| `end_age` | `95` | Simulate until every member has reached this age. |
| `end_year` | none | Simulate until this year instead. |

With sampled lifespans, the plan extends past `end_age` if someone lives longer.

## market

| Field | Default | Meaning |
|---|---|---|
| `preset` | `forward_conservative` | A [market preset](rules.md#market-presets): `forward_conservative`, `historical_us`, `pessimistic`, or `bootstrap` (historical years). |
| `overrides` | none | Changes to single preset values, as dotted paths: `factors.stocks.mean: 0.065`. Bootstrap presets can't be changed this way. |
| `deterministic_returns` | `geometric` | The constant return per asset class in deterministic runs: `geometric` (the typical compounded outcome implied by the preset) or `arithmetic` (the preset's mean, which overstates it). |

## macro

| Field | Default | Meaning |
|---|---|---|
| `salary_growth` | `{real_growth_rate: 0}` | The annual raise above inflation, as `real_growth_rate`, for salaries that don't set their own in [income.yaml](income.md). |

## levers

### ss_claim_ages

The Social Security claiming age for each member, by id: a whole age (`67`) or `{years: 67, months: 6}`. Ages run
from 62 to 70. A member who isn't listed claims at full retirement age.

```yaml
ss_claim_ages:
  alex: 70
  jordan: {years: 62, months: 1}
```

### mortality

How long members live. The `kind` is one of:

| `kind` | Meaning |
|---|---|
| `none` (default) | Everyone reaches the end of the plan. |
| `fixed` | Ages at death in `death_ages`, by member id: `{kind: fixed, death_ages: {alex: 74.5}}`. Members not listed reach the end of the plan. |
| `sampled` | Monte Carlo draws each member's lifespan from the SSA life table (by `sex` in household.yaml). Compared scenarios get the same lifespans. A deterministic run uses each member's life expectancy. |

What happens at a death is described in [Modeling](../modeling.md#survivors).

### relocations

Moves to another state, in order. Each has `when` (an [anchor](README.md#conventions)) and `state` (a key in
`rules/state_tax.yaml`):

```yaml
relocations:
  - {when: {year: 2045}, state: WI}
```

### withdrawal_order

When spending and taxes need more than the year's cash, accounts are drawn on in this order. List each of `taxable`
(cash, then brokerage), `deferred` (traditional 401(k)s and IRAs), `roth`, and `hsa` once. The default is
`[taxable, deferred, roth, hsa]`.

### early_withdrawals

Before age 59½ (65 for HSAs): `allow_with_penalty` (the default) withdraws and pays the additional tax;
`block` skips those accounts.

### surplus_sweep

Where leftover cash is invested at the end of each year, in order. Each target has an `account` (a brokerage or cash
account) and an optional `up_to_balance` (today's dollars): fill that account up to the balance, then move to the
next target. Without targets, everything goes to the first brokerage account (or, without one, the first cash
account).

```yaml
surplus_sweep:
  - {account: joint_savings, up_to_balance: 30000}
  - {account: joint_brokerage}
```

### cash_reserve

An emergency fund: `{account, amount}` keeps `amount` (today's dollars, grown with inflation) in a cash or brokerage
`account`. Withdrawals leave it alone until every other account in the withdrawal order is used up, and the run's
warnings flag any year it's drawn on. Each year, once spending is covered, it's topped back up: from the year's cash
first, then from the other accounts.

Without a reserve, taxable-first withdrawals can empty cash early in retirement while tax-advantaged accounts keep
growing. To measure liquidity without reserving it, use the [liquidity floor](goals.md#success) instead.

### roth_conversions

Moves money from traditional accounts to Roth accounts, paying the tax now. The `kind` is `none` (the default),
`fixed_amount`, or `fill_bracket`:

| Field | Applies to | Meaning |
|---|---|---|
| `start_year`, `end_year` | both | The years to convert (inclusive). |
| `amount` | `fixed_amount` | Per year, in today's dollars. |
| `bracket_rate` | `fill_bracket` | Convert up to the top of this ordinary income bracket, e.g. `0.22`, after the year's other income. |
| `respect_phase_outs` | `fill_bracket` | Stop short of income levels where a credit or deduction the household currently gets (the child and dependent credits, education credits, the senior deduction) starts to phase out. Default `false`. |
| `pay_tax_from` | both | `taxable` (the default) pays the tax from other accounts; `conversion` withholds it from the conversion, which counts as a withdrawal (penalized before 59½). |
| `pairs` | both | Which accounts convert into which, in order: `[{source: alex_401k, target: alex_roth_ira}]`. Each pair's `source` is a traditional account and its `target` a Roth account of the same owner. Default: each traditional IRA, then other traditional account, into the same owner's Roth IRA (or Roth 401(k)). |

Conversions happen after the year's spending and other withdrawals, so a bracket fill sees all of the year's income.

### inherited_ira

How inherited IRAs are drawn down within their 10-year window. Required annual RMDs always apply.

| `kind` | Meaning |
|---|---|
| `even` (default) | Spread the balance evenly over the years left. |
| `minimum_then_final` | Take only what's required, then the rest in year 10. |
| `fill_bracket` | Withdraw up to the top of the ordinary bracket in `bracket_rate` each year (and empty it by year 10). |

### contributions

Recurring contributions outside payroll: IRAs, 529s, brokerage accounts. Payroll contributions (401(k)s, HSAs) are
[salary elections](income.md#payroll-elections) instead.

| Field | Default | Meaning |
|---|---|---|
| `account` | required | The account contributed to. |
| `amount` | required | Per year, in today's dollars. Limits from the rules apply (IRA limits and phase-outs, for example). |
| `start`, `end` | the whole plan | [Anchors](README.md#conventions) for the first and last year (inclusive). |
| `index` | `general` | `general` grows with inflation; `none` stays at a fixed nominal amount. |

```yaml
contributions:
  - {account: riley_529, amount: 3000, end: {dependent: riley, age: 17}}
```

### plan_529_leftover

What happens to a 529 once its beneficiary's `qualified_education` spending has ended: `keep` (the default),
`change_beneficiary` (to another dependent), `roth_rollover` (to the beneficiary's Roth IRA, within the limits), or
`withdraw` (a non-qualified withdrawal). See [529 accounts](accounts.md#529-accounts).

## overrides

Changes to the profile's documents for this scenario only, so variations don't need copies of the profile. Each key
is a document (`household`, `accounts`, `income`, `liabilities`, `spending`, `events`, `health_costs`, or `goals`),
and its value maps dotted paths within that document to new values. A list item is addressed by its `id`:

```yaml
overrides:
  household:
    members.alex.target_retirement_age: 58
  income:
    income_streams.alex_salary.amount: 150000
  goals:
    success.liquidity_floor: {amount: 100000}
```

The last part of a path may add a key that doesn't exist yet; every earlier part must exist. The profile is
validated after the changes are applied.
