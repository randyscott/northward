"""Statistics from Monte Carlo telemetry: success under the profile's goals, percentile bands, terminal and legacy
wealth, lifetime taxes, and paired comparisons of scenarios run on the same draws.

Success is evaluated from telemetry after the run (D35), so other criteria can be applied without rerunning.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from northward.config.goals import GoalsDoc
from northward.config.loader import SimulationInput
from northward.engine.timeline import Timeline
from northward.lifecycle.mortality import is_sampled
from northward.montecarlo.telemetry import BUCKETS, NON_DOLLAR_BUCKETS, MonteCarloResult

PERCENTILES = (10, 25, 50, 75, 90)


@dataclass(frozen=True)
class SuccessResult:
    success: np.ndarray  # (sims,) bool
    failures: dict[str, np.ndarray]  # enabled criterion -> (sims,) bool, True where the path broke it
    first_failure: np.ndarray  # (sims,) index of the first failing year, -1 if none

    @property
    def probability(self) -> float:
        return float(self.success.mean())


def _floor_start_offsets(mc: MonteCarloResult, sim: SimulationInput, goals: GoalsDoc) -> np.ndarray:
    """Per path, the year offset from which the liquidity floor applies (a large number if it never does)."""
    floor = goals.success.liquidity_floor
    assert floor is not None
    never = mc.telemetry.shape[1]
    if floor.start is None:
        return np.zeros(mc.n_sims, dtype=np.int64)

    def offset(timeline: Timeline) -> int:
        year = timeline.year_of(floor.start)
        return never if year is None else max(0, year - mc.start_year)

    if not is_sampled(sim):
        return np.full(mc.n_sims, offset(Timeline(sim)), dtype=np.int64)
    cache: dict[tuple[float, ...], int] = {}
    offsets = np.empty(mc.n_sims, dtype=np.int64)
    for i in range(mc.n_sims):
        key = tuple(mc.death_ages[i])
        if key not in cache:
            cache[key] = offset(Timeline(sim, mc.death_ages_of(i)))
        offsets[i] = cache[key]
    return offsets


def evaluate_success(mc: MonteCarloResult, sim: SimulationInput, goals: GoalsDoc) -> SuccessResult:
    criteria = goals.success
    active = mc.active
    failing: dict[str, np.ndarray] = {}  # criterion -> (sims, years) bool
    if criteria.no_shortfall:
        failing["no_shortfall"] = active & (np.nan_to_num(mc.bucket("shortfall")) > criteria.shortfall_tolerance)
    if criteria.liquidity_floor is not None:
        starts = _floor_start_offsets(mc, sim, goals)
        applies = active & (np.arange(mc.telemetry.shape[1])[None, :] >= starts[:, None])
        below = np.nan_to_num(mc.real("liquid"), nan=np.inf) < criteria.liquidity_floor.amount - 0.005
        failing["liquidity_floor"] = applies & below
    any_year = np.zeros(active.shape, dtype=bool)
    for years in failing.values():
        any_year |= years
    failed = any_year.any(axis=1)
    first = np.where(failed, any_year.argmax(axis=1), -1)
    return SuccessResult(~failed, {name: years.any(axis=1) for name, years in failing.items()}, first)


def _percentiles(values: np.ndarray) -> dict[str, float]:
    """Percentiles of a 1-D array, ignoring NaN."""
    values = values[~np.isnan(values)]
    if values.size == 0:
        return {f"p{p}": float("nan") for p in PERCENTILES}
    return {f"p{p}": float(v) for p, v in zip(PERCENTILES, np.percentile(values, PERCENTILES), strict=True)}


def _last_active(mc: MonteCarloResult, values: np.ndarray) -> np.ndarray:
    """(sims,) value in each path's final year."""
    last = mc.active.sum(axis=1) - 1
    return values[np.arange(mc.n_sims), last]


@dataclass(frozen=True)
class PathOutcomes:
    """Per-path outcomes in nominal and today's dollars."""

    terminal_net_worth: np.ndarray
    terminal_net_worth_real: np.ndarray
    legacy_after_tax: np.ndarray  # net worth less the heirs' tax on pre-tax accounts
    legacy_after_tax_real: np.ndarray
    lifetime_taxes: np.ndarray
    lifetime_taxes_real: np.ndarray
    final_year: np.ndarray


def path_outcomes(mc: MonteCarloResult, goals: GoalsDoc) -> PathOutcomes:
    rate = goals.legacy.heirs_tax_rate
    price = _last_active(mc, mc.bucket("price_level"))
    net_worth = _last_active(mc, mc.bucket("net_worth"))
    pre_tax = _last_active(mc, mc.bucket("deferred") + mc.bucket("hsa"))
    legacy = net_worth - rate * pre_tax
    taxes = np.nansum(mc.bucket("total_taxes"), axis=1)
    taxes_real = np.nansum(mc.real("total_taxes"), axis=1)
    final_year = mc.start_year + mc.active.sum(axis=1) - 1
    return PathOutcomes(net_worth, net_worth / price, legacy, legacy / price, taxes, taxes_real, final_year)


def bands(mc: MonteCarloResult) -> dict[str, dict[str, dict[str, list[float]]]]:
    """{bucket: {nominal|real: {pXX: [value per year]}}}, over the paths still running each year."""
    out: dict[str, dict[str, dict[str, list[float]]]] = {}
    with np.errstate(all="ignore"):
        for name in BUCKETS:
            bases = {"nominal": mc.bucket(name)}
            if name not in NON_DOLLAR_BUCKETS:
                bases["real"] = mc.real(name)
            out[name] = {}
            for basis, values in bases.items():
                if np.isnan(values).all(axis=0).any():
                    columns = [_percentiles(values[:, y]) for y in range(values.shape[1])]
                    out[name][basis] = {f"p{p}": [c[f"p{p}"] for c in columns] for p in PERCENTILES}
                else:
                    table = np.nanpercentile(values, PERCENTILES, axis=0)
                    out[name][basis] = {f"p{p}": row.tolist() for p, row in zip(PERCENTILES, table, strict=True)}
    return out


def representative_paths(values: np.ndarray) -> dict[str, int]:
    """Path index at each percentile of `values` (for drill-down)."""
    order = np.argsort(values, kind="stable")
    return {f"p{p}": int(order[round(p / 100 * (len(order) - 1))]) for p in PERCENTILES}


def summarize(mc: MonteCarloResult, sim: SimulationInput, goals: GoalsDoc, with_bands: bool = True) -> dict[str, Any]:
    """A JSON-ready summary of a Monte Carlo run."""
    success = evaluate_success(mc, sim, goals)
    outcomes = path_outcomes(mc, goals)
    years = mc.years
    first = success.first_failure[success.first_failure >= 0]
    failure_years = {int(years[y]): int(count) for y, count in zip(*np.unique(first, return_counts=True), strict=True)}
    summary: dict[str, Any] = {
        "profile": mc.profile,
        "scenario": mc.scenario,
        "seed": mc.seed,
        "n_sims": mc.n_sims,
        "preset": mc.preset,
        "sampler": mc.sampler,
        "mortality": mc.mortality,
        "engine_version": mc.engine_version,
        "elapsed_seconds": round(mc.elapsed_seconds, 2),
        "years": years.tolist(),
        "goals": goals.model_dump(mode="json", exclude={"schema_version"}),
        "success": {
            "probability": success.probability,
            "failure_probability": {name: float(f.mean()) for name, f in success.failures.items()},
            "first_failure_year": failure_years,
            "median_first_failure_year": int(years[int(np.median(first))]) if first.size else None,
        },
        "terminal_net_worth": {
            "nominal": _percentiles(outcomes.terminal_net_worth),
            "real": _percentiles(outcomes.terminal_net_worth_real),
        },
        "legacy_after_tax": {
            "nominal": _percentiles(outcomes.legacy_after_tax),
            "real": _percentiles(outcomes.legacy_after_tax_real),
        },
        "lifetime_taxes": {
            "nominal": _percentiles(outcomes.lifetime_taxes),
            "real": _percentiles(outcomes.lifetime_taxes_real),
        },
        "final_year": _percentiles(outcomes.final_year.astype(float)),
        "paths_running": mc.active.sum(axis=0).tolist(),
        # Drill down with `northward run --path N --seed S`: paths at percentiles of real after-tax legacy.
        "representative_paths": representative_paths(outcomes.legacy_after_tax_real),
    }
    if with_bands:
        summary["bands"] = bands(mc)
    return summary


def compare(runs: list[tuple[MonteCarloResult, SimulationInput]], goals: GoalsDoc) -> dict[str, Any]:
    """Compare scenarios run with the same seed and path count (common random numbers): each scenario's headline
    numbers, and path-by-path differences from the first scenario, so the gaps reflect the decisions rather than
    sampling noise. Every scenario is measured against the same `goals`."""
    base_mc = runs[0][0]
    for mc, _ in runs[1:]:
        if (mc.seed, mc.n_sims) != (base_mc.seed, base_mc.n_sims):
            raise ValueError("scenarios must be run with the same seed and number of paths to be compared")
    base_success = evaluate_success(base_mc, runs[0][1], goals).success
    base_outcomes = path_outcomes(base_mc, goals)
    rows = []
    for mc, sim in runs:
        success = evaluate_success(mc, sim, goals).success
        outcomes = path_outcomes(mc, goals)
        legacy_gap = outcomes.legacy_after_tax_real - base_outcomes.legacy_after_tax_real
        tax_gap = outcomes.lifetime_taxes_real - base_outcomes.lifetime_taxes_real
        rows.append(
            {
                "scenario": mc.scenario,
                "preset": mc.preset,
                "success_probability": float(success.mean()),
                "terminal_net_worth_real": _percentiles(outcomes.terminal_net_worth_real),
                "legacy_after_tax_real": _percentiles(outcomes.legacy_after_tax_real),
                "lifetime_taxes_real": _percentiles(outcomes.lifetime_taxes_real),
                "vs_first": {
                    "succeeds_where_first_fails": float((success & ~base_success).mean()),
                    "fails_where_first_succeeds": float((~success & base_success).mean()),
                    "legacy_after_tax_real_difference": _percentiles(legacy_gap),
                    "legacy_higher_probability": float((legacy_gap > 0).mean()),
                    "lifetime_taxes_real_difference": _percentiles(tax_gap),
                },
            }
        )
    return {
        "seed": base_mc.seed,
        "n_sims": base_mc.n_sims,
        "goals": goals.model_dump(mode="json", exclude={"schema_version"}),
        "scenarios": rows,
    }
