# What Northward models

Northward models a US household's finances one calendar year at a time, using **2026** federal tax law and the
rules in [`data/rules/`](../data/rules/). Each rules file cites its primary sources (IRS revenue procedures and
notices, SSA's rules, CMS, and state revenue departments). This page summarizes what the engine covers and, just as
important, what it leaves out or simplifies.

Northward is planning software, not financial advice. Check anything important with a professional.

## Federal income and payroll tax

- Ordinary income brackets and standard deductions for every filing status, including the extra deduction at 65 and
  the senior deduction for 2025–2028 (with its income phase-out).
- Long-term capital gains and qualified dividends taxed at their own rates, stacked on top of ordinary income. The
  Net Investment Income Tax.
- The taxable share of Social Security (the 0/50/85% tiers).
- Capital losses: $3,000 a year against ordinary income ($1,500 married filing separately), with the rest carried
  forward.
- FICA per earner: Social Security tax up to the wage base, Medicare, and the Additional Medicare Tax.
- The 10% additional tax on early retirement-plan withdrawals, and 20% on non-medical HSA withdrawals before 65.
- Credits, in IRS order: the Child and Dependent Care Credit, the American Opportunity and Lifetime Learning
  credits (the better of the two per student), and the Child Tax Credit (with its refundable part) and Credit for
  Other Dependents. Each has its own income phase-out.
- Brackets and deductions grow with **simulated** inflation. Amounts fixed by statute stay fixed.

**Settling the bill.** Withdrawing money to pay tax creates more tax, so the engine repeats the calculation,
withdrawing more each round, until the extra tax is under $1. It usually converges in three to five rounds.

**Simplifications:** the standard deduction is always taken (no itemizing); MAGI equals AGI for every provision; every
dependent has a valid SSN; a qualifying relative's income and support tests aren't checked; and the care credit's
earned-income exception for students and disabled spouses isn't modeled. Indexed amounts follow deflation down, as
well as inflation up.

## State income tax

A generic engine handles flat and bracketed state taxes, with optional exemptions for Social Security, pensions,
retirement income, and part of capital gains; state standard deductions, exemptions, and credits; and a deduction for
529 contributions. A scenario can move the household to another state in a given year.

States available today: `none` (no income tax) and Wisconsin. Wisconsin's 2026 rules are modeled in full from the
Department of Revenue's sources, including its sliding standard deduction, the 30% capital-gain exclusion, the
retirement-income subtractions, the 529 deduction, and the married-couple credit. **Not modeled for Wisconsin:** the
school property tax credit, the itemized-deduction credit, the cap on the dependent-care exclusion, 529 recapture,
rounding of indexed amounts, and separate Wisconsin capital-loss carryovers. Qualifying surviving spouses use
Wisconsin's head-of-household amounts.

Adding a state usually means only adding its rules to `rules/state_tax.yaml`; see
[State income tax](configuration/state-tax.md) for the fields, the steps, and what needs code too. Contributions are
welcome.

## Social Security

- Each member's benefit starts from their **Primary Insurance Amount at full retirement age** (from their SSA
  statement), in today's dollars. The engine applies early-claiming reductions and delayed credits up to 70, and
  cost-of-living adjustments that follow simulated inflation (never negative).
- Spousal benefits, child benefits, and the benefit for a spouse caring for a child under 16, all within the family
  maximum.
- The earnings test when claiming before full retirement age while still working, with withheld months credited back.
- Survivor benefits, the mother's or father's benefit, and surviving-child benefits.
- Benefits are worked out month by month, so a claim, death, or birthday lands in the right month.

**Simplifications:** the PIA isn't computed from earnings history, and real wage growth before 62 isn't added to it.
Benefit months are whole months. The earnings test withholds only the earner's own and spousal benefits. A survivor
claims the survivor benefit as soon as eligible, rather than choosing when to switch.

## Saving and spending

- **Payroll:** 401(k) deferrals (percent, amount, or the maximum, with age 50+ and 60–63 catch-ups and the SECURE 2.0
  Roth catch-up rule), employer matches, payroll HSA contributions, and dependent-care FSAs.
  See [income](configuration/income.md).
- **Other contributions:** IRA and Roth IRA contributions with their income phase-outs and deductibility rules, the
  §415(c) cap, shared family HSA limits, and 529 contributions. All limits come from the rules and grow with inflation.
- **Spending:** a base amount with age phases and a change at retirement, plus categories that occur once, repeat,
  or run for a window. See [spending](configuration/spending.md).
- **Loans:** amortizing and interest-only debt, paid off on schedule.
- **Withdrawals:** when cash runs short, accounts are drawn down in the scenario's order (by default taxable, then
  tax-deferred, then Roth, then HSA). Taxable accounts use average-cost basis.
- **Surpluses** are invested in the scenario's sweep targets (by default the first brokerage account).
- **An emergency fund** (`levers.cash_reserve`) is left alone until every other account is exhausted, and topped up
  each year.

**Simplifications:** no specific-lot basis or tax-loss harvesting; Roth withdrawals are always tax- and penalty-free
(contribution basis and the 5-year rules aren't tracked); nondeductible IRA basis isn't tracked; and an age-based
penalty threshold counts as reached for the whole year it falls in.

## Required distributions and Roth conversions

- **RMDs** start at the age set by the owner's birth year (75 for anyone born in 1960 or later), from the Uniform
  Lifetime table. A workplace plan waits while the owner still works there.
- **Inherited IRAs** follow the 10-year rule, with annual RMDs when the original owner had started them. The scenario
  picks how to draw them down: evenly, the minimum then the rest in year 10, or filling a tax bracket.
- **Roth conversions:** a fixed amount a year, or enough to fill a chosen tax bracket, over a window of years. The tax
  is paid from taxable accounts or withheld from the conversion. An optional guard stops a conversion short of
  losing a credit or deduction the household is getting.

Conversions and bracket-filling withdrawals happen after the year's other income and spending are known, so they're
sized against the whole year.

## Education

- **529 plans:** tax-free growth, withdrawals for qualified education (coordinated with the American Opportunity
  credit), and a choice of what to do with leftover money. See [529 accounts](configuration/accounts.md#529-accounts).
- **Education credits** from spending tagged `qualified_education`.

**Simplifications:** the 529-to-Roth rollover ignores the 5-year contribution lookback and assumes the beneficiary
has enough earned income. The gift-tax 5-year election isn't modeled.

## Healthcare

- **While anyone works:** the employer premium, paid pre-tax.
- **Before 65 otherwise:** individual-market premiums from the ACA age curve, **without subsidies**.
- **From 65:** Medicare Parts B and D, IRMAA surcharges based on income from two years earlier, and a supplement.
- **Out-of-pocket costs**, growing with healthcare inflation. HSAs pay qualified costs tax-free.

Defaults come from `rules/healthcare.yaml`; a profile's `health_costs.yaml` can override them.

**Not modeled:** ACA premium tax credits, IRMAA appeals after a life-changing event, and age-based increases in
Medigap premiums.

## Survivors

When a member dies:

- **Filing status:** married filing jointly in the year of death. Then, with a dependent child, qualifying surviving
  spouse for two years, then head of household while a qualifying dependent remains, then single. Without a
  dependent child, single from the next year.
- **Social Security:** the survivor keeps the larger of their own benefit and the survivor benefit. Children and a
  survivor caring for a young child may get benefits too.
- **Accounts** pass to the survivor. Retirement accounts become the survivor's own, with RMDs based on the survivor's
  age. Taxable accounts get a stepped-up basis on the deceased's share (both halves in community-property states).
- **Income and spending:** salary and healthcare costs for the deceased stop, pensions continue at their survivor
  fraction, and base spending is multiplied by the survivor multiplier (0.75 by default).

## One-time events

Windfalls (tax-free, ordinary income, or capital gain), home sales (with the §121 exclusion, selling costs, and an
optional mortgage payoff), and inheritances (cash, stepped-up brokerage, or an inherited IRA). Home sales assume the
§121 ownership and use tests are met.

## Markets and Monte Carlo

- Stocks, bonds, cash, and inflation are drawn together each year, with correlations, from a
  [market preset](configuration/rules.md#market-presets): lognormal, normal, or fat-tailed (Student-t)
  distributions, or whole historical years from 1928–2025, resampled in blocks.
- Lifespans can be fixed, or drawn from the SSA 2023 period life table.
- Compared scenarios run on the same draws.

**Simplifications:** only market returns, inflation, and (optionally) lifespans are random. Wage growth, the
education and healthcare spreads, and dividend and interest yields are fixed. The life table has no mortality
improvement, and spouses' lifespans are independent. Per-path warnings aren't summarized across a Monte Carlo run;
open a single path to see them.

## Not modeled yet

Larger gaps, most of them tracked as [GitHub issues](https://github.com/randyscott/northward/issues):

- Itemized deductions: state and local taxes, mortgage interest, charitable gifts
  ([#9](https://github.com/randyscott/northward/issues/9)).
- ACA premium tax credits ([#10](https://github.com/randyscott/northward/issues/10)).
- Tax-law changes over time, such as provisions that expire ([#2](https://github.com/randyscott/northward/issues/2)).
- Dynamic spending rules, such as guardrails ([#3](https://github.com/randyscott/northward/issues/3)).
- Annuities ([#6](https://github.com/randyscott/northward/issues/6)), long-term care
  ([#7](https://github.com/randyscott/northward/issues/7)), and qualified charitable distributions
  ([#8](https://github.com/randyscott/northward/issues/8)).
- College financial aid ([#13](https://github.com/randyscott/northward/issues/13)), and the kiddie tax, custodial
  (UTMA/UGMA) accounts, and the Earned Income Tax Credit ([#14](https://github.com/randyscott/northward/issues/14)).
- Rules for states other than Wisconsin.
