"""Income streams: salaries (with payroll elections), pensions, and other income."""

from __future__ import annotations

from itertools import pairwise
from typing import Annotated, Literal, Union

from pydantic import Field, model_validator

from northward.config.anchors import Anchor
from northward.config.base import Document, Identifier, Money, Rate, StrictModel


class DependentCareFsaElection(StrictModel):
    annual: Money
    # Optional explicit end; the election also stops at the member's retirement or when no dependent is care-eligible.
    until: Anchor | None = None


def _exactly_one_amount(percent: float | None, amount: float | None, max_: bool) -> None:
    if sum((percent is not None, amount is not None, max_)) != 1:
        raise ValueError("give exactly one of percent, amount, or max: true")


class RetirementDeferral(StrictModel):
    """Employee 401(k)-type deferral into one account. Traditional deferrals reduce taxable wages; Roth don't."""

    account: Identifier
    percent: Rate | None = None  # of gross salary
    amount: Money | None = None  # per year, today's dollars
    max: bool = False  # the indexed elective-deferral limit (less any other deferrals of the same member)
    include_catch_up: bool = False  # add the age 50+ (or 60-63) catch-up when eligible
    # SECURE 2.0: catch-ups must be Roth when prior-year FICA wages exceed the indexed threshold. Required when
    # catch-ups are included and `account` is traditional.
    roth_catch_up_account: Identifier | None = None

    @model_validator(mode="after")
    def _check(self) -> RetirementDeferral:
        _exactly_one_amount(self.percent, self.amount, self.max)
        if self.roth_catch_up_account is not None and not self.include_catch_up:
            raise ValueError("roth_catch_up_account only applies when include_catch_up is true")
        return self


class MatchTier(StrictModel):
    """Employer matches `match` of each dollar deferred, on deferrals up to `up_to` of pay (cumulative)."""

    match: float = Field(ge=0, le=3)
    up_to: Rate


class EmployerMatch(StrictModel):
    account: Identifier  # receives the match (typically the traditional 401(k))
    tiers: tuple[MatchTier, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _check(self) -> EmployerMatch:
        if any(a.up_to >= b.up_to for a, b in pairwise(self.tiers)):
            raise ValueError("match tiers' up_to must increase")
        return self


class HsaElection(StrictModel):
    """Payroll HSA contribution (excluded from income tax and FICA). Employer money counts toward the limit."""

    account: Identifier
    coverage: Literal["self_only", "family"]
    amount: Money | None = None  # employee, per year, today's dollars
    max: bool = False  # the indexed limit for the coverage, less the employer contribution
    include_catch_up: bool = False  # add the age 55+ catch-up when eligible
    employer: Money = 0.0  # per year, today's dollars

    @model_validator(mode="after")
    def _check(self) -> HsaElection:
        _exactly_one_amount(None, self.amount, self.max)
        return self


class PayrollElections(StrictModel):
    retirement_deferrals: tuple[RetirementDeferral, ...] = ()
    employer_match: EmployerMatch | None = None
    hsa: HsaElection | None = None
    dependent_care_fsa: DependentCareFsaElection | None = None

    @model_validator(mode="after")
    def _check(self) -> PayrollElections:
        if sum(d.max for d in self.retirement_deferrals) > 1:
            raise ValueError("only one retirement deferral may use max: true")
        accounts = [d.account for d in self.retirement_deferrals]
        if len(set(accounts)) != len(accounts):
            raise ValueError("each retirement deferral must target a different account")
        return self


class SalaryStream(StrictModel):
    id: Identifier
    owner: Identifier
    type: Literal["salary"]
    amount: Money  # current annual gross
    # Real (above-inflation) raise rate; None uses the scenario's salary growth.
    real_growth_rate: float | None = None
    # When the salary stops; None: the owner's retirement.
    end: Anchor | None = None
    elections: PayrollElections = PayrollElections()


class PensionStream(StrictModel):
    id: Identifier
    owner: Identifier
    type: Literal["pension"]
    annual_amount: Money  # at start, in nominal dollars of the start year
    start: Anchor
    cola: float | Literal["cpi"] = 0.0  # annual increase: a fixed rate, or "cpi"
    survivor_fraction: Rate = 0.0  # share that continues to the surviving spouse


class OtherIncomeStream(StrictModel):
    id: Identifier
    owner: Identifier  # a member id, or "joint"
    type: Literal["other"]
    description: str | None = None
    amount: Money  # annual, in today's dollars
    start: Anchor | None = None
    end: Anchor | None = None
    index: Literal["general", "none"] = "general"
    tax_character: Literal["ordinary", "tax_free"] = "ordinary"


IncomeStream = Annotated[Union[SalaryStream, PensionStream, OtherIncomeStream], Field(discriminator="type")]  # noqa: UP007


class IncomeDoc(Document):
    income_streams: tuple[IncomeStream, ...] = ()

    @model_validator(mode="after")
    def _check_unique(self) -> IncomeDoc:
        ids = [s.id for s in self.income_streams]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"income stream ids must be unique; duplicated: {', '.join(duplicates)}")
        return self
