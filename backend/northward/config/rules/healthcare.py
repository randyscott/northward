"""Healthcare rules (Medicare premiums, IRMAA, the ACA age curve) and the household's cost assumptions."""

from __future__ import annotations

from itertools import pairwise
from typing import Literal

from pydantic import Field, field_validator

from northward.config.base import Age, Document, Money, StrictModel
from northward.config.rules.federal_tax import Metadata


class IrmaaTier(StrictModel):
    """Monthly surcharges for MAGI up to `up_to` (from the return two years earlier)."""

    up_to: float
    part_b_adjustment: Money
    part_d_adjustment: Money
    # Thresholds are CPI-indexed from the rules' base year; a tier frozen by statute gives the year indexing starts.
    indexed_from: int | None = None


def _check_tiers(tiers: tuple[IrmaaTier, ...]) -> tuple[IrmaaTier, ...]:
    bounds = [t.up_to for t in tiers]
    if any(a >= b for a, b in pairwise(bounds)) or bounds[-1] != float("inf"):
        raise ValueError("IRMAA tier bounds must increase and end with .inf")
    return tiers


class IrmaaSchedules(StrictModel):
    single: tuple[IrmaaTier, ...]  # single, HoH, QSS, and MFS who lived apart
    joint: tuple[IrmaaTier, ...]
    separate: tuple[IrmaaTier, ...]  # MFS who lived with their spouse

    @field_validator("single", "joint", "separate")
    @classmethod
    def _check(cls, tiers: tuple[IrmaaTier, ...]) -> tuple[IrmaaTier, ...]:
        return _check_tiers(tiers)


class Irmaa(StrictModel):
    lookback_years: int = Field(gt=0)
    thresholds_indexed: bool = True  # by CPI
    rounding: Money = 1000
    tiers: IrmaaSchedules


class Medicare(StrictModel):
    eligibility_age: Age
    part_b_monthly_premium: Money
    part_b_annual_deductible: Money


class HealthcareAssumptions(StrictModel):
    """The household's healthcare costs in today's dollars (grown by healthcare inflation). Per person unless noted."""

    employer_premium: Money  # annual household employee share while anyone works; paid pre-tax through payroll
    individual_premium_age_40: Money  # annual unsubsidized individual-market premium at 40 (scaled by the age curve)
    part_d_premium: Money  # annual stand-alone Part D plan premium
    supplement_premium: Money  # annual Medigap (or similar) premium
    out_of_pocket_under_65: Money
    out_of_pocket_65_plus: Money
    dependent_coverage_until_age: int = Field(default=26, gt=0)  # dependents covered through the year before this age
    # When HSAs pay qualified medical costs (out-of-pocket and Medicare premiums) tax-free.
    hsa_medical: Literal["pay_when_retired", "pay_always", "never"] = "pay_when_retired"


class HealthcareDoc(Document):
    metadata: Metadata
    medicare: Medicare
    irmaa: Irmaa
    # Individual-market premium relative to age 21 (federal default curve). Ages past the last entry use it.
    aca_age_curve: dict[int, float] = Field(min_length=1)
    default_assumptions: HealthcareAssumptions

    @field_validator("aca_age_curve")
    @classmethod
    def _check_curve(cls, curve: dict[int, float]) -> dict[int, float]:
        ages = sorted(curve)
        if ages != list(range(ages[0], ages[-1] + 1)) or any(v <= 0 for v in curve.values()):
            raise ValueError("aca_age_curve needs consecutive ages with positive ratios")
        return curve

    def age_factor(self, age: int) -> float:
        curve = self.aca_age_curve
        return curve[min(max(age, min(curve)), max(curve))]


class HealthcareProfileDoc(Document):
    """The household's healthcare cost assumptions, replacing the defaults in rules/healthcare.yaml. Every field is
    optional; amounts are annual, in today's dollars, and grow with healthcare inflation."""

    employer_premium: Money | None = None
    """The household's share of employer coverage while anyone works, paid pre-tax."""
    individual_premium_age_40: Money | None = None
    """Unsubsidized individual-market premium per person at age 40, before 65 with no employer coverage. Other ages
    follow the ACA age curve."""
    part_d_premium: Money | None = None
    """Medicare Part D plan premium per person, before any IRMAA surcharge."""
    supplement_premium: Money | None = None
    """Medigap (or similar) premium per person from 65."""
    out_of_pocket_under_65: Money | None = None
    """Deductibles, copays, and uncovered care per person before 65."""
    out_of_pocket_65_plus: Money | None = None
    """Out-of-pocket costs per person from 65."""
    dependent_coverage_until_age: int | None = None
    """Dependents are covered (and cost premiums) through the year before this age."""
    hsa_medical: Literal["pay_when_retired", "pay_always", "never"] | None = None
    """When HSAs pay qualified medical costs tax-free: once the owner retires, always, or never."""
