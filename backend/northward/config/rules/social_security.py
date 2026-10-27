"""Social Security benefit rules (docs/decisions.md D6: benefits start from each member's PIA at full retirement age)."""

from __future__ import annotations

from itertools import pairwise

from pydantic import Field, model_validator

from northward.config.base import Age, Document, FractionalRate, Money, Rate, StrictModel, Year
from northward.config.rules.federal_tax import Metadata


class FraEntry(StrictModel):
    """Full retirement age for births through `born_through_year` (None: all later births).

    SSA treats someone born on January 1 as born in the previous year; profiles record only birth month, so the
    engine can't apply that rule.
    """

    born_through_year: Year | None = None
    years: int = Field(ge=60, le=70)
    months: int = Field(default=0, ge=0, le=11)


def _check_fra_table(entries: tuple[FraEntry, ...]) -> None:
    *leading, last = entries
    if last.born_through_year is not None:
        raise ValueError("the last full-retirement-age entry must omit born_through_year")
    years = [e.born_through_year for e in leading]
    if any(y is None for y in years) or any(a >= b for a, b in pairwise(years)):
        raise ValueError("full-retirement-age entries must be in increasing birth-year order")


def _fra_for(entries: tuple[FraEntry, ...], birth_year: int) -> tuple[int, int]:
    for entry in entries:
        if entry.born_through_year is None or birth_year <= entry.born_through_year:
            return entry.years, entry.months
    raise AssertionError("unreachable: the last entry is open-ended")


class ReductionSchedule(StrictModel):
    """Reduction per month claimed before full retirement age."""

    first_months: int = Field(gt=0)
    first_rate_per_month: FractionalRate
    additional_rate_per_month: FractionalRate


class SpousalRules(StrictModel):
    fraction_of_pia: Rate  # of the worker's PIA; spousal benefits earn no delayed credits
    early_reduction: ReductionSchedule


class SurvivorRules(StrictModel):
    fraction_of_deceased_benefit: Rate  # includes the deceased's delayed credits
    earliest_age: Age
    max_reduction: Rate  # at earliest_age, prorated monthly to the survivor full retirement age
    # If the deceased claimed early, the survivor benefit is capped at the larger of the deceased's reduced benefit
    # and this fraction of their PIA.
    widow_limit_floor_fraction: Rate
    full_retirement_age: tuple[FraEntry, ...] = Field(min_length=1)  # a later-phased table than for workers

    @model_validator(mode="after")
    def _check(self) -> SurvivorRules:
        _check_fra_table(self.full_retirement_age)
        return self


class ChildRules(StrictModel):
    living_worker_fraction: Rate  # of the worker's PIA
    survivor_fraction: Rate  # of the deceased's PIA
    under_age: int = Field(gt=0)
    student_under_age: int = Field(gt=0)  # full-time elementary/secondary student
    disabled_before_age: int = Field(gt=0)


class ChildInCareRules(StrictModel):
    """Spouse (or surviving parent) caring for an entitled child: no minimum age and no age reduction."""

    child_under_age: int = Field(gt=0)
    spouse_fraction: Rate
    survivor_parent_fraction: Rate


class FamilyMaximum(StrictModel):
    """Family max = rates[0] x PIA up to bend_points[0], rates[1] up to [1], rates[2] up to [2], rates[3] above."""

    rates: tuple[float, float, float, float]
    bend_points: tuple[Money, Money, Money]  # for workers first eligible in the base year
    indexed: bool = True  # by the national average wage index

    @model_validator(mode="after")
    def _check(self) -> FamilyMaximum:
        if not self.bend_points[0] < self.bend_points[1] < self.bend_points[2]:
            raise ValueError("family maximum bend points must increase")
        return self


class EarningsTest(StrictModel):
    under_fra_exempt: Money
    under_fra_withholding_rate: Rate  # benefits withheld per dollar earned over the exempt amount
    fra_year_exempt: Money  # in the year FRA is reached, counting earnings before the FRA month
    fra_year_withholding_rate: Rate
    indexed: bool = True


class SocialSecurityDoc(Document):
    metadata: Metadata
    earliest_claim_age: Age
    latest_credit_age: Age  # delayed credits stop accruing here
    full_retirement_age: tuple[FraEntry, ...] = Field(min_length=1)
    early_reduction: ReductionSchedule
    delayed_credit_per_year: Rate
    spousal: SpousalRules
    survivor: SurvivorRules
    child: ChildRules
    child_in_care: ChildInCareRules
    family_maximum: FamilyMaximum
    earnings_test: EarningsTest

    @model_validator(mode="after")
    def _check(self) -> SocialSecurityDoc:
        _check_fra_table(self.full_retirement_age)
        if self.latest_credit_age <= self.earliest_claim_age:
            raise ValueError("latest_credit_age must be after earliest_claim_age")
        return self

    def full_retirement_age_for(self, birth_year: int) -> tuple[int, int]:
        """(years, months) for a worker or spouse born in `birth_year`."""
        return _fra_for(self.full_retirement_age, birth_year)

    def survivor_full_retirement_age_for(self, birth_year: int) -> tuple[int, int]:
        return _fra_for(self.survivor.full_retirement_age, birth_year)
