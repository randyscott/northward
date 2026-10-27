# goals.yaml

Optional. What counts as success in a Monte Carlo run, and how the money left at the end (the legacy) is valued.
Every scenario of the profile uses the same goals, so comparisons share one yardstick. A scenario can still change
them through `overrides`, and the CLI, API, and web UI can apply one-off changes when computing statistics, without
rerunning.

```yaml
schema_version: 1

success:
  no_shortfall: true
  shortfall_tolerance: 1
  liquidity_floor:
    amount: 50000
    start: {event: retirement, member: alex}

legacy:
  heirs_tax_rate: 0.25
```

Without a `goals.yaml`, a path succeeds when spending and taxes are paid in full every year, and heirs' tax is 25%.

## success

A path succeeds when every enabled criterion holds in every simulated year. The probability of success is the share
of paths that succeed.

| Field | Default | Meaning |
|---|---|---|
| `no_shortfall` | `true` | Fail a path in any year spending and taxes aren't paid in full (after drawing on every account the scenario allows). |
| `shortfall_tolerance` | `1` | Ignore a yearly shortfall up to this many dollars, for rounding. |
| `liquidity_floor` | none | Fail a path if liquid assets fall below a floor at the end of any year. |

**Liquidity floor.** Liquid assets are cash and brokerage accounts (and any cash not yet swept). Retirement
accounts and HSAs don't count, since drawing on them can mean tax and penalties.

| Field | Default | Meaning |
|---|---|---|
| `amount` | required | The floor, in today's dollars (it grows with simulated inflation). |
| `start` | the plan's start | An [anchor](README.md#conventions) for the first year the floor applies, such as a retirement. |

To keep money aside that withdrawals leave alone, rather than just measuring it, use the scenario's
[`cash_reserve`](scenarios.md#cash_reserve) lever.

## legacy

| Field | Default | Meaning |
|---|---|---|
| `heirs_tax_rate` | `0.25` | The income tax rate heirs pay on inherited pre-tax money (traditional retirement accounts and HSAs), used to report an after-tax legacy. |
