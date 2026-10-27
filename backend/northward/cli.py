"""Northward's command line (`northward ...`)."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from northward.config.base import ConfigError
from northward.config.goals import GoalsDoc
from northward.config.loader import SimulationInput, iter_all, load_simulation_input, validate_all
from northward.config.source import ConfigSource, FileSource
from northward.engine.export import write_result
from northward.engine.results import SimulationResult
from northward.engine.simulate import simulate
from northward.montecarlo import report, stats, telemetry
from northward.montecarlo.runner import run_monte_carlo, simulate_path
from northward.montecarlo.telemetry import MonteCarloResult, year_income
from northward.persistence import runs
from northward.persistence.commands import add_db_commands, add_runs_commands, db_command, runs_command, when
from northward.persistence.db import DEFAULT_URL, URL_ENV, Database, DatabaseError
from northward.persistence.repositories import NotFound
from northward.persistence.source import DbSource

DEFAULT_SIMS = 5000
DEFAULT_SEED = 1


def _validate(source: ConfigSource, profile: str | None, scenario: str | None) -> int:
    pairs = [
        (p, s) for p, s in iter_all(source) if (profile is None or p == profile) and (scenario is None or s == scenario)
    ]
    if not pairs:
        print("No matching profiles/scenarios found.", file=sys.stderr)
        return 1
    issues = validate_all(source, pairs)
    if issues:
        for issue in issues:
            print(issue, file=sys.stderr)
        print(f"\n{len(issues)} problem(s) found.", file=sys.stderr)
        return 1
    print(f"OK: {len(pairs)} scenario(s) across {len({p for p, _ in pairs})} profile(s) are valid.")
    return 0


def _show_config(sim: SimulationInput) -> None:
    profile, scenario = sim.profile, sim.scenario
    household = profile.household
    print(f"Profile {sim.profile_name!r}, scenario {sim.scenario_name!r}")
    if scenario.description:
        print(f"  {scenario.description}")

    print(f"\nHousehold ({household.household.filing_status.value}):")
    for m in household.members:
        print(
            f"  {m.id:<12} {m.name:<22} born {m.birth_year}-{m.birth_month:02d}, retire at {m.target_retirement_age:g}"
        )
    for d in household.dependents:
        print(f"  {d.id:<12} {d.name:<22} born {d.birth_year}-{d.birth_month:02d} ({d.relationship})")

    print("\nAccounts:")
    for a in profile.accounts:
        print(f"  {a.id:<20} {a.type:<26} {a.owner:<8} {a.balance:>14,.0f}")
    print(f"  {'total':<56} {sum(a.balance for a in profile.accounts):>14,.0f}")

    if profile.income.income_streams:
        print("\nIncome:")
        for stream in profile.income.income_streams:
            amount = getattr(stream, "amount", None) or getattr(stream, "annual_amount", 0.0)
            print(f"  {stream.id:<20} {stream.type:<26} {stream.owner:<8} {amount:>14,.0f}")
    if profile.liabilities.liabilities:
        print("\nLiabilities:")
        for liability in profile.liabilities.liabilities:
            print(f"  {liability.id:<20} {liability.kind:<26} {'':<8} {liability.balance:>14,.0f}")

    spending = profile.spending
    print(f"\nSpending: base {spending.base.amount:,.0f}/yr + {len(spending.categories)} categories")

    horizon, levers = scenario.horizon, scenario.levers
    end = f"year {horizon.end_year}" if horizon.end_year else f"all members age {horizon.end_age}"
    print(f"\nHorizon: {horizon.start_year} until {end}")
    print(f"Market preset: {sim.market.id}" + (" (with overrides)" if scenario.market.overrides else ""))
    print(f"Withdrawal order: {' > '.join(levers.withdrawal_order)}")
    print(f"Roth conversions: {levers.roth_conversions.kind}")
    for member_id, claim in levers.ss_claim_ages.items():
        print(f"SS claim age {member_id}: {claim.years}y{claim.months}m")
    print(f"Mortality: {levers.mortality.kind}")
    success = profile.goals.success
    criteria = ["never short on spending"] if success.no_shortfall else []
    if success.liquidity_floor is not None:
        criteria.append(f"liquid assets at least {success.liquidity_floor.amount:,.0f} (today $)")
    print(f"Success: {' and '.join(criteria) or 'always'}; heirs' tax rate {profile.goals.legacy.heirs_tax_rate:.0%}")


def _print_run_summary(result: SimulationResult, title: str = "Deterministic run") -> None:
    print(f"{title}: profile {result.profile!r}, scenario {result.scenario!r}")
    header = f"{'Year':>5} {'Ages':<9} {'Income':>11} {'Spending':>11} {'Taxes':>10} {'Withdrawn':>11} {'Net worth':>13} {'(today $)':>12}"
    print(header)
    print("-" * len(header))
    last = len(result.years) - 1
    for i, state in enumerate(result.years):
        if i % 5 and i != last:
            continue
        f = state.flows
        income = year_income(state)
        ages = "/".join(str(a) for a in state.ages.values())
        print(
            f"{state.year:>5} {ages:<9} {income:>11,.0f} {f.total_spending + f.debt_payments:>11,.0f} "
            f"{f.total_taxes:>10,.0f} {sum(f.withdrawals.values()):>11,.0f} {state.net_worth:>13,.0f} "
            f"{state.net_worth / state.price_level:>12,.0f}"
        )
    for warning in result.warnings:
        print(f"warning: {warning}")


def _add_goal_options(parser: argparse.ArgumentParser) -> None:
    group = parser.add_argument_group("success criteria (override the profile's goals.yaml)")
    group.add_argument("--allow-shortfall", action="store_true", help="Don't fail paths that are short on spending.")
    group.add_argument("--shortfall-tolerance", type=float, help="Yearly shortfall (dollars) treated as rounding.")
    group.add_argument(
        "--liquidity-floor",
        type=float,
        help="Fail paths whose liquid assets drop below this (today's dollars; 0: off).",
    )
    group.add_argument("--heirs-tax-rate", type=float, help="Heirs' tax rate on pre-tax accounts, for legacy.")


def _goals(sim: SimulationInput, args: argparse.Namespace) -> GoalsDoc:
    return sim.profile.goals.with_overrides(
        args.allow_shortfall, args.shortfall_tolerance, args.liquidity_floor, args.heirs_tax_rate
    )


def _progress(label: str) -> Callable[[int, int], None] | None:
    if not sys.stderr.isatty():
        return None

    def show(done: int, total: int) -> None:
        print(f"\r{label}: {done:,}/{total:,} paths", end="" if done < total else "\n", file=sys.stderr, flush=True)

    return show


def _progress_for(sim: SimulationInput) -> Callable[[int, int], None] | None:
    return _progress(f"{sim.profile_name}/{sim.scenario_name}")


@contextmanager
def _source(args: argparse.Namespace, db: Database | None) -> Iterator[ConfigSource]:
    """The data/ tree with --data-dir, else the database."""
    if db is None:
        yield FileSource(args.data_dir)
    else:
        with db.session() as session:
            yield DbSource(session)


def _load(args: argparse.Namespace, db: Database | None, scenario: str | None = None) -> SimulationInput:
    with _source(args, db) as source:
        return load_simulation_input(source, args.profile, scenario or args.scenario)


def _mc(db: Database | None, sim: SimulationInput, args: argparse.Namespace) -> MonteCarloResult:
    """A Monte Carlo run of `sim`: recorded (or fetched from the run cache) with the database, else just run."""
    if db is None:
        return run_monte_carlo(sim, args.sims, args.seed, workers=args.workers, progress=_progress_for(sim))
    info, mc, _ = runs.monte_carlo(
        db,
        sim,
        args.sims,
        args.seed,
        args.runs_dir,
        workers=args.workers,
        progress=_progress_for(sim),
        use_cache=not args.no_cache,
    )
    if info.cached:
        print(
            f"{sim.scenario_name}: stored run #{info.id} from {when(info.created_at)} has the same inputs, engine, "
            "seed, and paths (--no-cache reruns it)"
        )
    else:
        print(
            f"{sim.scenario_name}: run #{info.id}, {mc.n_sims:,} paths in {mc.elapsed_seconds:.1f} s -> {info.output_dir}"
        )
    return mc


def _monte_carlo(db: Database | None, args: argparse.Namespace) -> int:
    sim = _load(args, db)
    goals = _goals(sim, args)
    if db is None:
        mc = _mc(db, sim, args)
        summary = stats.summarize(mc, sim, goals)
        print(report.format_summary(summary))
        print(f"\n{mc.n_sims:,} paths in {mc.elapsed_seconds:.1f} s")
        out = args.out or args.runs_dir / args.profile / args.scenario / "mc"
        for path in report.write_outputs(mc, summary, out):
            print(f"wrote {path}")
        return 0
    info, mc, summary = runs.monte_carlo(
        db,
        sim,
        args.sims,
        args.seed,
        args.runs_dir,
        goals=goals,
        out=args.out,
        workers=args.workers,
        progress=_progress_for(sim),
        use_cache=not args.no_cache,
    )
    print(report.format_summary(summary))
    if info.cached:
        print(
            f"\nStored run #{info.id} from {when(info.created_at)}: same inputs, engine, seed, and paths "
            "(--no-cache reruns it)."
        )
    else:
        print(f"\nRun #{info.id}: {mc.n_sims:,} paths in {mc.elapsed_seconds:.1f} s")
    print(f"outputs in {args.out or info.output_dir}")
    print(f"drill down on its inputs: northward run --from-run {info.id} --path N")
    return 0


def _stats(db: Database | None, args: argparse.Namespace) -> int:
    if args.run.isdigit():
        if db is None:
            print("stats of a run number needs the database (drop --data-dir)", file=sys.stderr)
            return 1
        info, sim = runs.load_run_input(db, int(args.run))  # goals as the run saw them, from its pinned revisions
        if info.kind != runs.MONTE_CARLO or info.output_dir is None:
            print(f"run #{info.id} isn't a completed Monte Carlo run", file=sys.stderr)
            return 1
        if not (info.output_dir / "telemetry.npz").is_file():
            print(f"run #{info.id}'s telemetry is missing from {info.output_dir}", file=sys.stderr)
            return 1
        mc = telemetry.load(info.output_dir / "telemetry.npz")
    else:
        path = Path(args.run)
        mc = telemetry.load(path / "telemetry.npz" if path.is_dir() else path)
        with _source(args, db) as source:
            sim = load_simulation_input(source, mc.profile, mc.scenario)
    summary = stats.summarize(mc, sim, _goals(sim, args), with_bands=not args.json)
    print(json.dumps(summary, indent=1) if args.json else report.format_summary(summary))
    return 0


def _compare(db: Database | None, args: argparse.Namespace) -> int:
    if len(args.scenario) < 2:
        print("compare needs at least two --scenario options", file=sys.stderr)
        return 1
    with _source(args, db) as source:
        sims = [load_simulation_input(source, args.profile, name) for name in args.scenario]
    pairs = [(_mc(db, sim, args), sim) for sim in sims]
    comparison = stats.compare(pairs, _goals(sims[0], args))
    print(report.format_comparison(comparison))
    goals = {sim.profile.goals for sim in sims}
    if len(goals) > 1:
        print(f"note: the scenarios override goals differently; all were measured with {args.scenario[0]!r}'s goals")
    out = args.out or args.runs_dir / args.profile / "compare" / "__".join(args.scenario)
    out.mkdir(parents=True, exist_ok=True)
    (out / "comparison.json").write_text(json.dumps(comparison, indent=1))
    print(f"wrote {out / 'comparison.json'}")
    return 0


def _run(db: Database | None, args: argparse.Namespace) -> int:
    seed = DEFAULT_SEED if args.seed is None else args.seed
    if args.from_run is not None:
        if db is None or args.path is None:
            print("--from-run needs the database (no --data-dir) and --path", file=sys.stderr)
            return 1
        info, sim = runs.load_run_input(db, args.from_run)
        seed = info.seed if args.seed is None and info.seed is not None else seed
        result = simulate_path(sim, seed, args.path, record=not args.no_ledger)
        _print_run_summary(result, f"Monte Carlo path {args.path} of run #{info.id} (seed {seed})")
        out = args.out or args.runs_dir / str(info.id) / f"path-{args.path}"
    else:
        sim = _load(args, db)
        if args.path is not None:
            result = simulate_path(sim, seed, args.path, record=not args.no_ledger)
            _print_run_summary(result, f"Monte Carlo path {args.path} (seed {seed})")
            out = args.out or args.runs_dir / args.profile / args.scenario / f"path-{args.path}-seed-{seed}"
        elif db is None:
            result = simulate(sim, record=not args.no_ledger)
            _print_run_summary(result)
            out = args.out or args.runs_dir / args.profile / args.scenario
        else:
            info, result, written = runs.deterministic(
                db, sim, args.runs_dir, out=args.out, record_ledger=not args.no_ledger, fmt=args.format
            )
            _print_run_summary(result, f"Deterministic run #{info.id}")
            for path in written:
                print(f"wrote {path}")
            return 0
    for path in write_result(result, out, args.format):
        print(f"wrote {path}")
    return 0


def _serve(args: argparse.Namespace) -> int:
    import uvicorn

    from northward.api.app import create_app

    db = Database(args.db)
    db.check_schema()
    if args.host not in ("127.0.0.1", "localhost", "::1"):
        print(f"warning: the API has no authentication, and {args.host} may be reachable from other machines")
    ui_dir = args.ui_dir if (args.ui_dir / "index.html").is_file() else None
    if ui_dir is None:
        print(f"note: no built frontend in {args.ui_dir} (make ui); serving the API only")
    print(f"Northward: http://{args.host}:{args.port}/" + ("" if ui_dir else "docs"))
    uvicorn.run(create_app(db, args.runs_dir, args.workers, ui_dir=ui_dir), host=args.host, port=args.port)
    return 0


def _openapi(args: argparse.Namespace) -> int:
    from northward.api.app import create_app

    spec = json.dumps(create_app(Database(args.db)).openapi(), indent=1)
    if args.out is None:
        print(spec)
    else:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(spec + "\n")
        print(f"wrote {args.out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="northward", description="Northward: retirement planning with Monte Carlo simulation."
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        help="Read the rules/ and profiles/ files under this directory instead of the database.",
    )
    parser.add_argument("--db", help=f"Database URL (default: ${URL_ENV}, else {DEFAULT_URL}).")
    parser.add_argument(
        "--runs-dir", type=Path, default=Path("var/runs"), help="Where run outputs go (default: var/runs)."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate", help="Validate every profile and scenario (or the ones named).")
    validate.add_argument("--profile")
    validate.add_argument("--scenario")

    show = subparsers.add_parser("show-config", help="Load one profile + scenario and print a summary.")
    show.add_argument("--profile", default="default")
    show.add_argument("--scenario", default="base")

    run = subparsers.add_parser(
        "run", help="Run a deterministic simulation, or one Monte Carlo path (--path), and write year-by-year results."
    )
    run.add_argument("--profile", default="default")
    run.add_argument("--scenario", default="base")
    run.add_argument(
        "--path", type=int, help="Re-run this Monte Carlo path (with --seed) instead of the deterministic run."
    )
    run.add_argument("--seed", type=int, help=f"Monte Carlo seed for --path (default: the run's, else {DEFAULT_SEED}).")
    run.add_argument("--from-run", type=int, help="With --path: re-run a path of this stored run, on its inputs.")
    run.add_argument(
        "--out", type=Path, help="Output directory (default: var/runs/<run id>, or <profile>/<scenario> with files)."
    )
    run.add_argument("--format", choices=("csv", "json"), default="csv")
    run.add_argument("--no-ledger", action="store_true", help="Skip the transaction ledger.")

    def mc_options(p: argparse.ArgumentParser) -> None:
        p.add_argument("--sims", type=int, default=DEFAULT_SIMS, help=f"Number of paths (default {DEFAULT_SIMS}).")
        p.add_argument("--seed", type=int, default=DEFAULT_SEED, help=f"Random seed (default {DEFAULT_SEED}).")
        p.add_argument("--workers", type=int, help="Worker processes (default: one per CPU).")
        p.add_argument("--no-cache", action="store_true", help="Rerun even if a stored run has identical inputs.")
        _add_goal_options(p)

    mc = subparsers.add_parser("mc", help="Run a Monte Carlo simulation and write telemetry and statistics.")
    mc.add_argument("--profile", default="default")
    mc.add_argument("--scenario", default="base")
    mc.add_argument(
        "--out", type=Path, help="Output directory (default: var/runs/<run id>, or <profile>/<scenario>/mc with files)."
    )
    mc_options(mc)

    stats_cmd = subparsers.add_parser("stats", help="Recompute statistics from a saved Monte Carlo run.")
    stats_cmd.add_argument("run", help="A stored run's number, or a run directory (or its telemetry.npz).")
    stats_cmd.add_argument("--json", action="store_true", help="Print the summary as JSON.")
    _add_goal_options(stats_cmd)

    cmp = subparsers.add_parser("compare", help="Compare scenarios on the same Monte Carlo draws.")
    cmp.add_argument("--profile", default="default")
    cmp.add_argument(
        "--scenario", action="append", required=True, help="Repeat for each scenario; the first is the base."
    )
    cmp.add_argument("--out", type=Path, help="Output directory (default: var/runs/<profile>/compare/<a>__<b>).")
    mc_options(cmp)

    add_db_commands(subparsers)
    add_runs_commands(subparsers)

    serve = subparsers.add_parser("serve", help="Run the HTTP API and web UI on the database.")
    serve.add_argument("--host", default="127.0.0.1", help="Interface to listen on (default: localhost only).")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--workers", type=int, help="Monte Carlo worker processes (default: one per CPU).")
    serve.add_argument(
        "--ui-dir", type=Path, default=Path("frontend/dist"), help="Built frontend to serve (default: frontend/dist)."
    )

    openapi = subparsers.add_parser("openapi", help="Write the API's OpenAPI schema (for client type generation).")
    openapi.add_argument("out", nargs="?", type=Path, help="Output file (default: print it).")

    args = parser.parse_args(argv)
    try:
        if args.command == "db":
            return db_command(Database(args.db), args)
        if args.command == "runs":
            return runs_command(Database(args.db), args, _progress_for)
        if args.command == "serve":
            return _serve(args)
        if args.command == "openapi":
            return _openapi(args)
        db = None
        if args.data_dir is None:
            db = Database(args.db)
            db.check_schema()
        if args.command == "validate":
            with _source(args, db) as source:
                return _validate(source, args.profile, args.scenario)
        if args.command == "show-config":
            _show_config(_load(args, db))
            return 0
        if args.command == "mc":
            return _monte_carlo(db, args)
        if args.command == "stats":
            return _stats(db, args)
        if args.command == "compare":
            return _compare(db, args)
        return _run(db, args)
    except ConfigError as error:
        print(error, file=sys.stderr)
        return 1
    except (DatabaseError, NotFound) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
