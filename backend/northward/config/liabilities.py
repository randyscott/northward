"""Liabilities: amortizing loans and interest-only debt."""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import Field, field_validator, model_validator

from northward.config.anchors import Anchor
from northward.config.base import Document, Identifier, Money, Rate, StrictModel, also_accepts


class AmortizingLoan(StrictModel):
    """Fixed-payment loan (mortgage, auto). Give either `monthly_payment` or `remaining_term_months`."""

    id: Identifier
    kind: Literal["amortizing"]
    description: str | None = None
    balance: Money
    annual_rate: Rate
    monthly_payment: Money | None = None
    remaining_term_months: int | None = Field(default=None, gt=0)
    extra_monthly_payment: Money = 0.0

    @model_validator(mode="after")
    def _check_payment(self) -> AmortizingLoan:
        if (self.monthly_payment is None) == (self.remaining_term_months is None):
            raise ValueError("give exactly one of monthly_payment or remaining_term_months")
        if self.monthly_payment is not None and self.balance > 0:
            monthly_interest = self.balance * self.annual_rate / 12
            if self.monthly_payment + self.extra_monthly_payment <= monthly_interest:
                raise ValueError(
                    f"monthly payment {self.monthly_payment:,.2f} doesn't cover monthly interest "
                    f"{monthly_interest:,.2f}, so the loan never pays off"
                )
        return self


class InterestOnlyLoan(StrictModel):
    """Interest-only debt repaid as a lump sum at `payoff`."""

    id: Identifier
    kind: Literal["interest_only"]
    description: str | None = None
    balance: Money
    annual_rate: Rate
    payoff: Anchor


Liability = Annotated[Union[AmortizingLoan, InterestOnlyLoan], Field(discriminator="kind")]  # noqa: UP007


class LiabilitiesDoc(Document):
    liabilities: tuple[Liability, ...] = Field((), json_schema_extra=also_accepts({"type": "null"}))

    @field_validator("liabilities", mode="before")
    @classmethod
    def _none_is_empty(cls, value: object) -> object:
        return () if value is None else value  # `liabilities:` with no entries parses as null

    @model_validator(mode="after")
    def _check_unique(self) -> LiabilitiesDoc:
        ids = [liability.id for liability in self.liabilities]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"liability ids must be unique; duplicated: {', '.join(duplicates)}")
        return self
