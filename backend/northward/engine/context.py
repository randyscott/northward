"""Everything a simulation year needs that doesn't change from year to year."""

from __future__ import annotations

from dataclasses import dataclass

from northward.config.income import OtherIncomeStream, PensionStream, SalaryStream
from northward.config.loader import SimulationInput
from northward.engine.market import MarketPath
from northward.engine.timeline import Timeline
from northward.policy.limits import Limits
from northward.tax.federal import FederalTax
from northward.tax.indexing import PriceIndex


@dataclass(frozen=True)
class SimContext:
    sim: SimulationInput
    timeline: Timeline
    path: MarketPath
    prices: PriceIndex
    limits: Limits
    tax: FederalTax

    @classmethod
    def build(cls, sim: SimulationInput, path: MarketPath, death_ages: dict[str, float] | None = None) -> SimContext:
        timeline = Timeline(sim, death_ages)
        if path.start_year != timeline.start_year or path.years < len(timeline.years):
            raise ValueError("the market path doesn't cover the simulation horizon")
        spreads = sim.market.inflation_spreads
        prices = PriceIndex(
            timeline.start_year,
            path.inflation,
            pre_start_inflation=sim.market.factors["inflation"].mean,
            spreads={"education": spreads.education, "healthcare": spreads.healthcare},
        )
        real_wage_growth = sim.scenario.macro.salary_growth.real_growth_rate
        return cls(
            sim,
            timeline,
            path,
            prices,
            Limits(sim.rules.contribution_limits, prices),
            FederalTax(sim.rules.federal_tax, prices, real_wage_growth, sim.rules.state_tax),
        )

    @property
    def salaries(self) -> list[SalaryStream]:
        return [s for s in self.sim.profile.income.income_streams if isinstance(s, SalaryStream)]

    @property
    def other_streams(self) -> list[PensionStream | OtherIncomeStream]:
        return [s for s in self.sim.profile.income.income_streams if not isinstance(s, SalaryStream)]

    def member_ages(self, year: int) -> dict[str, int]:
        """Ages of the members alive for at least part of `year`."""
        return {m.id: self.timeline.age(m, year) for m in self.timeline.living_members(year)}
