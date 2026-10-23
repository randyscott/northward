"""Monte Carlo telemetry: a `(sims × years × buckets)` array of year-end values, and its `.npz` storage.

Dollar buckets are nominal; divide by `price_level` for today's (start-year) dollars. Years after a path ends (the
last death, when lifespans are sampled) are NaN.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from northward.config.rules.market import FACTORS
from northward.engine.results import SimulationResult, YearState

BUCKETS = (
    "price_level",  # general price level, 1.0 in the start year
    "members_alive",
    "net_worth",
    "total_assets",
    "liabilities",
    "liquid",  # unswept cash plus cash and brokerage accounts (the taxable bucket)
    "taxable",
    "deferred",
    "roth",
    "hsa",
    "education",  # 529s
    "income",  # wages, Social Security, pensions, other income, investment income, RMDs, inherited distributions
    "wages",
    "social_security",
    "pensions",
    "spending",  # every spending category, healthcare included (debt service is separate)
    "healthcare",  # premiums, IRMAA, and out-of-pocket costs
    "irmaa",
    "debt_payments",
    "federal_tax",  # income tax, NIIT, and additional taxes, less refundable credits
    "state_tax",
    "fica",
    "total_taxes",
    "rmds",
    "roth_conversions",
    "withdrawals",
    "shortfall",  # spending and taxes that couldn't be funded
)
NON_DOLLAR_BUCKETS = frozenset({"price_level", "members_alive"})
BUCKET_INDEX = {name: i for i, name in enumerate(BUCKETS)}
_HEALTHCARE = ("healthcare_premiums", "medicare_irmaa", "healthcare_out_of_pocket")


def year_income(state: YearState) -> float:
    f = state.flows
    return (
        f.gross_wages
        + f.social_security
        + f.pension_income
        + f.other_income
        + f.investment_income
        + f.rmds
        + f.inherited_distributions
    )


def _row(state: YearState, buckets_of: dict[str, str]) -> list[float]:
    f, t = state.flows, state.flows.taxes
    by_bucket = dict.fromkeys(("taxable", "deferred", "roth", "hsa", "education"), 0.0)
    for account, balance in state.balances.items():
        by_bucket[buckets_of[account]] += balance
    values = {
        "price_level": state.price_level,
        "members_alive": len(state.ages),
        "net_worth": state.net_worth,
        "total_assets": state.total_assets,
        "liabilities": state.total_liabilities,
        "liquid": state.cash + by_bucket["taxable"],
        **by_bucket,
        "income": year_income(state),
        "wages": f.gross_wages,
        "social_security": f.social_security,
        "pensions": f.pension_income,
        "spending": f.total_spending,
        "healthcare": sum(f.spending.get(label, 0.0) for label in _HEALTHCARE),
        "irmaa": f.spending.get("medicare_irmaa", 0.0),
        "debt_payments": f.debt_payments,
        "federal_tax": 0.0
        if t is None
        else t.income_tax + t.net_investment_income_tax + t.additional_taxes - t.credits.refundable,
        "state_tax": 0.0 if t is None else t.state.tax,
        "fica": 0.0 if t is None else t.social_security_tax + t.medicare_tax,
        "total_taxes": f.total_taxes,
        "rmds": f.rmds,
        "roth_conversions": f.roth_conversions,
        "withdrawals": sum(f.withdrawals.values()),
        "shortfall": f.shortfall,
    }
    return [values[name] for name in BUCKETS]


def telemetry_rows(result: SimulationResult) -> np.ndarray:
    """`(years × buckets)` telemetry for one simulated path."""
    return np.array([_row(state, result.account_buckets) for state in result.years], dtype=np.float64)


@dataclass(frozen=True)
class MonteCarloResult:
    profile: str
    scenario: str
    seed: int
    preset: str
    sampler: str  # parametric | bootstrap
    mortality: str  # the scenario's mortality lever: none | fixed | sampled
    start_year: int
    members: tuple[str, ...]
    telemetry: np.ndarray  # (sims, years, buckets); NaN once a path has ended
    market: np.ndarray  # (sims, years, FACTORS) returns and inflation each path ran on; NaN once it has ended
    death_ages: np.ndarray  # (sims, members): age at death, NaN if the member outlives the horizon
    engine_version: str
    elapsed_seconds: float = 0.0
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def n_sims(self) -> int:
        return self.telemetry.shape[0]

    @property
    def years(self) -> np.ndarray:
        return self.start_year + np.arange(self.telemetry.shape[1])

    def bucket(self, name: str) -> np.ndarray:
        """`(sims × years)` values of one bucket."""
        return self.telemetry[:, :, BUCKET_INDEX[name]]

    def real(self, name: str) -> np.ndarray:
        """`(sims × years)` values of a dollar bucket in today's (start-year) dollars."""
        return self.bucket(name) / self.bucket("price_level")

    @property
    def active(self) -> np.ndarray:
        """`(sims × years)`: True while the path is running."""
        return ~np.isnan(self.bucket("price_level"))

    def death_ages_of(self, index: int) -> dict[str, float]:
        return {m: float(a) for m, a in zip(self.members, self.death_ages[index], strict=True) if not np.isnan(a)}


def save(result: MonteCarloResult, path: Path) -> Path:
    """Write `result` as a compressed `.npz` (float32 telemetry and market arrays, plus metadata)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    meta = {
        "profile": result.profile,
        "scenario": result.scenario,
        "seed": result.seed,
        "preset": result.preset,
        "sampler": result.sampler,
        "mortality": result.mortality,
        "start_year": result.start_year,
        "members": list(result.members),
        "buckets": list(BUCKETS),
        "factors": list(FACTORS),
        "engine_version": result.engine_version,
        "elapsed_seconds": result.elapsed_seconds,
        "extra": result.extra,
    }
    np.savez_compressed(
        path,
        telemetry=result.telemetry.astype(np.float32),
        market=result.market.astype(np.float32),
        death_ages=result.death_ages,
        meta=np.array(json.dumps(meta)),
    )
    return path


def load(path: Path) -> MonteCarloResult:
    with np.load(path) as data:
        meta = json.loads(str(data["meta"]))
        if meta["buckets"] != list(BUCKETS):
            raise ValueError(f"{path} was written with different telemetry buckets; rerun it")
        return MonteCarloResult(
            profile=meta["profile"],
            scenario=meta["scenario"],
            seed=meta["seed"],
            preset=meta["preset"],
            sampler=meta["sampler"],
            mortality=meta["mortality"],
            start_year=meta["start_year"],
            members=tuple(meta["members"]),
            telemetry=data["telemetry"].astype(np.float64),
            market=data["market"].astype(np.float64),
            death_ages=data["death_ages"],
            engine_version=meta["engine_version"],
            elapsed_seconds=meta["elapsed_seconds"],
            extra=meta.get("extra", {}),
        )
