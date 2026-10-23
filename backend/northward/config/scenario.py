"""Scenario document: horizon, market preset selection, decision levers, and overrides of profile values."""

from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import BeforeValidator, ConfigDict, Field, WithJsonSchema, model_validator

from northward.config.anchors import Anchor
from northward.config.base import Age, Document, Identifier, Money, Rate, StrictModel, Year, also_accepts
from northward.config.events import Event

ProfileKind = Literal["household", "accounts", "income", "liabilities", "spending", "events", "health_costs", "goals"]
WithdrawalBucket = Literal["taxable", "deferred", "roth", "hsa"]
DEFAULT_WITHDRAWAL_ORDER: tuple[WithdrawalBucket, ...] = ("taxable", "deferred", "roth", "hsa")


class Horizon(StrictModel):
    start_year: Year
    # Simulate until every member has reached this age...
    end_age: int = Field(default=95, ge=50, le=120)
    # ...or until this year, if given.
    end_year: Year | None = None

    @model_validator(mode="after")
    def _check(self) -> Horizon:
        if self.end_year is not None and self.end_year < self.start_year:
            raise ValueError("end_year must not be before start_year")
        return self


class MarketSelection(StrictModel):
    preset: Identifier = "forward_conservative"
    # Dotted-path overrides of preset fields, e.g. {"factors.stocks.mean": 0.06}.
    overrides: dict[str, Any] = {}
    # Deterministic runs use one constant return per asset class: the geometric mean implied by the preset's
    # arithmetic mean and volatility (a typical compounded outcome), or the arithmetic mean itself.
    deterministic_returns: Literal["geometric", "arithmetic"] = "geometric"


class SalaryGrowth(StrictModel):
    real_growth_rate: float = 0.0  # annual raise above inflation


class Macro(StrictModel):
    salary_growth: SalaryGrowth = SalaryGrowth()


class ClaimAge(StrictModel):
    """Social Security claiming age. YAML accepts a whole number (67) or {years, months}."""

    model_config = ConfigDict(json_schema_extra=also_accepts({"type": "integer", "minimum": 62, "maximum": 70}))

    years: int = Field(ge=62, le=70)
    months: int = Field(default=0, ge=0, le=11)

    @model_validator(mode="before")
    @classmethod
    def _from_number(cls, value: Any) -> Any:
        return {"years": value} if isinstance(value, int) else value

    @model_validator(mode="after")
    def _check_max(self) -> ClaimAge:
        if self.years == 70 and self.months:
            raise ValueError("claiming age can't be after 70")
        return self


class NoConversions(StrictModel):
    kind: Literal["none"] = "none"


class ConversionPair(StrictModel):
    source: Identifier  # a traditional (deferred) retirement account
    target: Identifier  # a Roth account of the same owner


class _ConversionWindow(StrictModel):
    start_year: Year
    end_year: Year
    pay_tax_from: Literal["taxable", "conversion"] = "taxable"
    # Which accounts convert into which, in order. Empty: each traditional IRA, then other traditional retirement
    # account, into the same owner's Roth IRA (or Roth 401(k)).
    pairs: tuple[ConversionPair, ...] = ()

    @model_validator(mode="after")
    def _check_window(self) -> _ConversionWindow:
        if self.end_year < self.start_year:
            raise ValueError("end_year must not be before start_year")
        return self


class FixedAmountConversions(_ConversionWindow):
    kind: Literal["fixed_amount"]
    amount: Money  # per year, today's dollars


class FillBracketConversions(_ConversionWindow):
    kind: Literal["fill_bracket"]
    bracket_rate: Rate  # convert up to the top of this ordinary bracket, e.g. 0.22
    # Stop short of MAGI thresholds where credits phase out (and, from Phase 5, ACA/IRMAA thresholds).
    respect_phase_outs: bool = False


RothConversionPolicy = Annotated[
    Union[NoConversions, FixedAmountConversions, FillBracketConversions],  # noqa: UP007
    Field(discriminator="kind"),
]


class Contribution(StrictModel):
    """A recurring non-payroll contribution (IRA, 529, brokerage). Payroll contributions are salary elections."""

    account: Identifier
    amount: Money  # per year, today's dollars
    start: Anchor | None = None
    end: Anchor | None = None
    index: Literal["general", "none"] = "general"


class SweepTarget(StrictModel):
    """Where year-end surplus cash goes, in priority order."""

    account: Identifier  # a brokerage or cash account
    # Fill only up to this balance (today's dollars, indexed), e.g. an emergency reserve. None: no cap.
    up_to_balance: Money | None = None


class CashReserve(StrictModel):
    """An emergency fund kept at `amount` (today's dollars) in `account`. Withdrawals leave it in place until every
    other account in the withdrawal order is used up. Each year, once spending is covered, it's topped back up to its
    inflation-adjusted level: from the year's cash first, then from the other accounts in the withdrawal order."""

    account: Identifier  # a cash or brokerage account
    amount: Money  # today's dollars, indexed with general inflation


class InheritedIraStrategy(StrictModel):
    """How inherited IRAs are drawn down inside the 10-year window (required annual RMDs always apply)."""

    kind: Literal["even", "minimum_then_final", "fill_bracket"] = "even"
    bracket_rate: Rate | None = None  # fill_bracket: withdraw up to the top of this ordinary bracket

    @model_validator(mode="after")
    def _check(self) -> InheritedIraStrategy:
        if (self.kind == "fill_bracket") != (self.bracket_rate is not None):
            raise ValueError("bracket_rate is required for (and only for) kind fill_bracket")
        return self


class NoMortality(StrictModel):
    """Everyone lives to the end of the horizon."""

    kind: Literal["none"] = "none"


class FixedMortality(StrictModel):
    """Deterministic ages at death, e.g. {alex: 88}. Members not listed live to the end of the horizon."""

    kind: Literal["fixed"]
    death_ages: dict[Identifier, Age]


class SampledMortality(StrictModel):
    """Monte Carlo draws each member's age at death from the SSA period life table (by `sex`, or the average of both
    tables), the same draws for every scenario compared. The horizon runs to the last death, past `end_age` if need
    be. A deterministic run uses each member's life expectancy instead."""

    kind: Literal["sampled"]


MortalityPolicy = Annotated[Union[NoMortality, FixedMortality, SampledMortality], Field(discriminator="kind")]  # noqa: UP007


class Relocation(StrictModel):
    when: Anchor
    state: str  # a key in rules/state_tax.yaml


class Levers(StrictModel):
    ss_claim_ages: dict[Identifier, ClaimAge] = {}
    mortality: MortalityPolicy = NoMortality()
    relocations: tuple[Relocation, ...] = ()  # moves to another state, in order
    withdrawal_order: tuple[WithdrawalBucket, ...] = DEFAULT_WITHDRAWAL_ORDER
    # Before 59 1/2 (65 for HSAs): withdraw and pay the additional tax, or skip those accounts.
    early_withdrawals: Literal["allow_with_penalty", "block"] = "allow_with_penalty"
    # Empty: all surplus goes to the first brokerage account (or, if none, the first cash account).
    surplus_sweep: tuple[SweepTarget, ...] = ()
    cash_reserve: CashReserve | None = None
    roth_conversions: RothConversionPolicy = NoConversions()
    inherited_ira: InheritedIraStrategy = InheritedIraStrategy()
    contributions: tuple[Contribution, ...] = ()
    # What happens to a 529 once its beneficiary's qualified_education spending has ended.
    plan_529_leftover: Literal["keep", "change_beneficiary", "roth_rollover", "withdraw"] = "keep"

    @model_validator(mode="after")
    def _check_order(self) -> Levers:
        if sorted(self.withdrawal_order) != sorted(DEFAULT_WITHDRAWAL_ORDER):
            raise ValueError(f"withdrawal_order must list each of {', '.join(DEFAULT_WITHDRAWAL_ORDER)} exactly once")
        return self


# "latest" or a rule set's name, its tax year (PLAN.md D16); `rule_set: 2026` needn't be quoted.
RuleSetName = Annotated[
    str,
    BeforeValidator(lambda v: str(v) if isinstance(v, int) and not isinstance(v, bool) else v),
    WithJsonSchema({"anyOf": [{"type": "string"}, {"type": "integer"}], "description": '"latest" or a tax year'}),
]


class ScenarioDoc(Document):
    description: str | None = None
    rule_set: RuleSetName = "latest"
    horizon: Horizon
    market: MarketSelection = MarketSelection()
    macro: Macro = Macro()
    levers: Levers = Levers()
    events: tuple[Event, ...] = ()  # what-if events, in addition to the profile's events.yaml
    # Per profile document, dotted-path patches applied before validation,
    # e.g. {household: {"members.alex.target_retirement_age": 62}}. List items are addressed by id.
    overrides: dict[ProfileKind, dict[str, Any]] = {}
