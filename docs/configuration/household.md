# household.yaml

Who is in the household: one or two adult **members**, any **dependents**, the filing status, and the state of
residence. Every other document refers to people by the ids defined here.

```yaml
schema_version: 1

household:
  filing_status: married_filing_jointly
  state: WI

members:
  - id: alex
    name: "Alex Example"
    sex: male
    birth_year: 1978
    birth_month: 9
    target_retirement_age: 62
    social_security: {pia_at_fra: 2850}

  - id: jordan
    name: "Jordan Example"
    birth_year: 1981
    birth_month: 2
    target_retirement_age: 65
    social_security: {pia_at_fra: 2100}

dependents:
  - id: sam
    name: "Sam Example"
    birth_year: 2012
    birth_month: 5
    full_time_student_ages: [18, 21]
    lives_with_household_until_age: 22
```

## household

| Field | Default | Meaning |
|---|---|---|
| `filing_status` | required | `married_filing_jointly`, `married_filing_separately`, `single`, `head_of_household`, or `qualifying_surviving_spouse`. A two-member household must file jointly or separately, and a one-member household can't. |
| `state` | `none` | State of residence: a key in `rules/state_tax.yaml`. Today that's `none` (no state income tax) or `WI`; [State income tax](state-tax.md) explains how to add another. A scenario can move the household later with `levers.relocations`. |

After a death, the survivor's filing status changes automatically (see [Modeling](../modeling.md#survivors)).

## members

`members` lists one or two adults who can own accounts, earn income, and claim Social Security.

| Field | Default | Meaning |
|---|---|---|
| `id` | required | Used everywhere else to refer to this person. |
| `name` | required | Display name. |
| `birth_year`, `birth_month` | required | Drive every age-based rule: catch-up contributions, age 59½, Medicare, RMD age, Social Security. |
| `target_retirement_age` | required | When salary stops (prorated by month in that year). Fractional ages are allowed (`62.5`). A scenario can change it with `overrides`. |
| `social_security.pia_at_fra` | none | Monthly benefit at full retirement age, in today's dollars, from the member's SSA statement ([ssa.gov/myaccount](https://www.ssa.gov/myaccount/)). Leave out `social_security` if the member has no record of their own; spousal and survivor benefits still apply. The claiming age is a scenario lever. |
| `sex` | none | `male` or `female`. Used only to pick the life table when lifespans are sampled; without it, the average of both tables is used. |

## Dependents

`dependents` lists children or other relatives the household supports. Dependents affect both spending (spending categories can be
anchored to a dependent's age) and taxes:

- the Child Tax Credit and Credit for Other Dependents
- the Child and Dependent Care Credit and dependent-care FSA
- education credits (American Opportunity and Lifetime Learning)
- Head of Household and Qualifying Surviving Spouse filing status
- Social Security child benefits
- 529 accounts (as the beneficiary)

| Field | Default | Meaning |
|---|---|---|
| `id`, `name` | required | As for members. Members and dependents share one set of ids. |
| `birth_year`, `birth_month` | required | |
| `relationship` | `child` | `child` or `other_relative`. An other relative is a dependent while living with the household (the income and support tests aren't modeled) and never gets the Child Tax Credit. |
| `lives_with_household_until_age` | none | The last age at which they live with the household. After it they're no longer a dependent. |
| `full_time_student_ages` | none | `[first, last]` ages (inclusive) as a full-time student. Extends dependency to under 24, and decides the education credit: the first four student years get the American Opportunity credit, later years the Lifetime Learning credit. |
| `disabled` | `false` | Removes the age limits on dependency, the care credit, and Social Security child benefits. |
| `child_of` | every member | Members whose Social Security records can pay child benefits. |

**Status each year.** Each year, the engine works out each dependent's status from their age at the end of the
year. The age limits come from `rules/federal_tax.yaml`.

| Status | Rule | Used by |
|---|---|---|
| Dependent | A child under 19, or under 24 and a full-time student, or disabled; and living with the household. An other relative living with the household. | Credit for Other Dependents, Head of Household, Qualifying Surviving Spouse |
| Child Tax Credit | A dependent child under 17 | Child Tax Credit |
| Care-eligible | A dependent under 13, or disabled | Child and Dependent Care Credit, dependent-care FSA |
| Social Security child | A child under 18, or a child marked `disabled`. The high-school extension to 19 and the age-at-disability test aren't modeled. | Child and surviving-child benefits |

The household always claims its dependents. Split custody isn't modeled.
