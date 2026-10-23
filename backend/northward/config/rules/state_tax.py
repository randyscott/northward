"""State income tax rules (PLAN.md D5): a generic model covering flat and bracketed states, with the common
subtractions (Social Security, capital-gain and retirement exclusions, 529 contributions), fixed or income-phased
standard deductions, personal exemptions, and a few credits."""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import Field, model_validator

from northward.config.base import Age, ByFilingStatus, Document, Money, Rate, StrictModel
from northward.config.rules.federal_tax import BracketSchedule


class SlidingStandardDeduction(StrictModel):
    """A standard deduction that shrinks as state income rises (e.g. Wisconsin)."""

    maximum: ByFilingStatus[Money]
    phase_out_start: ByFilingStatus[Money]  # state income where the reduction begins
    phase_out_rate: ByFilingStatus[Rate]  # reduction per dollar of income above the start
    # Wisconsin: head of household's steeper slope stops once it reaches the single schedule.
    head_of_household_floor: Literal["single"] | None = None


class PersonalExemptions(StrictModel):
    per_person: Money  # each member alive during the year
    per_dependent: Money = 0.0
    additional_age_65: Money = 0.0  # per member 65 or older
    indexed: bool = False


class RetirementIncomeExclusion(StrictModel):
    """Per-person subtraction of pensions and traditional-account distributions (including RMDs, inherited IRAs,
    and Roth conversions). Several apply in order, each to the retirement income the earlier ones left."""

    amount: Money  # per qualifying person
    min_age: Age
    # Only households with federal AGI below this qualify (None: no income limit).
    agi_limit: ByFilingStatus[Money | None] | None = None
    # Joint returns with both spouses qualifying share one 2x cap, whoever received the income.
    pooled_for_joint: bool = False
    # Claiming it forfeits the state's credits that year; it's optional, so the lower tax is taken.
    bars_credits: bool = False


class Plan529Deduction(StrictModel):
    cap: Money  # per beneficiary (or per return)
    per: Literal["return", "beneficiary"] = "beneficiary"
    married_filing_separately_cap: Money | None = None
    indexed: bool = False
    rounding: Money = 10
    carryforward: bool = False  # excess contributions deductible in later years


class StateDependentCareCredit(StrictModel):
    """A state care credit computed like the federal one (on federal AGI) with its own caps and rate table."""

    expense_cap_one: Money
    expense_cap_two_or_more: Money
    max_rate: Rate
    agi_threshold: Money
    step: Money  # one point off the rate per step (or fraction) of AGI over the threshold
    floor_rate: Rate


class MarriedCoupleCredit(StrictModel):
    """A share of the lower-earning spouse's earned income, up to a cap (joint returns)."""

    rate: Rate
    earned_income_cap: Money


class _StateTaxBase(StrictModel):
    indexed: bool = True  # brackets, deductions, and exemptions grow with CPI from the rules' base year
    exempt_social_security: bool = True  # subtract the federally taxable part of benefits
    capital_gains_exclusion: Rate = 0.0  # share of net long-term gains excluded
    capital_loss_limit: Money | None = None  # net losses deductible per year (None: same as federal)
    retirement_income_exclusions: tuple[RetirementIncomeExclusion, ...] = ()
    subtract_health_premiums: bool = False  # after-tax health insurance premiums (incl. Medicare) are subtracted
    additional_tax_share: Rate = 0.0  # state share of the federal early-withdrawal and HSA additional taxes
    plan_529_deduction: Plan529Deduction | None = None
    standard_deduction: ByFilingStatus[Money] | None = None
    sliding_standard_deduction: SlidingStandardDeduction | None = None
    personal_exemptions: PersonalExemptions | None = None
    married_couple_credit: MarriedCoupleCredit | None = None
    dependent_care_credit: StateDependentCareCredit | None = None

    @model_validator(mode="after")
    def _one_deduction(self) -> _StateTaxBase:
        if self.standard_deduction is not None and self.sliding_standard_deduction is not None:
            raise ValueError("give standard_deduction or sliding_standard_deduction, not both")
        return self


class NoStateTax(StrictModel):
    kind: Literal["none"]


class FlatStateTax(_StateTaxBase):
    kind: Literal["flat"]
    rate: Rate


class ProgressiveStateTax(_StateTaxBase):
    kind: Literal["progressive"]
    brackets: ByFilingStatus[BracketSchedule]


StateTaxSystem = Annotated[Union[NoStateTax, FlatStateTax, ProgressiveStateTax], Field(discriminator="kind")]  # noqa: UP007


class StateRules(StrictModel):
    name: str
    # Community / marital property: both halves of joint property get a stepped-up basis at the first death.
    community_property: bool = False
    sources: tuple[str, ...] = ()
    tax: StateTaxSystem


class StateTaxDoc(Document):
    """Income tax rules per state, keyed by code (e.g. "WI"). A household's `state` picks one; "none" is required."""

    base_year: int
    states: dict[str, StateRules]

    @model_validator(mode="after")
    def _check(self) -> StateTaxDoc:
        if "none" not in self.states:
            raise ValueError("states must include 'none' (no state income tax)")
        return self
