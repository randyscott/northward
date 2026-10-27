# Getting started

This walks through installing Northward, exploring the example household, and setting up your own.

## Requirements

- Python 3.10 or newer
- Node.js 20.19 or newer, to build the web UI
- Linux or macOS (on Windows, use WSL)

## Install and start

```bash
git clone https://github.com/randyscott/northward.git
cd northward
make install      # create .venv and install Northward and its development tools
make db           # create var/northward.db and load the rules and the example profile into it
make ui           # build the web UI
make serve        # serve the UI and API at http://127.0.0.1:8000
```

Open http://127.0.0.1:8000. The server listens only on your own machine and has no login, so don't expose it to a
network.

For the command line, activate the virtual environment so `northward` is on your path:

```bash
source .venv/bin/activate
northward --help
```

## Explore the example household

The database starts with one profile, `example`: a fictional two-earner couple with two children, retirement and
college savings, a mortgage, a pension, and an expected inheritance. It has four scenarios:

| Scenario | What it shows |
|---|---|
| `base` | The plan as it stands: retire at 62 and 65, claim Social Security at 67. |
| `early_retire_roth_fill` | Alex retires at 58, fills the 22% bracket with Roth conversions, delays Social Security to 70, and keeps a $50,000 emergency fund. |
| `historical_lifespans` | Historical market years and randomly drawn lifespans. |
| `survivor` | Alex dies at 74, and the household moves to Wisconsin in 2045. |

In the web UI:

1. Open the `example` profile. The overview lists its documents and scenarios.
2. Open the `base` scenario and run it **deterministically**. You get one path with average returns: a year-by-year
   table, balances by account type, taxes, income, and the full ledger of every transaction.
3. Run it with **Monte Carlo**. Northward simulates thousands of possible market histories and shows the probability
   that the plan holds up, with a range of outcomes for net worth.
4. Use **Compare** to run `base` and `early_retire_roth_fill` on the same simulated markets and see the differences.

The same from the command line:

```bash
northward run --profile example --scenario base                     # deterministic
northward mc --profile example --scenario base --sims 5000 --seed 1  # Monte Carlo
northward compare --profile example --scenario base --scenario early_retire_roth_fill
```

## Set up your own household

The quickest way is to copy the example and change it:

1. In the web UI, create a new profile as a copy of `example`.
2. Edit each document to match your household. Start with `household`, then `accounts`, `income`, and `spending`.
   The editor completes field names, explains them on hover, and marks problems as you type. The
   [configuration reference](configuration/README.md) describes every document.
3. Clear out what you don't need. An optional document such as `events` can't be deleted, but saving it with only
   `schema_version: 1` is the same as not having it. Delete the example scenarios except `base`.
4. Edit the `base` scenario's levers (retirement ages, Social Security claiming ages), run it, then clone it to try
   alternatives.

You'll need: current account balances (and the cost basis of taxable accounts), salaries and payroll
elections, your Social Security benefit at full retirement age from [ssa.gov/myaccount](https://www.ssa.gov/myaccount/),
and an estimate of annual spending.

**Your data stays on your machine.** Profiles live in the database at `var/northward.db`, which git ignores. Back it
up with `northward db backup` ([CLI](cli.md#backups)).

## Next steps

- [Concepts](concepts.md): profiles, scenarios, rules, and runs.
- [Configuration](configuration/README.md): every document and field.
- [Modeling](modeling.md): what the engine models, and what it doesn't.
