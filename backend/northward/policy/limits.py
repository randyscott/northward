"""Contribution limits for a given year, indexed from the rules' base year."""

from __future__ import annotations

from typing import Literal

from northward.config.base import ByFilingStatus, FilingStatus
from northward.config.rules.contribution_limits import ContributionLimitsDoc
from northward.config.rules.federal_tax import PhaseOutRange
from northward.tax.indexing import PriceIndex


class Limits:
    def __init__(self, rules: ContributionLimitsDoc, prices: PriceIndex):
        self.rules = rules
        self.prices = prices
        self.base_year = rules.metadata.base_year

    def _indexed(self, amount: float, year: int, indexed: bool, rounding: float | None = None) -> float:
        return self.prices.indexed(amount, self.base_year, year, rounding) if indexed else amount

    def elective_deferral(self, year: int) -> float:
        ed = self.rules.elective_deferral
        return self._indexed(ed.limit, year, ed.indexed, ed.rounding)

    def deferral_catch_up(self, age: int, year: int) -> float:
        """Catch-up allowed for someone who reaches `age` during `year`: larger in the years they turn 60-63."""
        ed = self.rules.elective_deferral
        if age < 50:
            return 0.0
        amount = ed.catch_up_60_63 if 60 <= age <= 63 else ed.catch_up_50
        return self._indexed(amount, year, ed.indexed, ed.rounding)

    def roth_catch_up_required(self, prior_year_wages: float, year: int) -> bool:
        ed = self.rules.elective_deferral
        threshold = self._indexed(ed.roth_catch_up_wage_threshold, year, ed.roth_catch_up_threshold_indexed)
        return year >= ed.roth_catch_up_required_from and prior_year_wages > threshold

    def hsa(self, coverage: Literal["self_only", "family"], age: int, year: int) -> float:
        hsa = self.rules.hsa
        base = hsa.self_only if coverage == "self_only" else hsa.family
        limit = self._indexed(base, year, hsa.indexed, hsa.rounding)
        if age >= 55:
            limit += self._indexed(hsa.catch_up_55, year, hsa.catch_up_indexed)
        return limit

    def ira(self, age: int, year: int) -> float:
        """Combined traditional + Roth IRA limit, with the 50+ catch-up."""
        ira = self.rules.ira
        limit = self._indexed(ira.limit, year, ira.indexed, ira.rounding)
        if age >= 50:
            limit += self._indexed(ira.catch_up_50, year, ira.indexed, ira.catch_up_rounding)
        return limit

    def annual_additions(self, year: int) -> float:
        return self._indexed(self.rules.annual_additions_limit, year, self.rules.elective_deferral.indexed)

    def gift_exclusion(self, year: int) -> float:
        gift = self.rules.gift_tax
        return self._indexed(gift.annual_exclusion, year, gift.indexed, gift.rounding)

    def phase_out_share(
        self,
        table: ByFilingStatus[PhaseOutRange],
        status: FilingStatus,
        magi: float,
        year: int,
        mfs_indexed: bool,
        indexed: bool,
    ) -> float:
        """Share of a contribution allowed by a MAGI phase-out range (1 below the range, 0 above it)."""
        span = table.for_status(status)
        scale = 1.0
        if indexed and (status is not FilingStatus.MARRIED_FILING_SEPARATELY or mfs_indexed):
            scale = self.prices.factor(self.base_year, year)
        start, end = span.start * scale, span.end * scale
        if end <= start:
            return 0.0 if magi >= start else 1.0
        return 1.0 - min(1.0, max(0.0, (magi - start) / (end - start)))
