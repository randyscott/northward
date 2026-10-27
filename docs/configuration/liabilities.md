# liabilities.yaml

Optional. Mortgages, car loans, and other debt. Each year's payments are made in addition to
[spending](spending.md), and the balances count against net worth.

```yaml
schema_version: 1

liabilities:
  - id: mortgage
    kind: amortizing
    description: "Primary residence, 30-year fixed"
    balance: 285000
    annual_rate: 0.0425
    monthly_payment: 1968.0

  - id: car_loan
    kind: amortizing
    balance: 18000
    annual_rate: 0.059
    remaining_term_months: 36

  - id: heloc
    kind: interest_only
    balance: 40000
    annual_rate: 0.08
    payoff: {member: alex, age: 62}
```

`liabilities` is a list of loans. Each loan's `kind` is `amortizing` or `interest_only`.

## Amortizing loans

A fixed monthly payment that covers interest and pays down the balance: a mortgage or car loan.

| Field | Default | Meaning |
|---|---|---|
| `id` | required | Shown in the results; a home-sale [event](events.md) can pay the loan off by this id. |
| `description` | none | A note for yourself. |
| `balance` | required | The balance owed now. |
| `annual_rate` | required | The interest rate, e.g. `0.0425`. |
| `monthly_payment` | one of these two | The scheduled principal and interest payment, without escrow for taxes and insurance (put those in spending). |
| `remaining_term_months` | one of these two | Months left on the loan; the payment is computed from it. |
| `extra_monthly_payment` | `0` | Extra principal paid each month, which pays the loan off sooner. |

A `monthly_payment` that doesn't cover the monthly interest is an error, since the loan would never be repaid.
Payments are fixed in nominal dollars, so they shrink in today's dollars over time.

## Interest-only loans

| Field | Default | Meaning |
|---|---|---|
| `id` | required | Shown in the results. |
| `description` | none | A note for yourself. |
| `balance` | required | The balance owed, repaid in full at `payoff`. |
| `annual_rate` | required | Interest is paid each year on the full balance. |
| `payoff` | required | An [anchor](README.md#conventions) for the year the balance is repaid as a lump sum. |

Interest isn't deductible: the standard deduction is always taken (see [Modeling](../modeling.md)).
