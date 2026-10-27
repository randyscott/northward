# events.yaml

Optional. One-time events the household expects: a windfall, the sale of a home, an inheritance. A scenario can add
what-if events of its own in its `events` list, in the same format; they happen in addition to these.

```yaml
schema_version: 1

events:
  - id: parents_ira
    kind: inheritance
    description: "Inherited traditional IRA from Jordan's parent"
    when: {year: 2032}
    amount: 180000
    beneficiary: jordan
    asset: inherited_ira
    account: jordan_inherited_ira
    decedent_started_rmds: true

  - id: condo_sale
    kind: home_sale
    description: "Sell the rental condo"
    when: {year: 2034}
    price: 260000
    cost_basis: 190000

  - id: bonus
    kind: windfall
    when: {member: alex, age: 55}
    amount: 50000
    tax_character: ordinary
    owner: alex
```

`events` is a list. Each event's `kind` is `windfall`, `home_sale`, or `inheritance`, and every event has:

| Field | Meaning |
|---|---|
| `id` | Shown in the results and the ledger. |
| `description` | Optional. A note for yourself, also used as the ledger label. |
| `when` | An [anchor](README.md#conventions) for the year it happens. An event anchored to a death that doesn't occur never happens. |

Amounts of windfalls and inheritances are in today's dollars by default, grown with simulated inflation to the
event's year. Set `dollars: nominal` to give the amount in that year's dollars instead.

## Windfall

Money received once: a bonus, a gift, the sale of a business.

| Field | Default | Meaning |
|---|---|---|
| `amount` | required | The amount received. |
| `dollars` | `today` | `today` or `nominal`. |
| `tax_character` | `tax_free` | `tax_free`, `ordinary` (taxed as ordinary income), or `long_term_gain` (the whole amount is a long-term capital gain). |
| `owner` | joint | Whose income it is, for an ordinary windfall. |
| `deposit_to` | cash | An account to deposit it in. Without one, it goes to cash, where it pays the year's bills and the rest is swept. |

## Home sale

The sale of a home. The proceeds after selling costs go to cash.

| Field | Default | Meaning |
|---|---|---|
| `price` | required | The sale price in today's dollars, grown by `appreciation` to the year of the sale. |
| `appreciation` | `general` | Annual growth of the price: a rate such as `0.03`, or `general` to follow simulated inflation. |
| `cost_basis` | required | Purchase price plus improvements, in actual dollars. |
| `selling_costs` | `0.06` | Commissions and closing costs, as a share of the price. |
| `pay_off` | none | A [liability](liabilities.md) id to repay from the proceeds, such as the mortgage. |

The gain above the §121 exclusion ($250,000, or $500,000 married filing jointly) is taxed as a long-term capital
gain. The exclusion is always applied, so the ownership and use tests are assumed to be met. Rental or second-home
sales that don't qualify for the exclusion cannot generally be modeled correctly by adjusting `cost_basis`; this
event doesn't support disabling the exclusion.

## Inheritance

Money or an IRA inherited from someone outside the household. (Accounts passing between spouses are handled
automatically when a member dies.)

| Field | Default | Meaning |
|---|---|---|
| `amount` | required | The value inherited. |
| `dollars` | `today` | `today` or `nominal`. |
| `beneficiary` | required | The member who inherits. |
| `asset` | required | `cash` (received tax-free), `brokerage` (added to an existing brokerage account with a stepped-up basis, so no gain), or `inherited_ira`. |
| `account` | required unless `cash` | For `brokerage`, the account that receives it. For `inherited_ira`, the id of the new inherited IRA, which opens in that year. |
| `decedent_started_rmds` | `true` | For `inherited_ira`: whether the original owner had started RMDs. If so, annual RMDs apply in years 1–9 as well as emptying the account by year 10. |
| `asset_strategy` | 60% stocks, 40% bonds | For `inherited_ira`: how it's invested ([asset strategies](accounts.md#asset-strategies)). |

How an inherited IRA is drawn down within its 10 years is a scenario lever, `levers.inherited_ira`
([scenarios](scenarios.md#inherited_ira)).
