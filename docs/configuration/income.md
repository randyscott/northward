# income.yaml

Optional. The household's income other than Social Security (which comes from each member's record in
[household.yaml](household.md)) and investment returns. `income_streams` is a list of streams of three kinds, chosen by `type`:
`salary`, `pension`, and `other`.

```yaml
schema_version: 1

income_streams:
  - id: alex_salary
    owner: alex
    type: salary
    amount: 138000
    elections:
      retirement_deferrals:
        - {account: alex_401k, percent: 0.08}
      employer_match:
        account: alex_401k
        tiers: [{match: 1.0, up_to: 0.03}, {match: 0.5, up_to: 0.05}]

  - id: alex_pension
    owner: alex
    type: pension
    annual_amount: 14000
    start: {member: alex, age: 65}
    survivor_fraction: 0.5

  - id: rental_income
    owner: joint
    type: other
    amount: 9000
    end: {year: 2034}
```

## Salary

| Field | Default | Meaning |
|---|---|---|
| `id`, `owner` | required | The owner is a member. |
| `amount` | required | Current annual gross pay. |
| `real_growth_rate` | the scenario's | Annual raise above inflation. Without it, the scenario's `macro.salary_growth.real_growth_rate` applies. |
| `end` | the owner's retirement | An [anchor](README.md#conventions) for when the salary stops. In the retirement year, pay is prorated by the months before the retirement birthday. |
| `elections` | none | Payroll elections, below. |

Wages pay FICA (Social Security and Medicare tax, including the Additional Medicare Tax) per earner.

## Payroll elections

Elections are deducted from pay, so they happen exactly as they would at work, and stop when the salary does.

```yaml
    elections:
      retirement_deferrals:
        - account: jordan_401k           # a traditional or Roth 401(k)-type account of the salary's owner
          max: true                      # or percent: 0.10 (of gross pay), or amount: 20000 (today's dollars)
          include_catch_up: true
          roth_catch_up_account: jordan_roth_401k   # required for a traditional account with catch-ups
      employer_match:
        account: jordan_401k
        tiers: [{match: 0.5, up_to: 0.06}]
      hsa: {account: jordan_hsa, coverage: family, max: true, include_catch_up: true, employer: 750}
      dependent_care_fsa:
        annual: 5000
        until: {dependent: riley, age: 12}
```

**`retirement_deferrals`** is a list, one entry per account.

| Field | Meaning |
|---|---|
| `account` | A 401(k)-type account owned by the salary's owner. Each deferral goes to a different account. |
| `percent`, `amount`, or `max: true` | Exactly one. `max` is the indexed elective-deferral limit, less the member's other deferrals. Only one deferral per member can use `max`, since the limit is per person. |
| `include_catch_up` | Add the catch-up when eligible: from age 50, and the larger catch-up in the years the member turns 60–63. |
| `roth_catch_up_account` | Under SECURE 2.0, catch-ups must go to a Roth account when the member's prior-year wages exceed an indexed threshold ($150,000 in 2026). Required when a traditional deferral includes catch-ups. |

Traditional deferrals reduce taxable wages; Roth deferrals don't. Neither reduces wages for FICA.

**`employer_match`** puts the match in `account`, always pre-tax. Each of the `tiers` matches `match` of each dollar deferred,
on deferrals up to `up_to` of pay. Tiers are cumulative, so `[{match: 1.0, up_to: 0.03}, {match: 0.5, up_to: 0.05}]`
means 100% of the first 3% of pay and 50% of the next 2%. Employee and employer additions together are capped at the
§415(c) limit.

**`hsa`** contributes to an HSA through payroll, which excludes the money from both income tax and FICA.

| Field | Default | Meaning |
|---|---|---|
| `account` | required | The member's HSA. |
| `coverage` | required | `self_only` or `family`. If either spouse has family coverage, one family limit is shared between them. |
| `amount` or `max: true` | required | Exactly one. `max` is the indexed limit for the coverage, less the employer amount. |
| `include_catch_up` | `false` | Add the age-55 catch-up when eligible. |
| `employer` | `0` | The employer's contribution per year, which counts toward the limit. |

HSA contributions stop at Medicare enrollment.

**`dependent_care_fsa`** sets aside `annual` (today's dollars) for dependent care, excluded from income tax and FICA.

- It reimburses spending tagged `dependent_care` ([spending](spending.md#tags)) in the same year. The FSA is
  use-it-or-lose-it: any excess over that spending is forfeited, with a warning.
- The household's combined elections are checked against the limit in the rules.
- The amount reduces the expenses that count toward the Child and Dependent Care Credit.
- It stops at the member's retirement, once no dependent is care-eligible, or at `until`, whichever comes first.

## Pension

| Field | Default | Meaning |
|---|---|---|
| `id`, `owner` | required | The owner is a member. |
| `annual_amount` | required | The annual benefit when it starts, in that year's dollars (not today's). |
| `start` | required | An [anchor](README.md#conventions) for when payments begin. |
| `cola` | `0` | Annual increase once it starts: a fixed rate, or `cpi` to follow simulated inflation. |
| `survivor_fraction` | `0` | The share that continues to a surviving spouse. |

Pensions are taxed as ordinary income.

## Other income

Anything else: rental income, part-time work after retirement, annuity payments, gifts.

| Field | Default | Meaning |
|---|---|---|
| `id`, `owner` | required | The owner is a member, or `joint`. |
| `description` | none | A note for yourself. |
| `amount` | required | Per year, in today's dollars. |
| `start`, `end` | the whole plan | [Anchors](README.md#conventions) for when it starts and ends. |
| `index` | `general` | `general` grows with inflation; `none` stays at a fixed nominal amount. |
| `tax_character` | `ordinary` | `ordinary` (taxed as ordinary income, without FICA) or `tax_free`. |
