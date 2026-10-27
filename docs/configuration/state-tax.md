# State income tax

State income tax rules live in [`data/rules/state_tax.yaml`](../../data/rules/state_tax.yaml), keyed by state code.
A household's `state` in [household.yaml](household.md) picks one, and a scenario's
[`relocations`](scenarios.md#relocations) lever can move the household later. Today the file has `none` (no state
income tax) and `WI` (Wisconsin, modeled in full).

One generic engine ([`tax/state.py`](../../backend/northward/tax/state.py)) computes every state from the federal
return, so most states can be added by writing rules alone, with no code. This page describes those rules and how
to contribute a new state. [Adding a state](#adding-a-state) has the steps.

## How a state return is computed

Each simulated year, after the federal return:

1. **Start from federal AGI.**
2. **Subtract** what the state exempts, in this order:
   - the federally taxable part of Social Security (`exempt_social_security`)
   - a share of net long-term capital gains (`capital_gains_exclusion`); or, for a net loss, add back any loss over
     the state's limit (`capital_loss_limit`)
   - after-tax health insurance premiums (`subtract_health_premiums`)
   - retirement income exclusions (`retirement_income_exclusions`), each in turn
   - 529 contributions (`plan_529_deduction`)

   The result, floored at zero, is **state income**.
3. **Deductions:** subtract the standard deduction (fixed, or sliding with state income), then personal exemptions.
   The result, floored at zero, is **taxable income**.
4. **Tax:** a flat rate or brackets for the filing status.
5. **Credits** (the married-couple and dependent care credits) reduce the tax, but not below zero: they're
   nonrefundable.
6. **Add** the state's share of the federal early-withdrawal and HSA additional taxes (`additional_tax_share`).

The state tax is part of the year's tax bill, so withdrawals made to pay it are taxed too, and it's included in the
marginal rate that bracket-filling Roth conversions see.

## The file

```yaml
schema_version: 1
base_year: 2026

states:
  none:
    name: "No state income tax"
    tax: {kind: none}

  XX:
    name: "Example State"
    sources:
      - "XX Department of Revenue, 2026 Form 1 instructions: https://... (checked 2026-10-01)"
    tax:
      kind: flat
      rate: 0.045
      standard_deduction:
        single: 5000
        married_filing_jointly: 10000
        married_filing_separately: 5000
        head_of_household: 7500
      personal_exemptions: {per_person: 1000, per_dependent: 1000}
```

| Field | Meaning |
|---|---|
| `base_year` | The tax year the amounts are for. Indexed amounts grow with simulated inflation from this year. |
| `states` | Rules by state code. `none` is required. Use the state's two-letter postal code. |

Each state has:

| Field | Default | Meaning |
|---|---|---|
| `name` | required | The state's name. |
| `sources` | none | Where each figure comes from: forms, instructions, and statutes, with links and the date you checked them. Every figure should be traceable to one. |
| `community_property` | `false` | Set for community (or marital) property states: at the first death, both halves of jointly owned taxable accounts get a stepped-up basis, not just the deceased's half. This affects federal tax too. |
| `tax` | required | The income tax. Its `kind` is `none`, `flat` (with a `rate`), or `progressive` (with `brackets`). |

## Rates

**`flat`:** `rate` applies to all taxable income.

**`progressive`:** `brackets` gives, for each filing status, `[[upper bound of taxable income, rate], ...]`, ending
with `[.inf, top rate]`:

```yaml
brackets:
  single:                    [[15110, 0.035], [51950, 0.044], [332720, 0.053], [.inf, 0.0765]]
  married_filing_jointly:    [[20150, 0.035], [69260, 0.044], [443630, 0.053], [.inf, 0.0765]]
  married_filing_separately: [[10080, 0.035], [34630, 0.044], [221820, 0.053], [.inf, 0.0765]]
  head_of_household:         [[15110, 0.035], [51950, 0.044], [332720, 0.053], [.inf, 0.0765]]
```

**Filing statuses.** Every value that varies by filing status lists `married_filing_jointly`, `single`,
`married_filing_separately`, and `head_of_household`. `qualifying_surviving_spouse` is optional and defaults to the
joint value. If the state has no such status, give the value its filers actually use. If it has no head of household
status, repeat the single values.

**`indexed`** (default `true`): brackets and the standard deduction (fixed or sliding) grow with simulated inflation
from `base_year`. Set it to `false` if the state doesn't index them. Exemptions and the 529 cap have their own
`indexed` flags; other amounts aren't indexed.

## Subtractions

| Field | Default | Meaning |
|---|---|---|
| `exempt_social_security` | `true` | Subtract the federally taxable part of Social Security benefits. Set it to `false` for a state that taxes benefits as the federal return does. |
| `capital_gains_exclusion` | `0` | Share of net long-term capital gains excluded, e.g. `0.30`. |
| `capital_loss_limit` | the federal limit | Net capital losses deductible per year, for a state whose limit is lower than the federal $3,000. |
| `subtract_health_premiums` | `false` | Subtract health insurance premiums paid with after-tax money: individual-market premiums, Medicare Parts B and D (with IRMAA), and Medigap. Employer premiums are already pre-tax. |
| `retirement_income_exclusions` | none | Subtractions of retirement income, [below](#retirement-income-exclusions). |
| `plan_529_deduction` | none | A subtraction for 529 contributions, [below](#529-deduction). |

### Retirement income exclusions

A list of exclusions, applied in order, each to the retirement income the earlier ones left. Retirement income means
pensions and distributions from traditional accounts (including RMDs, inherited IRAs, and Roth conversions), counted
per member.

| Field | Default | Meaning |
|---|---|---|
| `amount` | required | The most excluded per qualifying person. Not indexed. |
| `min_age` | required | A member qualifies from this age (at the end of the year). Use `0` for an exclusion without an age requirement. |
| `agi_limit` | none | By filing status: only households with federal AGI below this qualify. A status set to `null` has no limit. |
| `pooled_for_joint` | `false` | On a joint return where both spouses qualify, they share one cap of twice `amount`, whichever spouse received the income. |
| `bars_credits` | `false` | Claiming the exclusion forfeits the state's credits that year. The engine computes the return both ways and keeps the lower tax. |

Wisconsin, for example, has a $24,000 subtraction at 67 (pooled for couples, and it forfeits credits) followed by an
older $5,000 subtraction at 65 below an income limit:

```yaml
retirement_income_exclusions:
  - {amount: 24000, min_age: 67, pooled_for_joint: true, bars_credits: true}
  - amount: 5000
    min_age: 65
    agi_limit: {single: 15000, head_of_household: 15000, married_filing_jointly: 30000,
                married_filing_separately: 30000, qualifying_surviving_spouse: 15000}
```

### 529 deduction

Subtracts contributions to 529 plans (from the scenario's `contributions` lever).

| Field | Default | Meaning |
|---|---|---|
| `cap` | required | The most deducted per year. |
| `per` | `beneficiary` | Only per-beneficiary caps are currently implemented. `return` parses but is not honored by the state engine; a return-wide cap needs an engine change. |
| `married_filing_separately_cap` | `cap` | A different cap for married filing separately. |
| `indexed` | `false` | Whether the cap grows with inflation. |
| `rounding` | `10` | An indexed cap is rounded to a multiple of this. |
| `carryforward` | `false` | Contributions over the cap can be deducted in later years. |

## Deductions and exemptions

Give a `standard_deduction` or a `sliding_standard_deduction`, or neither (no standard deduction).

**`standard_deduction`:** a fixed amount by filing status.

**`sliding_standard_deduction`:** a deduction that shrinks as state income rises.

| Field | Meaning |
|---|---|
| `maximum` | By filing status: the deduction at low incomes. |
| `phase_out_start` | By filing status: state income where the reduction begins. |
| `phase_out_rate` | By filing status: the reduction per dollar of state income above the start. The deduction stops at zero. |
| `head_of_household_floor` | Optional. `single`: head of household never gets less than the single schedule. |

**`personal_exemptions`:** amounts subtracted after the standard deduction.

| Field | Default | Meaning |
|---|---|---|
| `per_person` | required | Per member alive during the year. |
| `per_dependent` | `0` | Per dependent claimed that year. |
| `additional_age_65` | `0` | Extra per member 65 or older. |
| `indexed` | `false` | Whether the exemptions grow with inflation. |

For a flat-rate state, a fixed nonrefundable per-person credit can be represented as an exemption worth the
credit divided by the flat rate. This is not equivalent for progressive brackets, where an exemption saves tax at
the marginal rate; those per-person credits need engine support. Note any approximation in `sources`.

## Credits

Two credits are built in. Both are nonrefundable.

**`married_couple_credit`:** for joint returns with two members, `rate` × the lower earner's wages, up to
`earned_income_cap` of wages.

**`dependent_care_credit`:** a state child and dependent care credit computed like the federal one, from spending
tagged `dependent_care`. Not available to married filing separately.

| Field | Meaning |
|---|---|
| `expense_cap_one`, `expense_cap_two_or_more` | Expenses counted with one, or two or more, care-eligible dependents. The household's dependent-care FSA reduces the cap. Expenses are also limited to the lower earner's wages. |
| `max_rate` | The credit rate at low incomes. |
| `agi_threshold` | Federal AGI where the rate starts falling. |
| `step` | The rate falls one point per `step` dollars (or fraction) of AGI over the threshold. |
| `floor_rate` | The lowest rate. |

**`additional_tax_share`** (default `0`): the state's tax on early retirement-plan and HSA withdrawals, as a share of
the federal additional tax, e.g. `0.33`.

## What the engine can't express yet

Some state rules need code as well as rules. If your state has one of these, open an issue first (or include the
code change in your pull request, with tests):

- A calculation that doesn't start from federal AGI, such as one that starts from federal taxable income or taxes
  classes of income separately.
- Partial taxation of Social Security (an income threshold, or a share of benefits). The flag is all or nothing.
- Retirement exclusions for income other than pensions and traditional-account distributions, or exclusions that
  aren't per person.
- Itemized deductions, which the federal model doesn't have either ([#9](https://github.com/randyscott/northward/issues/9)).
- Credits other than the two above, refundable credits, and credits that phase out (other than the care credit's
  rate table).
- Additions to income, such as other states' municipal bond interest; and subtractions such as US Treasury interest.
- Local income taxes, part-year residency (a relocation moves the whole year to the new state), and income earned in
  another state.

A close approximation with the existing fields is often good enough for planning. Say so in a comment in the rules
and in your pull request.

## Adding a state

1. **Check the fit.** Read the state's resident income tax form and instructions for the rules' `base_year`, and
   compare them with this page and [the gaps above](#what-the-engine-cant-express-yet).
2. **Write the rules** in `data/rules/state_tax.yaml` under the state's code. Comment each block with what it is (the
   form line or schedule), and list every source in `sources`. Use primary sources: the revenue department's forms,
   instructions, and publications, and the statutes. Note any assumption (for example, which filing status the
   state's qualifying surviving spouses use).
3. **Validate:** `.venv/bin/northward --data-dir data validate` checks the file against the schema.
4. **Write tests.** Add `tests/tax/test_<state>.py` with hand-checked returns, following
   [`tests/tax/test_wisconsin.py`](../../tests/tax/test_wisconsin.py): build `TaxInputs` for a household, compute the
   return, and compare it with figures worked out by hand from the state's forms, worksheets, or tax tables, not
   with the engine's own output. Cover at least:
   - a working couple filing jointly (brackets, the standard deduction, exemptions, any married-couple credit)
   - a retired couple with Social Security, a pension, IRA withdrawals, and capital gains (the subtractions and
     retirement exclusions)
   - a single filer, and a head of household with a dependent
   - every other feature you used, including an income-limit edge (just below and just above `agi_limit`) and a
     case where `bars_credits` makes the exclusion not worth claiming

   Run `make test` and `make lint`.
5. **Try it on a household.** After `northward db seed`, set a scenario's
   `overrides: {household: {household.state: XX}}` (or add a relocation) and run it. Check that the state tax in the
   year table looks reasonable across working and retired years.
6. **Update the docs:** the list of states at the top of this page, the state income tax section of
   [Modeling](../modeling.md#state-income-tax) (including anything you approximated), and a line in
   [CHANGELOG.md](../../CHANGELOG.md).
7. **Open a pull request** that lists the sources, the tests, and any approximations.

When a new tax year arrives, update every state's amounts along with the federal rules, and change `base_year`.
