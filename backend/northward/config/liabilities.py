"""Liabilities: amortizing loans and interest-only debt."""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import Field, field_validator, model_validator

from northward.config.anchors import Anchor
from northward.config.base import Document, Identifier, Money, Rate, StrictModel, also_accepts


class AmortizingLoan(StrictModel):
    """Fixed-payment loan (mortgage, auto). Give either `monthly_payment` or `remaining_term_months`."""

    id: Identifier
    """Shown in results; events can pay the loan off by this id."""
    kind: Literal["amortizing"]
    description: str | None = None
    """A note for yourself."""
    balance: Money
    """The balance owed now."""
    annual_rate: Rate
    """The interest rate, e.g. 0.0425."""
    monthly_payment: Money | None = None
    """The scheduled principal and interest payment (not escrow). Give this or `remaining_term_months`."""
    remaining_term_months: int | None = Field(default=None, gt=0)
    """Months left on the loan; the payment is computed from it. Give this or `monthly_payment`."""
    extra_monthly_payment: Money = 0.0
    """Extra principal paid each month."""

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
    """Shown in results; events can pay the loan off by this id."""
    kind: Literal["interest_only"]
    description: str | None = None
    """A note for yourself."""
    balance: Money
    """The balance owed, repaid in full at `payoff`."""
    annual_rate: Rate
    """The interest rate, e.g. 0.07."""
    payoff: Anchor
    """When the balance is repaid as a lump sum."""


Liability = Annotated[Union[AmortizingLoan, InterestOnlyLoan], Field(discriminator="kind")]  # noqa: UP007


class LiabilitiesDoc(Document):
    """Mortgages and other loans. Payments are made in addition to spending."""

    liabilities: tuple[Liability, ...] = Field((), json_schema_extra=also_accepts({"type": "null"}))
    """Each loan's `kind` is `amortizing` or `interest_only`."""

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
