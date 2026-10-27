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
    """The years simulated."""

    start_year: Year
    """The first simulated year. Balances are as of its start, and "today's dollars" are its dollars."""
    end_age: int = Field(default=95, ge=50, le=120)
    """Simulate until every member has reached this age."""
    end_year: Year | None = None
    """Or simulate until this year instead."""

    @model_validator(mode="after")
    def _check(self) -> Horizon:
        if self.end_year is not None and self.end_year < self.start_year:
            raise ValueError("end_year must not be before start_year")
        return self


class MarketSelection(StrictModel):
    """Market assumptions: a preset from rules/market_assumptions.yaml, with optional changes."""

    preset: Identifier = "forward_conservative"
    """`forward_conservative`, `historical_us`, `pessimistic`, or `bootstrap` (historical years)."""
    overrides: dict[str, Any] = {}
    """Dotted-path changes to preset fields, e.g. {"factors.stocks.mean": 0.06}."""
    deterministic_returns: Literal["geometric", "arithmetic"] = "geometric"
    """The constant return per asset class in deterministic runs: the geometric mean implied by the preset (a typical
    compounded outcome) or the arithmetic mean."""


class SalaryGrowth(StrictModel):
    real_growth_rate: float = 0.0
    """Annual raise above inflation, for salaries that don't set their own."""


class Macro(StrictModel):
    """Economic assumptions outside the market preset."""

    salary_growth: SalaryGrowth = SalaryGrowth()
    """Default salary growth."""


class ClaimAge(StrictModel):
    """Social Security claiming age. YAML accepts a whole number (67) or {years, months}."""

    model_config = ConfigDict(json_schema_extra=also_accepts({"type": "integer", "minimum": 62, "maximum": 70}))

    years: int = Field(ge=62, le=70)
    """Whole years of age, 62-70."""
    months: int = Field(default=0, ge=0, le=11)
    """Extra months, 0-11."""

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
    """No Roth conversions."""

    kind: Literal["none"] = "none"
    """`none`, `fixed_amount`, or `fill_bracket`."""


class ConversionPair(StrictModel):
    source: Identifier
    """A traditional (tax-deferred) retirement account."""
    target: Identifier
    """A Roth account of the same owner."""


class _ConversionWindow(StrictModel):
    start_year: Year
    """The first year to convert."""
    end_year: Year
    """The last year to convert (inclusive)."""
    pay_tax_from: Literal["taxable", "conversion"] = "taxable"
    """Pay the tax from taxable accounts, or withhold it from the conversion (penalized before 59 1/2)."""
    pairs: tuple[ConversionPair, ...] = ()
    """Which accounts convert into which, in order. Default: each traditional IRA, then other traditional account,
    into the same owner's Roth IRA (or Roth 401(k))."""

    @model_validator(mode="after")
    def _check_window(self) -> _ConversionWindow:
        if self.end_year < self.start_year:
            raise ValueError("end_year must not be before start_year")
        return self


class FixedAmountConversions(_ConversionWindow):
    """Convert the same amount each year."""

    kind: Literal["fixed_amount"]
    amount: Money
    """Per year, in today's dollars."""


class FillBracketConversions(_ConversionWindow):
    """Convert enough each year to fill an income tax bracket, after the year's other income."""

    kind: Literal["fill_bracket"]
    bracket_rate: Rate
    """Convert up to the top of this ordinary bracket, e.g. 0.22."""
    respect_phase_outs: bool = False
    """Stop short of income levels where a credit or deduction the household gets starts to phase out (D28)."""


RothConversionPolicy = Annotated[
    Union[NoConversions, FixedAmountConversions, FillBracketConversions],  # noqa: UP007
    Field(discriminator="kind"),
]


class Contribution(StrictModel):
    """A recurring non-payroll contribution (IRA, 529, brokerage). Payroll contributions are salary elections."""

    account: Identifier
    """The account contributed to."""
    amount: Money
    """Per year, in today's dollars."""
    start: Anchor | None = None
    """The first year. Default: the start of the plan."""
    end: Anchor | None = None
    """The last year (inclusive). Default: the end of the plan."""
    index: Literal["general", "none"] = "general"
    """`general` grows with inflation; `none` stays at a fixed nominal amount."""


class SweepTarget(StrictModel):
    """Where year-end surplus cash goes, in priority order."""

    account: Identifier
    """A brokerage or cash account."""
    up_to_balance: Money | None = None
    """Fill only up to this balance (today's dollars), then move to the next target. Default: no cap."""


class CashReserve(StrictModel):
    """An emergency fund kept at `amount` (today's dollars) in `account`. Withdrawals leave it in place until every
    other account in the withdrawal order is used up. Each year, once spending is covered, it's topped back up to its
    inflation-adjusted level: from the year's cash first, then from the other accounts in the withdrawal order."""

    account: Identifier
    """A cash or brokerage account."""
    amount: Money
    """The reserve in today's dollars, grown with inflation."""


class InheritedIraStrategy(StrictModel):
    """How inherited IRAs are drawn down inside the 10-year window (required annual RMDs always apply)."""

    kind: Literal["even", "minimum_then_final", "fill_bracket"] = "even"
    """`even` spreads it over the years left; `minimum_then_final` takes only required amounts until year 10;
    `fill_bracket` withdraws up to a bracket each year."""
    bracket_rate: Rate | None = None
    """For `fill_bracket`: withdraw up to the top of this ordinary bracket, e.g. 0.22."""

    @model_validator(mode="after")
    def _check(self) -> InheritedIraStrategy:
        if (self.kind == "fill_bracket") != (self.bracket_rate is not None):
            raise ValueError("bracket_rate is required for (and only for) kind fill_bracket")
        return self


class NoMortality(StrictModel):
    """Everyone lives to the end of the horizon."""

    kind: Literal["none"] = "none"
    """`none`, `fixed`, or `sampled`."""


class FixedMortality(StrictModel):
    """Deterministic ages at death, e.g. {alex: 88}. Members not listed live to the end of the horizon."""

    kind: Literal["fixed"]
    death_ages: dict[Identifier, Age]
    """Age at death by member id, e.g. {alex: 88}. May be fractional."""


class SampledMortality(StrictModel):
    """Monte Carlo draws each member's age at death from the SSA period life table (by `sex`, or the average of both
    tables), the same draws for every scenario compared. The horizon runs to the last death, past `end_age` if need
    be. A deterministic run uses each member's life expectancy instead."""

    kind: Literal["sampled"]


MortalityPolicy = Annotated[Union[NoMortality, FixedMortality, SampledMortality], Field(discriminator="kind")]  # noqa: UP007


class Relocation(StrictModel):
    """A move to another state."""

    when: Anchor
    """The year of the move."""
    state: str
    """A key in rules/state_tax.yaml."""


class Levers(StrictModel):
    """The decisions a scenario tests."""

    ss_claim_ages: dict[Identifier, ClaimAge] = {}
    """Social Security claiming age by member id: 67, or {years: 67, months: 6}. Default: full retirement age."""
    mortality: MortalityPolicy = NoMortality()
    """Lifespans: `none` (everyone reaches the end of the plan), `fixed` ages, or `sampled` from the life table."""
    relocations: tuple[Relocation, ...] = ()
    """Moves to another state, in order."""
    withdrawal_order: tuple[WithdrawalBucket, ...] = DEFAULT_WITHDRAWAL_ORDER
    """The order accounts are drawn on to cover a shortfall: each of taxable, deferred, roth, and hsa once."""
    early_withdrawals: Literal["allow_with_penalty", "block"] = "allow_with_penalty"
    """Before 59 1/2 (65 for HSAs): withdraw and pay the additional tax, or skip those accounts."""
    surplus_sweep: tuple[SweepTarget, ...] = ()
    """Where leftover cash is invested, in order. Default: the first brokerage account (else the first cash
    account)."""
    cash_reserve: CashReserve | None = None
    """An emergency fund that withdrawals leave alone until everything else is used up."""
    roth_conversions: RothConversionPolicy = NoConversions()
    """Roth conversions: `none`, `fixed_amount`, or `fill_bracket`."""
    inherited_ira: InheritedIraStrategy = InheritedIraStrategy()
    """How inherited IRAs are drawn down within the 10-year window."""
    contributions: tuple[Contribution, ...] = ()
    """Recurring contributions outside payroll: IRAs, 529s, brokerage."""
    plan_529_leftover: Literal["keep", "change_beneficiary", "roth_rollover", "withdraw"] = "keep"
    """What happens to a 529 once its beneficiary's qualified_education spending has ended."""

    @model_validator(mode="after")
    def _check_order(self) -> Levers:
        if sorted(self.withdrawal_order) != sorted(DEFAULT_WITHDRAWAL_ORDER):
            raise ValueError(f"withdrawal_order must list each of {', '.join(DEFAULT_WITHDRAWAL_ORDER)} exactly once")
        return self


# "latest" or a rule set's name, its tax year (docs/decisions.md D16); `rule_set: 2026` needn't be quoted.
RuleSetName = Annotated[
    str,
    BeforeValidator(lambda v: str(v) if isinstance(v, int) and not isinstance(v, bool) else v),
    WithJsonSchema({"anyOf": [{"type": "string"}, {"type": "integer"}], "description": '"latest" or a tax year'}),
]


class ScenarioDoc(Document):
    """One plan for the profile: horizon, market assumptions, decisions (levers), and what-if changes."""

    description: str | None = None
    """What the scenario tests, shown in listings."""
    rule_set: RuleSetName = "latest"
    """The rules to use: `latest`, or a tax year such as 2026 to keep results fixed when new rules arrive."""
    horizon: Horizon
    """The years simulated."""
    market: MarketSelection = MarketSelection()
    """Market assumptions."""
    macro: Macro = Macro()
    """Economic assumptions outside the market preset."""
    levers: Levers = Levers()
    """The decisions being tested."""
    events: tuple[Event, ...] = ()
    """What-if events, in addition to the profile's events.yaml."""
    overrides: dict[ProfileKind, dict[str, Any]] = {}
    """Changes to profile documents for this scenario only, as dotted paths per document, e.g.
    {household: {"members.alex.target_retirement_age": 62}}. List items are addressed by id."""
