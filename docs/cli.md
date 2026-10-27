# Command line

Everything the web UI does can also be done with the `northward` command, plus database administration, backups,
and benchmarking. Activate the virtual environment first (`source .venv/bin/activate`), or run `.venv/bin/northward`.
`northward <command> --help` lists every option.

## Global options

These go before the command (`northward --db URL runs list`).

| Option | Meaning |
|---|---|
| `--db URL` | Database URL. Default: `$NORTHWARD_DATABASE_URL`, else `sqlite:///var/northward.db`. |
| `--data-dir DIR` | Read the `rules/` and `profiles/` files under `DIR` instead of the database. Runs in this mode aren't recorded. Tests and `make bench` use it. |
| `--runs-dir DIR` | Where run outputs go. Default: `var/runs`. |

## Checking configuration

```bash
northward validate                                       # every stored profile and scenario
northward validate --profile example --scenario base     # just one
northward show-config --profile example --scenario base  # a summary of the loaded configuration
```

## Running simulations

```bash
# A deterministic run: writes years.csv and ledger.csv to var/runs/<run id>/ (--format json, --no-ledger)
northward run --profile example --scenario base

# Monte Carlo: 5,000 paths by default, seed 1. Writes telemetry.npz, summary.json, and bands.csv
northward mc --profile example --scenario base --sims 5000 --seed 1

# Re-score a stored Monte Carlo run under other success criteria, without rerunning it
northward stats 12 --liquidity-floor 50000

# Re-run one path of a stored run with the full ledger (for example, a representative path from its summary)
northward run --from-run 12 --path 123

# Compare scenarios on the same simulated markets; the first scenario is the baseline
northward compare --profile example --scenario base --scenario early_retire_roth_fill
```

`mc`, `stats`, and `compare` accept goal overrides for the statistics: `--liquidity-floor`, `--allow-shortfall`,
`--shortfall-tolerance`, and `--heirs-tax-rate`. `mc` and `compare` also take `--workers` (default: one per CPU) and
`--no-cache`.

Every path draws from its own seeded random streams, so a run gives identical results however many worker processes
it uses, and any path can be regenerated alone. A Monte Carlo run with the same inputs, engine version, seed, and
number of paths as a stored one returns the stored result; `--no-cache` runs it again.

## Stored runs

Every run from the database is recorded, with the exact revisions of the documents it read.

```bash
northward runs list [--profile P] [--scenario S]
northward runs show 12           # details, pinned revisions, headline results
northward runs rerun 12          # run again on the pinned revisions and check the results are identical
```

## Documents

Documents are addressed as in the `data/` layout: `household`, `accounts`, ..., `scenarios/<name>`.

```bash
northward db list [--deleted]                 # rule sets, profiles, and scenarios
northward db list --profile example           # a profile's documents (and optional ones it lacks)

northward db edit --profile example accounts --note "Q3 statements"   # opens $VISUAL/$EDITOR; saves if valid
northward db edit --profile example accounts scenarios/base           # several documents, validated together
northward db put --profile example accounts.yaml scenarios/what_if=/tmp/what_if.yaml   # save files as revisions
northward db show --profile example accounts [--revision 3]           # or: --rule-set 2026 federal_tax
northward db history --profile example [accounts]
northward db diff --profile example accounts [OLD [NEW]]              # default: the last two revisions
northward db revert --profile example accounts --revision 3           # saves revision 3's text as a new revision
```

If `db edit` finds a problem, it shows it and offers to reopen the editor.

## Profiles and scenarios

```bash
northward db put --create --profile mine household.yaml accounts.yaml spending.yaml scenarios/base.yaml
northward db clone --profile example base retire_at_60             # a new scenario from an existing one
northward db delete --profile example --scenario retire_at_60      # soft delete; `db restore` undoes it
northward db purge --profile example --scenario retire_at_60 --yes # permanent, once deleted; refuses without --yes
```

Another way to add a profile is to put its files under `data/profiles/<name>/` and run `northward db seed`, which
imports profiles and scenarios that aren't stored yet. After that, the database is the master copy and the files
aren't read again.

## Rules

```bash
northward db seed                # store data/rules (new revisions only for changed files); import new profiles
```

Rule sets are named for their tax year. Seeding changed rule files adds revisions to that year's rule set, and a new
tax year becomes a new rule set. A scenario uses the latest unless it pins one (`rule_set: 2026`).

## Backups

```bash
northward db backup              # every document plus a copy of the SQLite file, in var/backups/<timestamp>/
northward db backup DIR          # ...or in DIR
northward db export [DIR] [--profile P]   # the documents alone, in the data/ layout
```

Run outputs in `var/runs/` can be regenerated from the database, so they don't need backing up. To back up nightly
at 2 a.m. into a synced folder, add this with `crontab -e`:

```cron
0 2 * * * cd /path/to/northward && .venv/bin/northward db backup ~/Backups/northward/$(date +\%Y\%m\%d) >/dev/null
```

To restore everything, copy a backup's `northward.db` to `var/northward.db`; that keeps every revision and run.
Seeding an empty database from a backup's `data/` directory restores only the latest revisions:

```bash
northward db init && northward db seed ~/Backups/northward/20261016/data
```

## Database administration

```bash
northward db init                # create var/northward.db, or bring its schema up to date
northward db migrate             # upgrade the schema
```

## Server

```bash
northward serve [--host HOST] [--port PORT] [--workers N] [--ui-dir DIR]
northward openapi [FILE]         # write the OpenAPI schema
```

See [HTTP API](api.md) and [Web UI](web-ui.md).
