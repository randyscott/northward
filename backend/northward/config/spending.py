"""Spending: a base annual amount plus phased or periodic categories (docs/configuration/spending.md)."""

from __future__ import annotations

from itertools import pairwise
from typing import Literal

from pydantic import Field, model_validator

from northward.config.anchors import Anchor
from northward.config.base import Age, Document, Identifier, Money, StrictModel

SpendingIndex = Literal["general", "education", "healthcare", "none"]
SpendingTag = Literal["qualified_education", "dependent_care"]


class PhaseBand(StrictModel):
    until_age: Age | None = None
    """The band applies through this age of the reference member (inclusive). Leave out on the last band."""
    multiplier: float = Field(ge=0)
    """Base spending is multiplied by this, e.g. 0.85."""


class SpendingPhases(StrictModel):
    """Multipliers on base spending by the reference member's age (e.g. go-go / slow-go / no-go years)."""

    reference: Identifier
    """The member whose age selects the band."""
    bands: tuple[PhaseBand, ...] = Field(min_length=1)
    """Bands in increasing age order; the last has no `until_age`."""

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
    """Ordinary living costs, excluding taxes, healthcare, and loan payments (which are modeled separately)."""

    amount: Money
    """Annual spending in today's dollars."""
    index: SpendingIndex = "general"
    """How it grows: `general` (CPI), `education` or `healthcare` (CPI plus the preset's spread), or `none`."""
    retirement_change: float = Field(default=0.0, ge=-1)
    """Fractional change from the first full year all members are retired, e.g. -0.10."""
    includes_healthcare: bool = False
    """True if `amount` already covers healthcare, which turns off the healthcare cost model."""
    survivor_multiplier: float = Field(default=0.75, ge=0)
    """After the first death in a two-member household, base spending is multiplied by this."""
    phases: SpendingPhases | None = None
    """Multipliers by a member's age, e.g. spending less in later decades."""


class SpendingCategory(StrictModel):
    """Spending on top of base. Active from `start` to `end` (inclusive), every `every_years`, or `once`."""

    id: Identifier
    """Shown in the results' spending breakdown and the ledger."""
    description: str | None = None
    """A note for yourself."""
    amount: Money
    """Today's dollars per year it occurs."""
    index: SpendingIndex = "general"
    """How it grows: `general` (CPI), `education` or `healthcare` (CPI plus the preset's spread), or `none`."""
    tags: tuple[SpendingTag, ...] = ()
    """`qualified_education` (education credits, paid from 529s) and `dependent_care` (care credit, FSA)."""
    beneficiary: Identifier | None = None
    """The dependent (or member) it's for. Required with `qualified_education`."""
    start: Anchor | None = None
    """The first year. Default: the start of the plan."""
    end: Anchor | None = None
    """The last year (inclusive). Default: the end of the plan."""
    every_years: int | None = Field(default=None, ge=1)
    """Repeat every N years from `start`. Default: every year."""
    once: Anchor | None = None
    """A single year. Can't be combined with `start`, `end`, or `every_years`."""

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
    """Ordinary annual spending."""
    categories: tuple[SpendingCategory, ...] = ()
    """Spending on top of base: once, every few years, or for a stretch of years."""

    @model_validator(mode="after")
    def _check_unique(self) -> Spending:
        ids = [c.id for c in self.categories]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"spending category ids must be unique; duplicated: {', '.join(duplicates)}")
        return self


class SpendingDoc(Document):
    """What the household spends: a base amount plus categories."""

    spending: Spending
    """Base spending and categories."""
