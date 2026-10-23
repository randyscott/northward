"""Recorded runs: simulate from database inputs, store the run in `runs`, and reuse a stored identical run.

A Monte Carlo run is cached by (scenario, input hash, engine version, seed, paths): asking again for the same thing
returns the stored telemetry instead of recomputing it. Every run pins the revisions it read, so `load_run_input`
rebuilds exactly its inputs even after the documents have been edited.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from northward.config.goals import GoalsDoc
from northward.config.loader import SimulationInput, load_simulation_input
from northward.engine.export import write_result
from northward.engine.results import SimulationResult
from northward.engine.simulate import simulate
from northward.fingerprint import engine_version
from northward.montecarlo import report, stats, telemetry
from northward.montecarlo.runner import run_monte_carlo
from northward.montecarlo.telemetry import MonteCarloResult
from northward.persistence.db import Database
from northward.persistence.models import Run, Scenario, utc_now
from northward.persistence.repositories import Conflict, NotFound, ProfileRepo, RunRepo, ScenarioRepo
from northward.persistence.source import revision_key

MONTE_CARLO = "monte_carlo"
DETERMINISTIC = "deterministic"
SHORTFALL_TOLERANCE = 1.0


@dataclass(frozen=True)
class RunInfo:
    """A stored run, detached from the database session."""

    id: int
    kind: str
    profile: str
    scenario: str
    seed: int | None
    n_sims: int | None
    engine_version: str
    input_hash: str
    status: str
    output_dir: Path | None
    summary: dict[str, Any] | None
    error: str | None
    created_at: datetime
    finished_at: datetime | None
    elapsed_seconds: float | None
    revisions: tuple[tuple[str, int], ...]  # (document, revision number), e.g. ("profiles/x/accounts.yaml", 3)
    cached: bool = False  # returned from the cache rather than run now

    @classmethod
    def of(cls, run: Run, cached: bool = False) -> RunInfo:
        revisions = sorted((_document_label(r), r.revision) for r in run.revisions)
        return cls(
            id=run.id,
            kind=run.kind,
            profile=run.scenario.profile.name,
            scenario=run.scenario.name,
            seed=run.seed,
            n_sims=run.n_sims,
            engine_version=run.engine_version,
            input_hash=run.input_hash,
            status=run.status,
            output_dir=Path(run.output_dir) if run.output_dir else None,
            summary=run.summary,
            error=run.error,
            created_at=as_utc(run.created_at),
            finished_at=None if run.finished_at is None else as_utc(run.finished_at),
            elapsed_seconds=run.elapsed_seconds,
            revisions=tuple(revisions),
            cached=cached,
        )


def as_utc(moment: datetime) -> datetime:
    """Stored times are UTC; SQLite returns them without a time zone."""
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _document_label(revision: Any) -> str:
    scope, a, b = revision_key(revision)
    if scope == "rules":
        return f"rules[{revision.document.rule_set.name}]/{a}"
    return f"{a}/{b}" if scope == "profile" else f"{a}/scenarios/{b}"


def _scenario(db_session: Any, sim: SimulationInput) -> Scenario:
    profile = ProfileRepo(db_session).get(sim.profile_name, include_archived=True)
    return ScenarioRepo(db_session).get(profile, sim.scenario_name, include_archived=True)


class RunCancelled(Exception):
    """Raised (e.g. from a progress callback) to stop a run for good; it's recorded as failed."""


class RunInterrupted(Exception):
    """Raised to stop a run that should run again later (the server is stopping); it goes back to the queue."""


def _start(
    db: Database, sim: SimulationInput, kind: str, seed: int | None, n_sims: int | None, status: str = "running"
) -> RunInfo:
    assert sim.snapshot is not None, "recorded runs need inputs built by load_simulation_input"
    with db.session() as session:
        repo = RunRepo(session)
        return RunInfo.of(
            repo.start(_scenario(session, sim), kind, sim.snapshot, engine_version(), seed, n_sims, status)
        )


def _set_status(db: Database, run_id: int, status: str) -> None:
    with db.session() as session:
        run = RunRepo(session).get(run_id)
        run.status, run.pid = status, os.getpid() if status == "running" else None


def _finish(db: Database, run_id: int, summary: dict[str, Any], output_dir: Path, elapsed: float) -> RunInfo:
    with db.session() as session:
        run = RunRepo(session).get(run_id)
        # Stored as JSON, so keep exactly what reading it back gives (e.g. integer keys become strings).
        run.summary = json.loads(json.dumps(summary))
        run.status, run.output_dir = "complete", str(output_dir.resolve())
        run.finished_at, run.elapsed_seconds = utc_now(), elapsed
        session.flush()
        return RunInfo.of(run)


def _fail(db: Database, run_id: int, error: BaseException | str) -> None:
    message = error if isinstance(error, str) else f"{type(error).__name__}: {error}"
    with db.session() as session:
        run = RunRepo(session).get(run_id)
        run.status, run.error, run.finished_at = "failed", message, utc_now()


def find_cached(
    db: Database, sim: SimulationInput, n_sims: int, seed: int, statuses: tuple[str, ...] = ("complete",)
) -> RunInfo | None:
    """The newest Monte Carlo run of `sim` with the same inputs, engine, seed, and paths, among runs in `statuses`
    (a completed one only if its telemetry still exists)."""
    assert sim.snapshot is not None
    with db.session() as session:
        key = (sim.snapshot.content_hash(), engine_version(), seed, n_sims)
        for run in RunRepo(session).cached(_scenario(session, sim), MONTE_CARLO, *key, statuses=statuses):
            if run.status != "complete" or (Path(run.output_dir or "") / "telemetry.npz").is_file():
                return RunInfo.of(run, cached=run.status == "complete")
    return None


def queue_monte_carlo(db: Database, sim: SimulationInput, n_sims: int, seed: int) -> RunInfo:
    """Record a Monte Carlo run as queued, for `execute_monte_carlo` to run later (e.g. by a job runner)."""
    return _start(db, sim, MONTE_CARLO, seed, n_sims, status="queued")


def execute_monte_carlo(
    db: Database,
    run_id: int,
    sim: SimulationInput,
    runs_dir: Path,
    *,
    goals: GoalsDoc | None = None,
    out: Path | None = None,
    workers: int | None = None,
    progress: Callable[[int, int], None] | None = None,
    mp_context: str | None = None,
) -> tuple[RunInfo, MonteCarloResult, dict[str, Any]]:
    """Run recorded run `run_id` (queued or started) on `sim`. `progress` may raise RunCancelled or RunInterrupted."""
    info = get_run(db, run_id)
    assert info.n_sims is not None and info.seed is not None
    _set_status(db, run_id, "running")
    output = out or runs_dir / str(run_id)
    try:
        mc = run_monte_carlo(sim, info.n_sims, info.seed, workers=workers, progress=progress, mp_context=mp_context)
        summary = stats.summarize(mc, sim, goals or sim.profile.goals)
        report.write_outputs(mc, summary, output)
    except RunInterrupted:
        _set_status(db, run_id, "queued")
        raise
    except BaseException as error:  # cancelled and interrupted (Ctrl+C) runs too
        _fail(db, run_id, "cancelled" if isinstance(error, RunCancelled) else error)
        raise
    stored = {k: v for k, v in summary.items() if k != "bands"}
    return _finish(db, run_id, stored, output, mc.elapsed_seconds), mc, summary


def monte_carlo(
    db: Database,
    sim: SimulationInput,
    n_sims: int,
    seed: int,
    runs_dir: Path,
    *,
    goals: GoalsDoc | None = None,
    out: Path | None = None,
    workers: int | None = None,
    progress: Callable[[int, int], None] | None = None,
    use_cache: bool = True,
) -> tuple[RunInfo, MonteCarloResult, dict[str, Any]]:
    """Run (or fetch from the cache) a Monte Carlo simulation of `sim`, which must come from a `DbSource`.
    Outputs go to `out`, else `runs_dir/<run id>/`. Returns the run, its telemetry, and its summary under `goals`
    (default: the profile's)."""
    goals = goals or sim.profile.goals
    cached = find_cached(db, sim, n_sims, seed) if use_cache else None
    if cached is not None:
        mc = telemetry.load(Path(cached.output_dir or "") / "telemetry.npz")
        summary = stats.summarize(mc, sim, goals)
        if out is not None:
            report.write_outputs(mc, summary, out)
        return cached, mc, summary
    info = _start(db, sim, MONTE_CARLO, seed, n_sims)
    return execute_monte_carlo(db, info.id, sim, runs_dir, goals=goals, out=out, workers=workers, progress=progress)


def cancel_queued(db: Database, run_id: int) -> RunInfo:
    """Record a queued run as cancelled (a running one is stopped by its runner)."""
    with db.session() as session:
        run = RunRepo(session).get(run_id)
        if run.status != "queued":
            raise Conflict(f"run {run_id} is {run.status}, not queued")
        run.status, run.error, run.finished_at = "failed", "cancelled", utc_now()
        session.flush()
        return RunInfo.of(run)


def _alive(pid: int | None) -> bool:
    if pid is None or pid == os.getpid():  # our own pid on a run we didn't start: a reused pid (e.g. in a container)
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def reconcile(db: Database) -> list[int]:
    """At startup: mark running runs whose process is gone as failed, and return the queued runs, oldest first."""
    queued = []
    with db.session() as session:
        for run in RunRepo(session).unfinished():
            if run.status == "queued":
                queued.append(run.id)
            elif not _alive(run.pid):
                run.status, run.finished_at = "failed", utc_now()
                run.error = "interrupted: the process running it stopped before it finished"
    return queued


def deterministic_summary(result: SimulationResult) -> dict[str, Any]:
    first, last = result.years[0], result.years[-1]
    return {
        "profile": result.profile,
        "scenario": result.scenario,
        "start_year": first.year,
        "end_year": last.year,
        "final_net_worth": last.net_worth,
        "final_net_worth_real": last.net_worth / last.price_level,
        "lifetime_taxes": sum(state.flows.total_taxes for state in result.years),
        "shortfall_years": [s.year for s in result.years if s.flows.shortfall > SHORTFALL_TOLERANCE],
        "warnings": list(result.warnings),
    }


def deterministic(
    db: Database,
    sim: SimulationInput,
    runs_dir: Path,
    *,
    out: Path | None = None,
    record_ledger: bool = True,
    fmt: Literal["csv", "json"] = "csv",
) -> tuple[RunInfo, SimulationResult, list[Path]]:
    """Run and record the deterministic simulation of `sim`; results go to `out`, else `runs_dir/<run id>/`."""
    run_id = _start(db, sim, DETERMINISTIC, None, None).id
    output = out or runs_dir / str(run_id)
    started = time.perf_counter()
    try:
        result = simulate(sim, record=record_ledger)
        written = write_result(result, output, fmt)
    except BaseException as error:
        _fail(db, run_id, error)
        raise
    elapsed = time.perf_counter() - started
    return _finish(db, run_id, deterministic_summary(result), output, elapsed), result, written


def get_run(db: Database, run_id: int) -> RunInfo:
    with db.session() as session:
        return RunInfo.of(RunRepo(session).get(run_id))


def list_runs(
    db: Database,
    profile: str | None = None,
    scenario: str | None = None,
    limit: int = 50,
    kind: str | None = None,
    status: str | None = None,
) -> list[RunInfo]:
    with db.session() as session:
        return [RunInfo.of(run) for run in RunRepo(session).list(profile, scenario, limit, kind, status)]


def load_run_input(db: Database, run_id: int) -> tuple[RunInfo, SimulationInput]:
    """A stored run and exactly the inputs it ran on (its pinned revisions)."""
    with db.session() as session:
        repo = RunRepo(session)
        run = repo.get(run_id)
        sim = load_simulation_input(repo.source(run), run.scenario.profile.name, run.scenario.name)
        return RunInfo.of(run), sim


def telemetry_path(info: RunInfo) -> Path:
    """Where a completed Monte Carlo run's telemetry is (Conflict or NotFound if it has none)."""
    if info.kind != MONTE_CARLO:
        raise Conflict(f"run {info.id} is a {info.kind} run, not a Monte Carlo run")
    if info.status != "complete" or info.output_dir is None:
        raise Conflict(f"run {info.id} is {info.status}; it has no results yet")
    path = info.output_dir / "telemetry.npz"
    if not path.is_file():
        raise NotFound(f"run {info.id}'s telemetry is missing from {info.output_dir}")
    return path


def load_monte_carlo(db: Database, run_id: int) -> tuple[RunInfo, SimulationInput, MonteCarloResult]:
    """A completed Monte Carlo run, its pinned inputs, and its telemetry."""
    info, sim = load_run_input(db, run_id)
    return info, sim, telemetry.load(telemetry_path(info))


def remove_outputs(outputs: list[str], runs_dir: Path) -> list[Path]:
    """Delete purged runs' output folders that are inside `runs_dir`; returns the ones left alone (outside it)."""
    root, kept = runs_dir.resolve(), []
    for output in outputs:
        path = Path(output)
        if path.is_dir() and path.resolve().is_relative_to(root):
            shutil.rmtree(path)
        elif path.exists():
            kept.append(path)
    return kept
