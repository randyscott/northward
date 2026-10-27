# Concepts

The ideas you need to use Northward well.

## Profiles, scenarios, and rules

A **profile** describes one household as it is today: who's in it, what they own and owe, what they earn, and what
they spend. It's a set of YAML documents (`household`, `accounts`, `income`, `spending`, and a few optional ones).

A **scenario** belongs to a profile and describes one plan for the future:

- **horizon:** the first simulated year, and the age (or year) the plan runs to
- **market:** which market preset to use, with any changes to it
- **levers:** the decisions being tested: Social Security claiming ages, withdrawal order, Roth conversions,
  contributions, an emergency fund, relocations, and lifespans
- **events:** what-if one-time events, in addition to the profile's own
- **overrides:** changes to the profile for this scenario only, such as an earlier retirement age or lower spending

A profile usually has several scenarios: a `base` plan, and variations of it to compare.

**Rules** are shared by every profile: tax brackets, contribution limits, RMD tables, Social Security rules, Medicare
premiums, and market assumptions. They change once a year, when a new tax year's figures are published.

The [configuration reference](configuration/README.md) covers every document.

## Documents and revisions

Profiles, scenarios, and rules are stored in a SQLite database (`var/northward.db`). Saving a document never
overwrites it: it adds a **revision**. You can see a document's history, diff any two revisions, and restore an old
one.

Every save is validated first. The document must be valid on its own, and the whole profile, with every one of its
scenarios, must still load. A change that would break something is rejected with a list of the problems, and nothing
is saved.

Rule files are different: the copies in `data/rules/` are the master copy, kept in git. `northward db seed` loads them
into the database.

## Runs

A **run** simulates a scenario. Northward simulates one year at a time: income comes in, required distributions are
taken, spending and taxes are paid, surpluses are invested, and markets move. See
[the yearly cycle](architecture.md#the-yearly-cycle).

- A **deterministic run** uses one constant return for each asset class and a fixed inflation rate. It produces a
  single path with every detail: a year-by-year table and a ledger of every transaction.
- A **Monte Carlo run** simulates thousands of paths (5,000 by default), each with different market returns and
  inflation, and, optionally, different lifespans. It reports how likely the plan is to succeed, and the range of
  outcomes. You can open any single path in full detail.

Every run records the exact revisions of the documents it used. Rerunning a stored run reproduces it exactly, even
after the documents have changed. A Monte Carlo run with the same inputs, seed, and number of paths as a stored one
returns the stored result instead of running again.

## Success

By default, a Monte Carlo path **succeeds** if spending and taxes are fully paid every year. A profile's `goals.yaml`
can add a **liquidity floor**: cash plus brokerage accounts never below an amount, in today's dollars. The probability
of success is the share of paths that succeed.

Success criteria are applied to the stored results, so you can change them and see the new probability without
rerunning.

## Comparing scenarios

Comparing two scenarios is the main use of Northward: claiming Social Security at 62 or 70, converting to Roth or
not, retiring a year earlier. A comparison runs each scenario on **the same simulated markets** (common random
numbers), so the differences come from the decision, not from luck in the random draws. It reports the change in the
probability of success, in legacy, and in lifetime taxes, and how often one scenario ends with more than the other.

## Today's dollars and nominal dollars

The engine works in **nominal** dollars: the actual dollars of each future year. Results can be shown in **today's
dollars** (the scenario's start year), which divides out the simulated inflation so amounts decades apart can be
compared. Most amounts you enter are in today's dollars and grow with inflation, unless the field says otherwise.
