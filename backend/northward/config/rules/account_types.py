"""Account type rules: the tax and behavioral definition shared by every account of a given type."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import Field, model_validator

from northward.config.base import Age, Document, Identifier, StrictModel


class AccountFamily(str, Enum):
    """Which account model and behavior an account type uses. Families are code; types are data."""

    RETIREMENT = "retirement"  # 401(k), IRA, Roth variants: invested, individually owned
    HSA = "hsa"
    INHERITED = "inherited"  # inherited IRA subject to the SECURE Act 10-year rule
    BROKERAGE = "brokerage"  # taxable, tracks cost basis
    CASH = "cash"  # checking, savings: interest only
    EDUCATION_529 = "education_529"


class TaxWrapper(str, Enum):
    DEFERRED = "deferred"
    ROTH = "roth"
    HSA = "hsa"
    TAXABLE = "taxable"
    EDUCATION = "education"


class WithdrawalTax(str, Enum):
    ORDINARY_INCOME = "ordinary_income"
    NONE = "none"
    CAPITAL_GAINS = "capital_gains"
    CONDITIONAL_MEDICAL = "conditional_medical"  # tax-free for medical costs; otherwise ordinary (+ penalty before 65)
    CONDITIONAL_EDUCATION = (
        "conditional_education"  # tax-free for qualified education; otherwise earnings taxed + penalty
    )


class RmdRule(str, Enum):
    NONE = "none"
    UNIFORM_LIFETIME = "uniform_lifetime"  # starts at the owner's applicable age from rmd.yaml
    INHERITED_10_YEAR = "inherited_10_year"  # SECURE Act non-eligible designated beneficiary


class OwnershipConstraint(str, Enum):
    INDIVIDUAL_ONLY = "individual_only"
    JOINT_OR_INDIVIDUAL = "joint_or_individual"


# The wrapper and withdrawal treatment each family must use.
_FAMILY_TAX = {
    AccountFamily.HSA: ({TaxWrapper.HSA}, {WithdrawalTax.CONDITIONAL_MEDICAL}),
    AccountFamily.INHERITED: (
        {TaxWrapper.DEFERRED, TaxWrapper.ROTH},
        {WithdrawalTax.ORDINARY_INCOME, WithdrawalTax.NONE},
    ),
    AccountFamily.BROKERAGE: ({TaxWrapper.TAXABLE}, {WithdrawalTax.CAPITAL_GAINS}),
    AccountFamily.CASH: ({TaxWrapper.TAXABLE}, {WithdrawalTax.NONE}),
    AccountFamily.EDUCATION_529: ({TaxWrapper.EDUCATION}, {WithdrawalTax.CONDITIONAL_EDUCATION}),
    AccountFamily.RETIREMENT: (
        {TaxWrapper.DEFERRED, TaxWrapper.ROTH},
        {WithdrawalTax.ORDINARY_INCOME, WithdrawalTax.NONE},
    ),
}


class AccountType(StrictModel):
    name: Identifier
    description: str
    family: AccountFamily
    tax_wrapper: TaxWrapper
    ownership_constraint: OwnershipConstraint
    allows_contributions: bool
    withdrawal_tax: WithdrawalTax
    rmd_rule: RmdRule = RmdRule.NONE
    # Age before which withdrawals incur the early-withdrawal penalty (None: no age-based penalty).
    early_withdrawal_penalty_age: Age | None = None
    # Which annual contribution limit applies (contribution_limits.yaml).
    contribution_limit: Literal["elective_deferral", "ira", "hsa", "none"] = "none"

    @model_validator(mode="after")
    def _check_consistency(self) -> AccountType:
        wrappers, withdrawal_taxes = _FAMILY_TAX[self.family]
        if self.tax_wrapper not in wrappers:
            raise ValueError(f"family {self.family.value} requires tax_wrapper in {sorted(w.value for w in wrappers)}")
        if self.withdrawal_tax not in withdrawal_taxes:
            allowed = sorted(w.value for w in withdrawal_taxes)
            raise ValueError(f"family {self.family.value} requires withdrawal_tax in {allowed}")
        expected_withdrawal = {TaxWrapper.DEFERRED: WithdrawalTax.ORDINARY_INCOME, TaxWrapper.ROTH: WithdrawalTax.NONE}
        if self.tax_wrapper in expected_withdrawal and self.withdrawal_tax is not expected_withdrawal[self.tax_wrapper]:
            raise ValueError(
                f"tax_wrapper {self.tax_wrapper.value} requires withdrawal_tax "
                f"{expected_withdrawal[self.tax_wrapper].value}"
            )
        if self.family is AccountFamily.INHERITED:
            if self.rmd_rule is not RmdRule.INHERITED_10_YEAR:
                raise ValueError("inherited accounts must use rmd_rule inherited_10_year")
            if self.allows_contributions:
                raise ValueError("inherited accounts can't allow contributions")
        elif self.rmd_rule is RmdRule.INHERITED_10_YEAR:
            raise ValueError("rmd_rule inherited_10_year is only valid for the inherited family")
        if self.rmd_rule is RmdRule.UNIFORM_LIFETIME and self.tax_wrapper is not TaxWrapper.DEFERRED:
            raise ValueError("lifetime RMDs apply only to tax-deferred accounts")
        if self.ownership_constraint is OwnershipConstraint.JOINT_OR_INDIVIDUAL and self.family not in (
            AccountFamily.BROKERAGE,
            AccountFamily.CASH,
        ):
            raise ValueError(f"family {self.family.value} accounts must be individually owned")
        return self


class AccountTypesDoc(Document):
    account_types: tuple[AccountType, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_unique(self) -> AccountTypesDoc:
        names = [t.name for t in self.account_types]
        duplicates = sorted({n for n in names if names.count(n) > 1})
        if duplicates:
            raise ValueError(f"account type names must be unique; duplicated: {', '.join(duplicates)}")
        return self

    def get(self, name: str) -> AccountType | None:
        return next((t for t in self.account_types if t.name == name), None)
