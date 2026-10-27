"""Income streams: salaries (with payroll elections), pensions, and other income."""

from __future__ import annotations

from itertools import pairwise
from typing import Annotated, Literal, Union

from pydantic import Field, model_validator

from northward.config.anchors import Anchor
from northward.config.base import Document, Identifier, Money, Rate, StrictModel


class DependentCareFsaElection(StrictModel):
    """Pre-tax dependent-care savings, reimbursing spending tagged dependent_care in the same year."""

    annual: Money
    """Amount set aside per year, in today's dollars. Any excess over that year's dependent_care spending is
    forfeited."""
    until: Anchor | None = None
    """An explicit end. The election also stops at the member's retirement or when no dependent is care-eligible."""


def _exactly_one_amount(percent: float | None, amount: float | None, max_: bool) -> None:
    if sum((percent is not None, amount is not None, max_)) != 1:
        raise ValueError("give exactly one of percent, amount, or max: true")


class RetirementDeferral(StrictModel):
    """Employee 401(k)-type deferral into one account. Traditional deferrals reduce taxable wages; Roth don't."""

    account: Identifier
    """A traditional or Roth 401(k)-type account owned by the salary's owner."""
    percent: Rate | None = None
    """Share of gross salary, e.g. 0.08."""
    amount: Money | None = None
    """Per year, in today's dollars."""
    max: bool = False
    """Defer the indexed elective-deferral limit, less the member's other deferrals."""
    include_catch_up: bool = False
    """Add the age 50+ (or larger age 60-63) catch-up when eligible."""
    roth_catch_up_account: Identifier | None = None
    """Where catch-ups go when SECURE 2.0 requires them to be Roth (prior-year wages over the indexed threshold).
    Required for a traditional account with catch-ups."""

    @model_validator(mode="after")
    def _check(self) -> RetirementDeferral:
        _exactly_one_amount(self.percent, self.amount, self.max)
        if self.roth_catch_up_account is not None and not self.include_catch_up:
            raise ValueError("roth_catch_up_account only applies when include_catch_up is true")
        return self


class MatchTier(StrictModel):
    """Employer matches `match` of each dollar deferred, on deferrals up to `up_to` of pay (cumulative)."""

    match: float = Field(ge=0, le=3)
    """Employer dollars per employee dollar deferred in this tier, e.g. 0.5."""
    up_to: Rate
    """The tier covers deferrals up to this share of pay, counting from the previous tier's `up_to`."""


class EmployerMatch(StrictModel):
    """The employer's matching contribution, always deposited pre-tax."""

    account: Identifier
    """The account that receives the match (typically the traditional 401(k))."""
    tiers: tuple[MatchTier, ...] = Field(min_length=1)
    """Match tiers with increasing `up_to`, e.g. 100% of the first 3% of pay, then 50% of the next 2%."""

    @model_validator(mode="after")
    def _check(self) -> EmployerMatch:
        if any(a.up_to >= b.up_to for a, b in pairwise(self.tiers)):
            raise ValueError("match tiers' up_to must increase")
        return self


class HsaElection(StrictModel):
    """Payroll HSA contribution (excluded from income tax and FICA). Employer money counts toward the limit."""

    account: Identifier
    """The member's HSA."""
    coverage: Literal["self_only", "family"]
    """The HDHP coverage, which sets the limit. With family coverage, spouses share one family limit."""
    amount: Money | None = None
    """Employee contribution per year, in today's dollars."""
    max: bool = False
    """Contribute the indexed limit for the coverage, less the employer contribution."""
    include_catch_up: bool = False
    """Add the age 55+ catch-up when eligible."""
    employer: Money = 0.0
    """The employer's contribution per year, in today's dollars."""

    @model_validator(mode="after")
    def _check(self) -> HsaElection:
        _exactly_one_amount(None, self.amount, self.max)
        return self


class PayrollElections(StrictModel):
    """Contributions taken from pay. They stop when the salary does."""

    retirement_deferrals: tuple[RetirementDeferral, ...] = ()
    """401(k)-type deferrals, one per account. Only one may use `max`."""
    employer_match: EmployerMatch | None = None
    """The employer's matching contribution."""
    hsa: HsaElection | None = None
    """Payroll HSA contributions."""
    dependent_care_fsa: DependentCareFsaElection | None = None
    """A dependent-care FSA election."""

    @model_validator(mode="after")
    def _check(self) -> PayrollElections:
        if sum(d.max for d in self.retirement_deferrals) > 1:
            raise ValueError("only one retirement deferral may use max: true")
        accounts = [d.account for d in self.retirement_deferrals]
        if len(set(accounts)) != len(accounts):
            raise ValueError("each retirement deferral must target a different account")
        return self


class SalaryStream(StrictModel):
    """Wages from a job, with payroll elections. Pays FICA."""

    id: Identifier
    """Shown in results and the ledger."""
    owner: Identifier
    """The member who earns it."""
    type: Literal["salary"]
    amount: Money
    """Current annual gross pay."""
    real_growth_rate: float | None = None
    """Annual raise above inflation. Default: the scenario's `macro.salary_growth`."""
    end: Anchor | None = None
    """When the salary stops. Default: the owner's retirement (prorated by month in that year)."""
    elections: PayrollElections = PayrollElections()
    """Deferrals, employer match, HSA, and dependent-care FSA."""


class PensionStream(StrictModel):
    """A defined-benefit pension, taxed as ordinary income."""

    id: Identifier
    """Shown in results and the ledger."""
    owner: Identifier
    """The member who earned it."""
    type: Literal["pension"]
    annual_amount: Money
    """The annual benefit when it starts, in that year's dollars (not today's)."""
    start: Anchor
    """When payments begin."""
    cola: float | Literal["cpi"] = 0.0
    """Annual increase once it starts: a fixed rate, or `cpi` to follow inflation."""
    survivor_fraction: Rate = 0.0
    """The share that continues to a surviving spouse."""


class OtherIncomeStream(StrictModel):
    """Any other income: rental income, part-time work, gifts. No FICA."""

    id: Identifier
    """Shown in results and the ledger."""
    owner: Identifier
    """A member id, or `joint`."""
    type: Literal["other"]
    description: str | None = None
    """A note for yourself."""
    amount: Money
    """Per year, in today's dollars."""
    start: Anchor | None = None
    """When it starts. Default: the start of the plan."""
    end: Anchor | None = None
    """When it ends (inclusive). Default: the end of the plan."""
    index: Literal["general", "none"] = "general"
    """`general` grows with inflation; `none` stays at a fixed nominal amount."""
    tax_character: Literal["ordinary", "tax_free"] = "ordinary"
    """`ordinary` is taxed as ordinary income."""


IncomeStream = Annotated[Union[SalaryStream, PensionStream, OtherIncomeStream], Field(discriminator="type")]  # noqa: UP007


class IncomeDoc(Document):
    """Salaries (with payroll elections), pensions, and other income. Social Security comes from household.yaml."""

    income_streams: tuple[IncomeStream, ...] = ()
    """Each stream's `type` is `salary`, `pension`, or `other`."""

    @model_validator(mode="after")
    def _check_unique(self) -> IncomeDoc:
        ids = [s.id for s in self.income_streams]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"income stream ids must be unique; duplicated: {', '.join(duplicates)}")
        return self
