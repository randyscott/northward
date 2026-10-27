# spending.yaml

What the household spends. One `base` amount covers ordinary living costs. `categories` add spending on top:
once, every few years, or for a stretch of years (a child at home, college, travel early in retirement).

Taxes, healthcare, and loan payments aren't part of spending. The engine adds them separately from the tax rules,
the healthcare model, and `liabilities.yaml`.

```yaml
schema_version: 1

spending:
  base:
    amount: 84000                # today's dollars per year, excluding healthcare
    retirement_change: -0.05     # 5% less from the first full year everyone is retired
    phases:
      reference: alex
      bands:
        - {until_age: 75, multiplier: 1.00}
        - {until_age: 85, multiplier: 0.85}
        - {multiplier: 0.75}

  categories:
    - id: sam_household
      description: "Food, activities, and other costs for Sam"
      amount: 14000
      end: {dependent: sam, age: 17}

    - id: sam_college
      amount: 32000
      index: education
      tags: [qualified_education]
      beneficiary: sam
      start: {dependent: sam, age: 18}
      end: {dependent: sam, age: 21}

    - id: car_replacement
      amount: 38000
      every_years: 8
      start: {year: 2029}
      end: {member: alex, age: 82}

    - id: retirement_travel
      amount: 12000
      start: {event: retirement, member: alex}
      end: {member: alex, age: 78}

    - id: roof
      amount: 22000
      once: {year: 2031}
```

## base

| Field | Default | Meaning |
|---|---|---|
| `amount` | required | Annual spending in today's dollars. |
| `index` | `general` | How it grows: see [indexing](#indexing). |
| `retirement_change` | `0` | A fractional change from the first full year all members are retired. `-0.10` means spending drops 10%. |
| `phases` | none | Multipliers by a member's age, below. |
| `survivor_multiplier` | `0.75` | After the first death in a two-member household, base spending is multiplied by this. |
| `includes_healthcare` | `false` | Set to `true` only if `amount` already covers healthcare. That turns off the healthcare cost model. |

**Phases** scale base spending as the `reference` member ages, for example to model spending less in your 80s.
Each of the `bands` applies its `multiplier` until `until_age` (inclusive). The last band has no `until_age`, and applies for the rest of the
plan. Ages must increase from band to band.

## categories

Each category is spending on top of base, with its own timing.

| Field | Default | Meaning |
|---|---|---|
| `id` | required | Shown in the results' spending breakdown and ledger. |
| `description` | none | A note for yourself. |
| `amount` | required | Today's dollars per year it occurs. |
| `index` | `general` | How it grows: see [indexing](#indexing). |
| `start` | the plan's start | An [anchor](README.md#conventions) for the first year. |
| `end` | the plan's end | An anchor for the last year (inclusive). |
| `every_years` | every year | Repeat every N years, counting from `start`. |
| `once` | none | An anchor for a single year. Can't be combined with `start`, `end`, or `every_years`. |
| `tags` | none | Links the spending to tax rules, below. |
| `beneficiary` | none | The dependent (or member) the spending is for. Required with `qualified_education`. |

A category anchored to a member who dies keeps its own `end`. The survivor multiplier applies only to base spending.

### Tags

| Tag | Effect |
|---|---|
| `qualified_education` | Counts toward the beneficiary's education credits, and is paid from the beneficiary's 529 accounts first ([529 accounts](accounts.md#529-accounts)). |
| `dependent_care` | Counts toward the Child and Dependent Care Credit, and is reimbursed by a dependent-care FSA ([payroll elections](income.md#payroll-elections)). |

Untagged categories are ordinary spending.

## Indexing

Amounts are in today's dollars and grow each year by:

| `index` | Growth |
|---|---|
| `general` | Simulated CPI. |
| `education` | CPI plus the market preset's education spread (2% by default). |
| `healthcare` | CPI plus the market preset's healthcare spread (2.5% by default). |
| `none` | Nothing: a fixed nominal amount. |

The spreads are added to the simulated CPI, so education and healthcare costs still move with inflation in Monte
Carlo runs.
