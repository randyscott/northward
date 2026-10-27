"""State income tax rules (docs/decisions.md D5): a generic model covering flat and bracketed states, with the common
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
    """The deduction at low incomes."""
    phase_out_start: ByFilingStatus[Money]
    """State income where the reduction begins."""
    phase_out_rate: ByFilingStatus[Rate]
    """Reduction per dollar of state income above the start."""
    head_of_household_floor: Literal["single"] | None = None
    """`single`: head of household never gets less than the single schedule (Wisconsin)."""


class PersonalExemptions(StrictModel):
    """Fixed amounts subtracted per person after the standard deduction."""

    per_person: Money
    """Per member alive during the year."""
    per_dependent: Money = 0.0
    """Per dependent claimed that year."""
    additional_age_65: Money = 0.0
    """Extra per member 65 or older."""
    indexed: bool = False
    """Whether the exemptions grow with inflation."""


class RetirementIncomeExclusion(StrictModel):
    """Per-person subtraction of pensions and traditional-account distributions (including RMDs, inherited IRAs,
    and Roth conversions). Several apply in order, each to the retirement income the earlier ones left."""

    amount: Money
    """The most excluded per qualifying person. Not indexed."""
    min_age: Age
    """A member qualifies from this age (at the end of the year)."""
    agi_limit: ByFilingStatus[Money | None] | None = None
    """Only households with federal AGI below this qualify. Default: no income limit."""
    pooled_for_joint: bool = False
    """On a joint return where both spouses qualify, they share one cap of twice `amount`, whoever received the
    income."""
    bars_credits: bool = False
    """Claiming it forfeits the state's credits that year. It's optional, so the engine takes the lower tax."""


class Plan529Deduction(StrictModel):
    """A subtraction for contributions to 529 plans."""

    cap: Money
    """The most deducted per year, per beneficiary or per return."""
    per: Literal["return", "beneficiary"] = "beneficiary"
    """Whether `cap` applies per beneficiary or per return."""
    married_filing_separately_cap: Money | None = None
    """A different cap for married filing separately. Default: `cap`."""
    indexed: bool = False
    """Whether the cap grows with inflation."""
    rounding: Money = 10
    """An indexed cap is rounded to a multiple of this."""
    carryforward: bool = False
    """Contributions over the cap can be deducted in later years."""


class StateDependentCareCredit(StrictModel):
    """A state care credit computed like the federal one (on federal AGI) with its own caps and rate table."""

    expense_cap_one: Money
    """Expenses counted with one qualifying person."""
    expense_cap_two_or_more: Money
    """Expenses counted with two or more."""
    max_rate: Rate
    """The credit rate at low incomes."""
    agi_threshold: Money
    """Federal AGI where the rate starts falling."""
    step: Money
    """The rate falls one point per `step` (or fraction) of AGI over the threshold."""
    floor_rate: Rate
    """The lowest rate."""


class MarriedCoupleCredit(StrictModel):
    """A share of the lower-earning spouse's earned income, up to a cap (joint returns)."""

    rate: Rate
    """Share of the lower earner's wages."""
    earned_income_cap: Money
    """Wages counted at most."""


class _StateTaxBase(StrictModel):
    indexed: bool = True
    """Whether brackets and standard deductions grow with inflation from the rules' base year."""
    exempt_social_security: bool = True
    """Subtract the federally taxable part of Social Security benefits."""
    capital_gains_exclusion: Rate = 0.0
    """Share of net long-term capital gains excluded."""
    capital_loss_limit: Money | None = None
    """Net capital losses deductible per year, if lower than federal. Default: the federal limit."""
    retirement_income_exclusions: tuple[RetirementIncomeExclusion, ...] = ()
    """Subtractions of pension and retirement-account income, applied in order."""
    subtract_health_premiums: bool = False
    """Subtract health insurance premiums paid with after-tax money (including Medicare and Medigap)."""
    additional_tax_share: Rate = 0.0
    """State tax as a share of the federal early-withdrawal and HSA additional taxes."""
    plan_529_deduction: Plan529Deduction | None = None
    """A subtraction for 529 contributions."""
    standard_deduction: ByFilingStatus[Money] | None = None
    """A fixed standard deduction. Give this or `sliding_standard_deduction`, or neither."""
    sliding_standard_deduction: SlidingStandardDeduction | None = None
    """A standard deduction that shrinks as income rises."""
    personal_exemptions: PersonalExemptions | None = None
    """Amounts subtracted per person."""
    married_couple_credit: MarriedCoupleCredit | None = None
    """A credit for two-earner couples filing jointly."""
    dependent_care_credit: StateDependentCareCredit | None = None
    """A state child and dependent care credit."""

    @model_validator(mode="after")
    def _one_deduction(self) -> _StateTaxBase:
        if self.standard_deduction is not None and self.sliding_standard_deduction is not None:
            raise ValueError("give standard_deduction or sliding_standard_deduction, not both")
        return self


class NoStateTax(StrictModel):
    """No state income tax."""

    kind: Literal["none"]


class FlatStateTax(_StateTaxBase):
    """One rate on all taxable income."""

    kind: Literal["flat"]
    rate: Rate
    """The tax rate, e.g. 0.0495."""


class ProgressiveStateTax(_StateTaxBase):
    """Bracketed rates by filing status."""

    kind: Literal["progressive"]
    brackets: ByFilingStatus[BracketSchedule]
    """For each filing status, [[upper bound of taxable income, rate], ...], ending with [.inf, top rate]."""


StateTaxSystem = Annotated[Union[NoStateTax, FlatStateTax, ProgressiveStateTax], Field(discriminator="kind")]  # noqa: UP007


class StateRules(StrictModel):
    """One state's rules."""

    name: str
    """The state's name."""
    community_property: bool = False
    """A community (or marital) property state: both halves of joint property get a stepped-up basis at the first
    death."""
    sources: tuple[str, ...] = ()
    """Where each figure comes from: forms, instructions, statutes, with links and the date checked."""
    tax: StateTaxSystem
    """The income tax: `kind` is `none`, `flat`, or `progressive`."""


class StateTaxDoc(Document):
    """Income tax rules per state, keyed by code (e.g. "WI"). A household's `state` picks one; "none" is required."""

    base_year: int
    """The tax year the amounts are for. Indexed amounts grow with inflation from here."""
    states: dict[str, StateRules]
    """Rules by state code: `none`, `WI`, ..."""

    @model_validator(mode="after")
    def _check(self) -> StateTaxDoc:
        if "none" not in self.states:
            raise ValueError("states must include 'none' (no state income tax)")
        return self
