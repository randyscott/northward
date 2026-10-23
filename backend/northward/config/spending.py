"""Spending: a base annual amount plus phased or periodic categories (PLAN.md §4.1)."""

from __future__ import annotations

from itertools import pairwise
from typing import Literal

from pydantic import Field, model_validator

from northward.config.anchors import Anchor
from northward.config.base import Age, Document, Identifier, Money, StrictModel

SpendingIndex = Literal["general", "education", "healthcare", "none"]
SpendingTag = Literal["qualified_education", "dependent_care"]


class PhaseBand(StrictModel):
    until_age: Age | None = None  # inclusive; None on the last band
    multiplier: float = Field(ge=0)


class SpendingPhases(StrictModel):
    """Multipliers on base spending by the reference member's age (e.g. go-go / slow-go / no-go years)."""

    reference: Identifier
    bands: tuple[PhaseBand, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_bands(self) -> SpendingPhases:
        *leading, last = self.bands
        if last.until_age is not None:
            raise ValueError("the last phase band must omit until_age (it applies for the rest of the plan)")
        ages = [band.until_age for band in leading]
        if any(age is None for age in ages):
            raise ValueError("only the last phase band may omit until_age")
        if any(a >= b for a, b in pairwise(ages)):
            raise ValueError("phase band until_age values must increase")
        return self


class BaseSpending(StrictModel):
    amount: Money  # today's dollars per year
    index: SpendingIndex = "general"
    # Fractional change from the first full year all members are retired (e.g. -0.10).
    retirement_change: float = Field(default=0.0, ge=-1)
    # Healthcare costs are modeled separately (rules/healthcare.yaml + health_costs.yaml) unless this is true,
    # meaning base spending already covers them.
    includes_healthcare: bool = False
    # After the first death in a two-member household, base spending is multiplied by this.
    survivor_multiplier: float = Field(default=0.75, ge=0)
    phases: SpendingPhases | None = None


class SpendingCategory(StrictModel):
    """Spending on top of base. Active from `start` to `end` (inclusive), every `every_years`, or `once`."""

    id: Identifier
    description: str | None = None
    amount: Money  # today's dollars per occurrence
    index: SpendingIndex = "general"
    tags: tuple[SpendingTag, ...] = ()
    beneficiary: Identifier | None = None
    start: Anchor | None = None  # None: the simulation start year
    end: Anchor | None = None  # None: the end of the simulation
    every_years: int | None = Field(default=None, ge=1)
    once: Anchor | None = None

    @model_validator(mode="after")
    def _check(self) -> SpendingCategory:
        if self.once is not None and (self.start or self.end or self.every_years):
            raise ValueError("'once' can't be combined with start, end, or every_years")
        if "qualified_education" in self.tags and self.beneficiary is None:
            raise ValueError("qualified_education spending must name a beneficiary")
        if len(set(self.tags)) != len(self.tags):
            raise ValueError("tags must not repeat")
        return self


class Spending(StrictModel):
    base: BaseSpending
    categories: tuple[SpendingCategory, ...] = ()

    @model_validator(mode="after")
    def _check_unique(self) -> Spending:
        ids = [c.id for c in self.categories]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"spending category ids must be unique; duplicated: {', '.join(duplicates)}")
        return self


class SpendingDoc(Document):
    spending: Spending
