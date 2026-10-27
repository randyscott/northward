"""Profile goals: what counts as a successful Monte Carlo path, and how legacy is valued (docs/decisions.md D35, D36)."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from northward.config.anchors import Anchor
from northward.config.base import Document, Money, Rate, StrictModel


class LiquidityFloor(StrictModel):
    """Year-end liquid assets (unswept cash plus cash and brokerage accounts) must stay at or above `amount`."""

    amount: Money
    """The floor, in today's dollars."""
    start: Anchor | None = None
    """The first year the floor applies. Default: the start of the plan."""


class SuccessCriteria(StrictModel):
    """A path succeeds when every enabled criterion holds in every simulated year."""

    no_shortfall: bool = True
    """Fail a path in any year spending and taxes aren't fully paid."""
    shortfall_tolerance: Money = 1.0
    """Ignore a yearly shortfall up to this many dollars (rounding)."""
    liquidity_floor: LiquidityFloor | None = None
    """Fail a path if cash plus brokerage falls below a floor at a year end."""


class Legacy(StrictModel):
    """How the money left at the end is valued."""

    heirs_tax_rate: Rate = 0.25
    """Income tax rate heirs pay on inherited pre-tax money (traditional retirement accounts and HSAs)."""


class GoalsDoc(Document):
    """What counts as success in Monte Carlo, and how legacy is valued. Every scenario of the profile uses it."""

    success: SuccessCriteria = Field(default_factory=SuccessCriteria)
    """The success criteria."""
    legacy: Legacy = Field(default_factory=Legacy)
    """How legacy is valued after tax."""

    def with_overrides(
        self,
        allow_shortfall: bool = False,
        shortfall_tolerance: float | None = None,
        liquidity_floor: float | None = None,
        heirs_tax_rate: float | None = None,
    ) -> GoalsDoc:
        """These goals with one-off changes (CLI flags, API query parameters). A `liquidity_floor` of 0 turns the
        floor off; any other amount keeps the floor's start, if it has one."""
        data: dict[str, Any] = self.model_dump()
        if allow_shortfall:
            data["success"]["no_shortfall"] = False
        if shortfall_tolerance is not None:
            data["success"]["shortfall_tolerance"] = shortfall_tolerance
        if liquidity_floor is not None:
            floor = data["success"]["liquidity_floor"] or {}
            data["success"]["liquidity_floor"] = {**floor, "amount": liquidity_floor} if liquidity_floor else None
        if heirs_tax_rate is not None:
            data["legacy"]["heirs_tax_rate"] = heirs_tax_rate
        return GoalsDoc.model_validate(data)
