"""Profile goals: what counts as a successful Monte Carlo path, and how legacy is valued (PLAN.md D35, D36)."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from northward.config.anchors import Anchor
from northward.config.base import Document, Money, Rate, StrictModel


class LiquidityFloor(StrictModel):
    """Year-end liquid assets (unswept cash plus cash and brokerage accounts) must stay at or above `amount`."""

    amount: Money  # today's (start-year) dollars
    start: Anchor | None = None  # first year the floor applies (default: the first simulated year)


class SuccessCriteria(StrictModel):
    """A path succeeds when every enabled criterion holds in every simulated year."""

    no_shortfall: bool = True  # spending and taxes are always fully funded...
    shortfall_tolerance: Money = 1.0  # ...ignoring a yearly shortfall up to this many (nominal) dollars
    liquidity_floor: LiquidityFloor | None = None


class Legacy(StrictModel):
    # Income tax rate heirs pay on inherited pre-tax money (traditional retirement accounts and HSAs).
    heirs_tax_rate: Rate = 0.25


class GoalsDoc(Document):
    success: SuccessCriteria = Field(default_factory=SuccessCriteria)
    legacy: Legacy = Field(default_factory=Legacy)

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
