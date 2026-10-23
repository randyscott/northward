"""Simulations and stored runs: deterministic runs (synchronous), Monte Carlo jobs, results, drill-down, comparison.

A Monte Carlo request is answered by an identical completed run when there is one (`cached: true`, 200), else by an
identical run already queued or running, else by a newly queued run (202); poll `GET /api/runs/{id}`.
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Query, Response

from northward.api import convert, schemas
from northward.api.deps import DatabaseDep, JobsDep, RunsDirDep
from northward.config.loader import SimulationInput, load_simulation_input
from northward.engine.export import ledger_rows, year_rows
from northward.engine.results import SimulationResult
from northward.engine.simulate import simulate
from northward.montecarlo import stats, telemetry
from northward.montecarlo.runner import simulate_path
from northward.montecarlo.telemetry import BUCKETS, MonteCarloResult, telemetry_rows
from northward.persistence import runs
from northward.persistence.db import Database
from northward.persistence.repositories import Conflict
from northward.persistence.runs import RunInfo
from northward.persistence.source import DbSource

router = APIRouter(prefix="/api")


def _load(db: Database, profile: str, scenario: str) -> SimulationInput:
    with db.session() as session:
        return load_simulation_input(DbSource(session), profile, scenario)


@functools.lru_cache(maxsize=4)
def _telemetry(path: str, modified: float) -> MonteCarloResult:
    """Telemetry of recently viewed runs, kept in memory (10,000 paths are ~40 MB and take a moment to load)."""
    return telemetry.load(Path(path))


def _results_input(db: Database, run_id: int) -> tuple[RunInfo, SimulationInput, MonteCarloResult]:
    info, sim = runs.load_run_input(db, run_id)
    path = runs.telemetry_path(info)
    return info, sim, _telemetry(str(path), path.stat().st_mtime)


@router.post("/simulate/deterministic", response_model=schemas.DeterministicOut, tags=["simulate"])
def simulate_deterministic(
    db: DatabaseDep, runs_dir: RunsDirDep, body: schemas.DeterministicRequest
) -> schemas.DeterministicOut:
    """Run (and record) the deterministic simulation; returns the year-by-year table and the ledger."""
    sim = _load(db, body.profile, body.scenario)
    info, result, _ = runs.deterministic(db, sim, runs_dir, record_ledger=body.ledger)
    return schemas.DeterministicOut(
        run=convert.run_out(info),
        years=convert.json_safe(year_rows(result)),
        ledger=convert.json_safe(ledger_rows(result)),
        warnings=list(result.warnings),
    )


@router.post(
    "/simulate/montecarlo",
    response_model=schemas.RunOut,
    status_code=202,
    responses={200: {"model": schemas.RunOut, "description": "An identical completed run (`cached: true`)."}},
    tags=["simulate"],
)
def simulate_monte_carlo(
    db: DatabaseDep, jobs: JobsDep, body: schemas.MonteCarloRequest, response: Response
) -> schemas.RunOut:
    sim = _load(db, body.profile, body.scenario)
    info = jobs.submit(sim, body.n_sims, body.seed, body.use_cache)
    if info.status == "complete":
        response.status_code = 200
    return convert.run_out(info, jobs.progress(info.id))


@router.get("/runs", response_model=list[schemas.RunOut], tags=["runs"])
def list_runs(
    db: DatabaseDep,
    jobs: JobsDep,
    profile: str | None = None,
    scenario: str | None = None,
    kind: str | None = None,
    status: str | None = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 50,
) -> list[schemas.RunOut]:
    """Run history, newest first."""
    found = runs.list_runs(db, profile, scenario, limit, kind, status)
    return [convert.run_out(info, jobs.progress(info.id)) for info in found]


@router.get("/runs/{run_id}", response_model=schemas.RunOut, tags=["runs"])
def get_run(db: DatabaseDep, jobs: JobsDep, run_id: int) -> schemas.RunOut:
    return convert.run_out(runs.get_run(db, run_id), jobs.progress(run_id))


@router.post("/runs/{run_id}/cancel", response_model=schemas.RunOut, tags=["runs"])
def cancel_run(jobs: JobsDep, run_id: int) -> schemas.RunOut:
    """Cancel a queued or running Monte Carlo run (it's recorded as failed: cancelled)."""
    return convert.run_out(jobs.cancel(run_id))


@router.get("/runs/{run_id}/results", tags=["runs"])
def get_results(
    db: DatabaseDep,
    run_id: int,
    bands: bool = True,
    buckets: Annotated[
        list[str] | None, Query(description=f"Bands of only these buckets ({', '.join(BUCKETS)}).")
    ] = None,
    allow_shortfall: bool = False,
    shortfall_tolerance: Annotated[float | None, Query(ge=0)] = None,
    liquidity_floor: Annotated[float | None, Query(ge=0, description="Today's dollars; 0 turns the floor off.")] = None,
    heirs_tax_rate: Annotated[float | None, Query(ge=0, le=1)] = None,
) -> dict[str, Any]:
    """A completed Monte Carlo run's statistics and percentile bands, under the profile's goals (as the run saw them)
    with any one-off overrides."""
    if buckets and (unknown := sorted(set(buckets) - set(BUCKETS))):
        raise ValueError(f"unknown buckets: {', '.join(unknown)}")
    _, sim, mc = _results_input(db, run_id)
    goals = sim.profile.goals.with_overrides(allow_shortfall, shortfall_tolerance, liquidity_floor, heirs_tax_rate)
    summary = stats.summarize(mc, sim, goals, with_bands=bands)
    if bands and buckets:
        summary["bands"] = {name: summary["bands"][name] for name in buckets}
    return convert.json_safe(summary)


def _years(run_id: int, result: SimulationResult, ledger: bool) -> dict[str, Any]:
    rows = telemetry_rows(result)
    return dict(
        run_id=run_id,
        death_ages=result.death_ages,
        years=convert.json_safe(year_rows(result)),
        ledger=convert.json_safe(ledger_rows(result)) if ledger else [],
        warnings=list(result.warnings),
        buckets={name: convert.json_safe(rows[:, j].tolist()) for j, name in enumerate(BUCKETS)},
    )


@router.get("/runs/{run_id}/years", response_model=schemas.YearsOut, tags=["runs"])
def get_years(db: DatabaseDep, run_id: int, ledger: bool = True) -> schemas.YearsOut:
    """A deterministic run's year table and ledger, recomputed from its pinned inputs (exactly as it ran)."""
    info, sim = runs.load_run_input(db, run_id)
    if info.kind != runs.DETERMINISTIC:
        raise Conflict(f"run {run_id} is a Monte Carlo run; see its results and paths instead")
    return schemas.YearsOut(**_years(run_id, simulate(sim, record=ledger), ledger))


@router.get("/runs/{run_id}/paths/{path}", response_model=schemas.PathOut, tags=["runs"])
def get_path(db: DatabaseDep, run_id: int, path: int, ledger: bool = True) -> schemas.PathOut:
    """Re-run one path of a Monte Carlo run on its pinned inputs, with the ledger on."""
    info, sim = runs.load_run_input(db, run_id)
    if info.kind != runs.MONTE_CARLO or info.seed is None or info.n_sims is None:
        raise Conflict(f"run {run_id} is a {info.kind} run; only Monte Carlo runs have paths")
    if not 0 <= path < info.n_sims:
        raise ValueError(f"path must be between 0 and {info.n_sims - 1}")
    result = simulate_path(sim, info.seed, path, record=ledger)
    return schemas.PathOut(**_years(run_id, result, ledger), path=path, seed=info.seed)


@router.post(
    "/compare",
    response_model=schemas.CompareOut,
    responses={202: {"model": schemas.CompareOut, "description": "Some runs are still queued or running."}},
    tags=["simulate"],
)
def compare(db: DatabaseDep, jobs: JobsDep, body: schemas.CompareRequest, response: Response) -> schemas.CompareOut:
    """Compare scenarios on the same Monte Carlo draws. Missing runs are queued (202); POST the same request again
    once they finish (identical requests share runs, so polling is cheap)."""
    sims = [_load(db, body.profile, name) for name in body.scenarios]
    infos = [jobs.submit(sim, body.n_sims, body.seed) for sim in sims]
    out = [convert.run_out(info, jobs.progress(info.id)) for info in infos]
    if any(info.status == "failed" for info in infos):
        failed = next(info for info in infos if info.status == "failed")
        raise Conflict(f"run {failed.id} ({failed.scenario}) failed: {failed.error}")
    if any(info.status != "complete" for info in infos):
        response.status_code = 202
        return schemas.CompareOut(status="pending", runs=out, comparison=None)
    pairs = [(_results_input(db, info.id)[2], sim) for info, sim in zip(infos, sims, strict=True)]
    goals = sims[0].profile.goals.with_overrides(
        body.allow_shortfall, body.shortfall_tolerance, body.liquidity_floor, body.heirs_tax_rate
    )
    return schemas.CompareOut(status="complete", runs=out, comparison=convert.json_safe(stats.compare(pairs, goals)))
