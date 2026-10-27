# Changelog

Notable changes to Northward. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Changes
are listed under "Unreleased" until a version is tagged.

## Unreleased

### Changed

- Documentation reorganized: the README is now an overview, and the user and developer guides, configuration
  reference, design decisions, and roadmap live in [`docs/`](docs/README.md). `PLAN.md` was retired. Its decisions
  keep their numbers in [docs/decisions.md](docs/decisions.md).
- Added [AGENTS.md](AGENTS.md) with guidance for AI coding agents.
- A [configuration reference](docs/configuration/README.md) covering every profile and scenario document.
- The YAML editor now explains every field on hover, and completes and checks the fields of each account in
  `accounts`, which it previously treated as free-form.
- The backlog moved to [GitHub issues](https://github.com/randyscott/northward/issues).
- A [state income tax guide](docs/configuration/state-tax.md) for contributing rules for new states.

## 0.1.0 (2026-10-23)

First public release.

- Year-by-year simulation of a household: wages and payroll elections, Social Security (own, spousal, child, and
  survivor benefits), pensions and other income, spending with phases and categories, loans, and one-time events.
- 2026 federal income and payroll tax with credits, plus a generic state engine with Wisconsin implemented in full.
- Contribution limits, RMDs, inherited IRAs, Roth conversions, withdrawal ordering, surplus sweeps, and a cash
  reserve. 529 plans, HSAs, and dependent-care FSAs.
- Healthcare costs (employer, individual market, Medicare and IRMAA), mortality, and survivor transitions.
- Monte Carlo with parametric and historical-bootstrap market presets, sampled lifespans, configurable success
  criteria, and scenario comparison on common random numbers.
- A SQLite database of revisioned documents, recorded and cached runs, backups, and a full CLI.
- An HTTP API and a web UI with a schema-aware YAML editor, a balance grid, results dashboards, run history, and
  scenario comparison.
