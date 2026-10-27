# Northward

Northward is a retirement-planning tool for one household. It simulates the years ahead one at a time, with taxes,
Social Security, RMDs, Roth conversions, healthcare, and survivor transitions. It then runs thousands of Monte Carlo
paths to show how likely a plan is to hold up. You can compare decisions, such as claiming Social Security at 62 or
70, on the same simulated markets.

It runs on your own machine: a Python engine and API, a local database of your documents, and a web app. Your data
never leaves your computer.

It's planning software, not financial advice; check anything important with a professional.

## What it does

- **Year-by-year simulation** of a one- or two-person household with dependents: salaries and payroll elections,
  Social Security (own, spousal, child, and survivor benefits), pensions, spending that changes with age and life
  events, loans, and one-time events such as home sales and inheritances.
- **Taxes** under 2026 law: federal income tax with credits, capital gains, NIIT, Social Security taxability, FICA,
  and early-withdrawal penalties, plus state income tax (Wisconsin today, through a generic state engine; other
  states [can be added](docs/configuration/state-tax.md#adding-a-state) with rules alone).
- **Retirement accounts:** contribution limits and catch-ups, RMDs, inherited IRAs, Roth conversions (fixed or
  bracket-filling), withdrawal order, and an emergency fund. 529 plans and HSAs too.
- **Healthcare:** employer coverage, individual-market premiums before 65, and Medicare with IRMAA.
- **Monte Carlo** with forward-looking or historical market assumptions, optional random lifespans, and success
  criteria you can change without rerunning.
- **Scenario comparison** on common random numbers, so differences come from the decision, not from luck.
- **Every result is reproducible.** Documents are revisioned, and each run records the exact revisions it used.

See [What Northward models](docs/modeling.md) for the details and the limitations.

## Quick start

Requires Python 3.10+ and Node.js 20.19+.

```bash
git clone https://github.com/randyscott/northward.git
cd northward
make install      # Python environment and dependencies
make db           # create the database and load the rules and an example household
make ui           # build the web UI
make serve        # open http://127.0.0.1:8000
```

Then follow [Getting started](docs/getting-started.md) to explore the example household and set up your own.

## Documentation

- [Getting started](docs/getting-started.md) and [Concepts](docs/concepts.md)
- [Configuration reference](docs/configuration/README.md): what goes in each document
- [Web UI](docs/web-ui.md), [Command line](docs/cli.md), and [HTTP API](docs/api.md)
- [Development](docs/development.md), [Architecture](docs/architecture.md), and [Design decisions](docs/decisions.md)
- [Roadmap](docs/roadmap.md) and [Changelog](CHANGELOG.md)

## Status

Northward is a personal project. It's single-user, and its server has no
authentication, so it listens only on your own machine. Tax rules cover 2026; each new tax year's figures are added
as a new rule set, so old results don't change.

Licensed under the [MIT License](LICENSE).
