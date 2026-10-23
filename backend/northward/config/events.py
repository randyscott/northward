"""Scheduled one-time events: windfalls, home sales, and inheritances (profile `events.yaml` and scenario events)."""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import Field, model_validator

from northward.config.accounts import AssetStrategy
from northward.config.anchors import Anchor
from northward.config.base import Document, Identifier, Money, Rate, StrictModel


class WindfallEvent(StrictModel):
    id: Identifier
    kind: Literal["windfall"]
    description: str | None = None
    when: Anchor
    amount: Money
    dollars: Literal["today", "nominal"] = "today"  # "today": inflated to the event year
    tax_character: Literal["tax_free", "ordinary", "long_term_gain"] = "tax_free"
    owner: Identifier | None = None  # whose income it is, for ordinary windfalls (None: joint)
    deposit_to: Identifier | None = None  # an account; None: cash (then swept)


class HomeSaleEvent(StrictModel):
    """Sale of a home: gain above the §121 exclusion is a long-term gain; an attached mortgage is paid off."""

    id: Identifier
    kind: Literal["home_sale"]
    description: str | None = None
    when: Anchor
    price: Money  # today's dollars, grown by `appreciation`
    appreciation: float | Literal["general"] = "general"  # annual rate, or follow CPI
    cost_basis: Money  # purchase price plus improvements (nominal)
    selling_costs: Rate = 0.06
    pay_off: Identifier | None = None  # a liability id repaid from the proceeds


class InheritanceEvent(StrictModel):
    id: Identifier
    kind: Literal["inheritance"]
    description: str | None = None
    when: Anchor
    amount: Money
    dollars: Literal["today", "nominal"] = "today"
    beneficiary: Identifier  # the member who inherits
    asset: Literal["cash", "brokerage", "inherited_ira"]
    # brokerage: an existing brokerage account to receive it (stepped-up basis); inherited_ira: the new account's id.
    account: Identifier | None = None
    decedent_started_rmds: bool = True  # inherited_ira: annual RMDs in years 1-9 if the decedent had begun them
    asset_strategy: AssetStrategy | None = None  # inherited_ira; default 60/40 static

    @model_validator(mode="after")
    def _check(self) -> InheritanceEvent:
        if self.asset != "cash" and self.account is None:
            raise ValueError(f"an inherited {self.asset} needs `account`")
        return self


Event = Annotated[Union[WindfallEvent, HomeSaleEvent, InheritanceEvent], Field(discriminator="kind")]  # noqa: UP007


class EventsDoc(Document):
    events: tuple[Event, ...] = ()

    @model_validator(mode="after")
    def _check_unique(self) -> EventsDoc:
        ids = [e.id for e in self.events]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"event ids must be unique; duplicated: {', '.join(duplicates)}")
        return self
