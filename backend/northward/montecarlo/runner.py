"""Run many simulated paths across a process pool (D2): the ledger is off, and each path yields one telemetry slab.

`simulate_path` re-runs any single path with the ledger on; it gets exactly the draws the Monte Carlo run used.
"""

from __future__ import annotations

import multiprocessing
import os
import time
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor, as_completed

import numpy as np

from northward.config.loader import SimulationInput
from northward.config.rules.market import FACTORS
from northward.engine.market import MarketPath
from northward.engine.results import SimulationResult
from northward.engine.simulate import simulate
from northward.engine.timeline import Timeline
from northward.fingerprint import engine_version
from northward.lifecycle.mortality import is_sampled, sampled_death_ages
from northward.montecarlo.samplers import death_uniforms, market_sampler
from northward.montecarlo.telemetry import BUCKETS, MonteCarloResult, telemetry_rows

Progress = Callable[[int, int], None]  # (paths done, total)


class PathFactory:
    """Builds the inputs of path `index` for one scenario and seed: its death ages (when lifespans are sampled) and a
    market path covering its horizon."""

    def __init__(self, sim: SimulationInput, seed: int):
        self.sim = sim
        self.seed = seed
        self.sampler = market_sampler(sim)
        self.sampled_mortality = is_sampled(sim)
        self.horizon = len(Timeline(sim).years)  # when lifespans aren't sampled, every path has the same horizon

    def death_ages(self, index: int) -> dict[str, float] | None:
        if not self.sampled_mortality:
            return None
        members = len(self.sim.profile.household.members)
        return sampled_death_ages(self.sim, death_uniforms(self.seed, index, members))

    def years(self, death_ages: dict[str, float] | None) -> int:
        return self.horizon if death_ages is None else len(Timeline(self.sim, death_ages).years)

    def market(self, index: int, years: int) -> MarketPath:
        returns = self.sampler.sample(self.seed, index, years)
        start = self.sim.scenario.horizon.start_year
        return MarketPath(start, *(np.ascontiguousarray(returns[:, j]) for j in range(len(FACTORS))))

    def run(self, index: int, record: bool) -> SimulationResult:
        death_ages = self.death_ages(index)
        return simulate(self.sim, self.market(index, self.years(death_ages)), record, death_ages)


def simulate_path(sim: SimulationInput, seed: int, index: int, record: bool = True) -> SimulationResult:
    """Re-run path `index` of a Monte Carlo run (same seed), by default with the ledger on."""
    return PathFactory(sim, seed).run(index, record)


_factory: PathFactory | None = None  # per worker process


def _init_worker(sim: SimulationInput, seed: int) -> None:
    global _factory
    _factory = PathFactory(sim, seed)


def _run_chunk(start: int, stop: int, years: int) -> tuple[int, np.ndarray, np.ndarray, np.ndarray]:
    assert _factory is not None
    members = [m.id for m in _factory.sim.profile.household.members]
    telemetry = np.full((stop - start, years, len(BUCKETS)), np.nan)
    market = np.full((stop - start, years, len(FACTORS)), np.nan)
    deaths = np.full((stop - start, len(members)), np.nan)
    for k, index in enumerate(range(start, stop)):
        result = _factory.run(index, record=False)
        rows = telemetry_rows(result)
        telemetry[k, : len(rows)] = rows
        path = _factory.market(index, len(rows))
        market[k, : len(rows)] = np.column_stack([getattr(path, f) for f in FACTORS])
        for j, member in enumerate(members):
            deaths[k, j] = result.death_ages.get(member, np.nan)
    return start, telemetry, market, deaths


def run_monte_carlo(
    sim: SimulationInput,
    n_sims: int,
    seed: int,
    workers: int | None = None,
    chunk_size: int | None = None,
    progress: Progress | None = None,
    mp_context: str | None = None,
) -> MonteCarloResult:
    """Simulate paths `0 .. n_sims-1`. Results are identical for any `workers` or `chunk_size`.

    `mp_context` picks the worker processes' start method (default: the platform's). A server should use "spawn",
    since forking a process that runs threads can deadlock. `progress` may raise to stop the run."""
    if n_sims < 1:
        raise ValueError("n_sims must be at least 1")
    started = time.perf_counter()
    factory = PathFactory(sim, seed)
    years = max((factory.years(factory.death_ages(i)) for i in range(n_sims)), default=0)
    workers = max(1, min(workers or os.cpu_count() or 1, n_sims))
    chunk_size = chunk_size or max(1, min(250, -(-n_sims // (workers * 8))))
    chunks = [(start, min(start + chunk_size, n_sims)) for start in range(0, n_sims, chunk_size)]

    members = tuple(m.id for m in sim.profile.household.members)
    telemetry = np.empty((n_sims, years, len(BUCKETS)))
    market = np.empty((n_sims, years, len(FACTORS)))
    deaths = np.empty((n_sims, len(members)))
    done = 0

    def collect(part: tuple[int, np.ndarray, np.ndarray, np.ndarray]) -> None:
        nonlocal done
        start, t, m, d = part
        telemetry[start : start + len(t)], market[start : start + len(t)], deaths[start : start + len(t)] = t, m, d
        done += len(t)
        if progress:
            progress(done, n_sims)

    if workers == 1:
        _init_worker(sim, seed)
        for start, stop in chunks:
            collect(_run_chunk(start, stop, years))
    else:
        context = multiprocessing.get_context(mp_context) if mp_context else None
        with ProcessPoolExecutor(
            max_workers=workers, mp_context=context, initializer=_init_worker, initargs=(sim, seed)
        ) as pool:
            futures = [pool.submit(_run_chunk, start, stop, years) for start, stop in chunks]
            try:
                for future in as_completed(futures):
                    collect(future.result())
            except BaseException:  # stopped (e.g. by `progress`, or Ctrl+C): don't run the remaining chunks
                pool.shutdown(wait=True, cancel_futures=True)
                raise

    return MonteCarloResult(
        profile=sim.profile_name,
        scenario=sim.scenario_name,
        seed=seed,
        preset=sim.market.id,
        sampler=sim.market.kind,
        mortality=sim.scenario.levers.mortality.kind,
        start_year=sim.scenario.horizon.start_year,
        members=members,
        telemetry=telemetry,
        market=market,
        death_ages=deaths,
        engine_version=engine_version(),
        elapsed_seconds=time.perf_counter() - started,
    )
