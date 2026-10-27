"""Scheduled one-time events: windfalls, home sales, and inheritances (profile `events.yaml` and scenario events)."""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import Field, model_validator

from northward.config.accounts import AssetStrategy
from northward.config.anchors import Anchor
from northward.config.base import Document, Identifier, Money, Rate, StrictModel

_ID = "Shown in results and the ledger."


class WindfallEvent(StrictModel):
    """A one-time receipt: a bonus, a gift, a business sale."""

    id: Identifier = Field(description=_ID)
    kind: Literal["windfall"]
    description: str | None = None
    """A note for yourself."""
    when: Anchor
    """The year it arrives."""
    amount: Money
    """The amount received."""
    dollars: Literal["today", "nominal"] = "today"
    """`today`: grown with inflation to the event year; `nominal`: that year's dollars."""
    tax_character: Literal["tax_free", "ordinary", "long_term_gain"] = "tax_free"
    """How it's taxed."""
    owner: Identifier | None = None
    """Whose income it is, for an ordinary windfall. Default: joint."""
    deposit_to: Identifier | None = None
    """An account to deposit it in. Default: cash, which then pays the year's bills or is swept."""


class HomeSaleEvent(StrictModel):
    """Sale of a home: gain above the §121 exclusion is a long-term gain; an attached mortgage is paid off."""

    id: Identifier = Field(description=_ID)
    kind: Literal["home_sale"]
    description: str | None = None
    """A note for yourself."""
    when: Anchor
    """The year of the sale."""
    price: Money
    """The sale price in today's dollars, grown by `appreciation` to the sale year."""
    appreciation: float | Literal["general"] = "general"
    """Annual price growth: a rate, or `general` to follow inflation."""
    cost_basis: Money
    """Purchase price plus improvements, in actual dollars."""
    selling_costs: Rate = 0.06
    """Commissions and closing costs, as a share of the price."""
    pay_off: Identifier | None = None
    """A liability id repaid from the proceeds, e.g. the mortgage."""


class InheritanceEvent(StrictModel):
    """Money or an IRA inherited from someone outside the household."""

    id: Identifier = Field(description=_ID)
    kind: Literal["inheritance"]
    description: str | None = None
    """A note for yourself."""
    when: Anchor
    """The year it's inherited."""
    amount: Money
    """The value inherited."""
    dollars: Literal["today", "nominal"] = "today"
    """`today`: grown with inflation to the event year; `nominal`: that year's dollars."""
    beneficiary: Identifier
    """The member who inherits."""
    asset: Literal["cash", "brokerage", "inherited_ira"]
    """`cash` (tax-free), `brokerage` (with a stepped-up basis), or `inherited_ira` (opens a new inherited IRA)."""
    account: Identifier | None = None
    """For `brokerage`, an existing brokerage account to receive it; for `inherited_ira`, the new account's id."""
    decedent_started_rmds: bool = True
    """For `inherited_ira`: whether the original owner had started RMDs (then annual RMDs apply in years 1-9)."""
    asset_strategy: AssetStrategy | None = None
    """For `inherited_ira`: how it's invested. Default: 60% stocks, 40% bonds."""

    @model_validator(mode="after")
    def _check(self) -> InheritanceEvent:
        if self.asset != "cash" and self.account is None:
            raise ValueError(f"an inherited {self.asset} needs `account`")
        return self


Event = Annotated[Union[WindfallEvent, HomeSaleEvent, InheritanceEvent], Field(discriminator="kind")]  # noqa: UP007


class EventsDoc(Document):
    """Expected one-time events: windfalls, home sales, and inheritances."""

    events: tuple[Event, ...] = ()
    """Each event's `kind` is `windfall`, `home_sale`, or `inheritance`."""

    @model_validator(mode="after")
    def _check_unique(self) -> EventsDoc:
        ids = [e.id for e in self.events]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"event ids must be unique; duplicated: {', '.join(duplicates)}")
        return self
