# Configuration

Everything Northward simulates comes from YAML documents. A **profile** is one household's documents. **Scenarios**
belong to a profile and vary its decisions. **Rules** (tax law, Social Security, market assumptions, and so on) are
shared by every profile. See [Concepts](../concepts.md) for how the three fit together.

You can edit documents in the web UI's editor, which completes keys and explains them on hover, or with
`northward db edit` ([CLI](../cli.md)). Either way, a document is validated before it's saved. The
[example profile](../../data/profiles/example/) uses most features and is a good starting point to copy.

## Documents

| Document | Required | What it holds | Reference |
|---|---|---|---|
| `household.yaml` | yes | Members, dependents, filing status, state of residence | [household](household.md) |
| `accounts.yaml` | yes | Every account: owner, type, balance, investment mix | [accounts](accounts.md) |
| `income.yaml` | no | Salaries (with payroll elections), pensions, other income | [income](income.md) |
| `spending.yaml` | yes | Base spending plus one-off, recurring, and windowed categories | [spending](spending.md) |
| `liabilities.yaml` | no | Mortgages and other loans | [liabilities](liabilities.md) |
| `events.yaml` | no | One-time events: windfalls, home sales, inheritances | [events](events.md) |
| `health_costs.yaml` | no | The household's healthcare cost assumptions | [health costs](health-costs.md) |
| `goals.yaml` | no | What counts as success in Monte Carlo, and how legacy is valued | [goals](goals.md) |
| `scenarios/<name>.yaml` | at least one | Horizon, market preset, levers (decisions), what-if changes | [scenarios](scenarios.md) |
| `rules/*.yaml` | shared | Tax law, contribution limits, RMDs, Social Security, healthcare, glide paths, market presets | [rules](rules.md), [state tax](state-tax.md) |

The editor shows the same field descriptions on hover. A test keeps the two in step: every field of these documents
must have a description and appear on its page.

## Conventions

These apply to every document.

**`schema_version`.** Every document starts with `schema_version: 1`. If the format changes, older versions are
upgraded automatically when they're read.

**Unknown keys are errors.** A misspelled key is reported, not ignored.

**Ids.** Members, dependents, accounts, income streams, spending categories, and so on each have an `id`. An id is
lowercase letters, digits, and underscores, starting with a letter (`alex`, `joint_brokerage`, `sam_529`). Other
documents refer to things by id, and a reference to an id that doesn't exist is an error. Ids must be unique within
their list. Members and dependents share one namespace.

**Owners.** An account or income stream's `owner` is a member id, or `joint`. Some account types (IRAs, 401(k)s,
HSAs) can't be joint.

**Money and dollars.** Amounts are non-negative numbers without currency symbols. Unless a field says otherwise,
amounts are in **today's dollars** (the scenario's start year) and grow with simulated inflation. Rates are fractions:
`0.05` means 5%.

**Anchors.** Many fields say *when* something starts or ends. An anchor is one of:

| Anchor | Example | When |
|---|---|---|
| `year` | `{year: 2031}` | A calendar year. |
| `member` and `age` | `{member: alex, age: 85}` | The year a member reaches an age. |
| `dependent` and `age` | `{dependent: sam, age: 18}` | The year a dependent reaches an age. |
| `event` and `member` | `{event: retirement, member: jordan}` | The year of a member's `retirement` or `death`. An anchor on a death that doesn't happen within the plan never occurs. |

Ages can be fractional (`62.5`), counted in months from the person's birth month.

**Overrides.** A scenario can change any profile value without editing the profile, with dotted paths. A list item is
addressed by its `id`:

```yaml
overrides:
  household:
    members.alex.target_retirement_age: 58
  spending:
    spending.base.amount: 80000
```

## Checking your configuration

`northward validate` checks every stored profile and scenario (or `--profile P --scenario S`). Each problem names the
document, the path to the field (list items by their `id`), and what's wrong. For a misspelled key:

```
profiles/example/household.yaml: members[alex].target_retirement_age: Field required
profiles/example/household.yaml: members[alex].target_retirment_age: Extra inputs are not permitted

2 problem(s) found.
```

The web UI shows the same problems on the lines they point at. `northward show-config --profile P --scenario S`
prints a summary of the loaded configuration.
