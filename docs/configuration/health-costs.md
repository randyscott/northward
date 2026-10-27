# health_costs.yaml

Optional. The household's healthcare cost assumptions. Without this document, the defaults in
[`rules/healthcare.yaml`](../../data/rules/healthcare.yaml) apply; with it, each field given replaces its default.
Amounts are annual, in today's dollars, and grow with healthcare inflation (CPI plus the market preset's healthcare
spread).

```yaml
schema_version: 1
employer_premium: 4200
out_of_pocket_65_plus: 3000
```

How the costs apply depends on the year: employer coverage while anyone in the household works; individual-market
coverage before 65 otherwise; Medicare (with IRMAA surcharges from the rules) from 65. See
[Modeling](../modeling.md#healthcare).

| Field | Default | Meaning |
|---|---|---|
| `employer_premium` | 6,850 | The household's share of employer coverage while anyone works, paid pre-tax. |
| `individual_premium_age_40` | 7,500 | The unsubsidized individual-market premium per person at age 40, used before 65 when there's no employer coverage. Other ages follow the ACA age curve. |
| `part_d_premium` | 420 | Medicare Part D plan premium per person, before any IRMAA surcharge. |
| `supplement_premium` | 2,160 | Medigap (or similar) premium per person from 65. |
| `out_of_pocket_under_65` | 1,750 | Deductibles, copays, and uncovered care per person before 65. |
| `out_of_pocket_65_plus` | 2,000 | Out-of-pocket costs per person from 65. |
| `dependent_coverage_until_age` | 26 | Dependents are covered (and add to premiums and costs) through the year before this age. |
| `hsa_medical` | `pay_when_retired` | When HSAs pay qualified medical costs tax-free: `pay_when_retired` (once the owner retires), `pay_always`, or `never` (let the HSA grow). |

Medicare Part B premiums and IRMAA thresholds are law, not assumptions, so they're in the rules rather than here.

If your base spending in [spending.yaml](spending.md) already includes healthcare, set
`spending.base.includes_healthcare: true` instead; that turns this model off.
