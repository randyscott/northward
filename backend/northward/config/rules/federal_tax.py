"""Federal income and payroll tax rules for one base year. Thresholds marked `indexed` grow with simulated CPI (D9).

In per-status tables whose values may be null, null means the filing status is ineligible.
"""

from __future__ import annotations

from itertools import pairwise
from typing import Annotated

from pydantic import AfterValidator, Field, model_validator

from northward.config.base import Age, ByFilingStatus, Document, Money, Rate, StrictModel, Year


def _check_schedule(schedule: tuple[tuple[float, float], ...]) -> tuple[tuple[float, float], ...]:
    if not schedule:
        raise ValueError("a bracket schedule needs at least one bracket")
    caps = [cap for cap, _ in schedule]
    rates = [rate for _, rate in schedule]
    if any(a >= b for a, b in pairwise(caps)):
        raise ValueError("bracket upper bounds must strictly increase")
    if caps[-1] != float("inf"):
        raise ValueError("the last bracket's upper bound must be .inf")
    if any(not 0 <= r <= 1 for r in rates) or any(a > b for a, b in pairwise(rates)):
        raise ValueError("bracket rates must be between 0 and 1 and must not decrease")
    return schedule


# [[upper bound of taxable income, marginal rate], ...], ending with [.inf, top rate].
BracketSchedule = Annotated[tuple[tuple[float, float], ...], AfterValidator(_check_schedule)]


class Metadata(StrictModel):
    jurisdiction: str
    base_year: Year
    description: str | None = None
    sources: tuple[str, ...] = ()


class PhaseOutRange(StrictModel):
    start: Money
    end: Money

    @model_validator(mode="after")
    def _check(self) -> PhaseOutRange:
        if self.end < self.start:
            raise ValueError("phase-out end must not be below its start")
        return self


class AdditionalStandardDeduction(StrictModel):
    """Per person, per condition (age 65+ or blind)."""

    married: Money  # MFJ, MFS, QSS
    unmarried: Money  # single, HoH


class StandardDeduction(StrictModel):
    indexed: bool = True
    amounts: ByFilingStatus[Money]
    additional_65_or_blind: AdditionalStandardDeduction


class SeniorDeduction(StrictModel):
    """OBBBA enhanced deduction for age 65+, per qualifying person; each person's amount phases out separately."""

    amount_per_person: Money
    min_age: Age
    first_year: Year
    last_year: Year
    indexed: bool = False
    phase_out_rate: Rate
    magi_threshold: ByFilingStatus[Money | None]


class BracketTable(StrictModel):
    indexed: bool = True
    schedules: ByFilingStatus[BracketSchedule]


class NetInvestmentIncomeTax(StrictModel):
    rate: Rate
    indexed: bool = False
    magi_threshold: ByFilingStatus[Money]


class SsTaxThresholds(StrictModel):
    base: Money  # up to 50% of benefits taxable above this provisional income
    adjusted_base: Money  # up to 85% taxable above this

    @model_validator(mode="after")
    def _check(self) -> SsTaxThresholds:
        if self.adjusted_base < self.base:
            raise ValueError("adjusted_base must not be below base")
        return self


class SocialSecurityTaxability(StrictModel):
    indexed: bool = False
    tier1_rate: Rate
    tier2_rate: Rate
    thresholds: ByFilingStatus[SsTaxThresholds]


class Fica(StrictModel):
    social_security_rate: Rate  # employee share
    social_security_wage_base: Money
    wage_base_indexed: bool = True  # by the national average wage index; the engine uses simulated wage growth
    medicare_rate: Rate  # employee share, no wage cap
    additional_medicare_rate: Rate
    additional_medicare_indexed: bool = False
    additional_medicare_threshold: ByFilingStatus[Money]


class CapitalLossLimit(StrictModel):
    """Net capital losses offset ordinary income up to this much per year; the rest carries forward."""

    annual_limit: Money
    married_filing_separately_limit: Money


class Penalties(StrictModel):
    early_withdrawal_rate: Rate
    early_withdrawal_age: Age
    hsa_non_medical_rate: Rate
    hsa_penalty_free_age: Age
    plan_529_non_qualified_earnings_rate: Rate


class DependentAgeTests(StrictModel):
    """Age limits (exclusive: "under N" at year end) used to derive each dependent's status for a year (§4.4)."""

    ctc_under_age: int = Field(gt=0)
    qualifying_child_under_age: int = Field(gt=0)
    student_under_age: int = Field(gt=0)
    care_under_age: int = Field(gt=0)


class ChildTaxCredit(StrictModel):
    amount_per_child: Money
    amount_indexed: bool
    amount_rounding: Money  # indexed amounts round down to a multiple of this
    refundable_max_per_child: Money
    refundable_indexed: bool
    refundable_rounding: Money
    refundable_earned_income_threshold: Money
    refundable_rate: Rate
    phase_out_threshold: ByFilingStatus[Money]
    phase_out_per_1000: Money  # reduction per $1,000 (or fraction) of MAGI over the threshold; shared with ODC
    phase_out_indexed: bool = False


class OtherDependentCredit(StrictModel):
    amount: Money
    indexed: bool = False


class AmericanOpportunityCredit(StrictModel):
    tier1_expenses: Money
    tier1_rate: Rate
    tier2_expenses: Money
    tier2_rate: Rate
    refundable_fraction: Rate
    max_years: int = Field(gt=0)


class LifetimeLearningCredit(StrictModel):
    rate: Rate
    expense_cap_per_return: Money


class EducationCredits(StrictModel):
    indexed: bool = False
    phase_out: ByFilingStatus[PhaseOutRange | None]  # shared by AOTC and LLC; null = ineligible
    american_opportunity: AmericanOpportunityCredit
    lifetime_learning: LifetimeLearningCredit


class CareRateStage(StrictModel):
    """The rate drops one point per `step` (or fraction) of AGI over `agi_threshold`, down to `floor_rate`."""

    agi_threshold: ByFilingStatus[Money | None]  # null = ineligible
    step: ByFilingStatus[Money | None]
    floor_rate: Rate


class ChildDependentCareCredit(StrictModel):
    indexed: bool = False
    expense_cap_one: Money
    expense_cap_two_or_more: Money
    max_rate: Rate
    stages: tuple[CareRateStage, ...] = Field(min_length=1)


class Credits(StrictModel):
    child_tax_credit: ChildTaxCredit
    other_dependent_credit: OtherDependentCredit
    education: EducationCredits
    child_dependent_care: ChildDependentCareCredit


class FederalTaxDoc(Document):
    metadata: Metadata
    standard_deduction: StandardDeduction
    senior_deduction: SeniorDeduction
    ordinary_income_brackets: BracketTable
    capital_gains_brackets: BracketTable
    net_investment_income_tax: NetInvestmentIncomeTax
    social_security_taxability: SocialSecurityTaxability
    capital_loss: CapitalLossLimit
    home_sale_exclusion: ByFilingStatus[Money]  # §121 gain exclusion on a principal residence
    fica: Fica
    penalties: Penalties
    dependent_age_tests: DependentAgeTests
    credits: Credits
