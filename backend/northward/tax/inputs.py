"""Everything the federal tax calculation needs for one year, independent of how the engine produced it."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from northward.config.base import FilingStatus
from northward.lifecycle.dependents import DependentStatus


@dataclass(frozen=True)
class PersonTaxInput:
    member: str
    age: int
    wages: float  # income-tax wages (after traditional deferrals and cafeteria-plan exclusions); also earned income
    fica_wages: float  # after cafeteria-plan exclusions only
    retirement_income: float = 0.0  # pensions and traditional-account distributions (for state exclusions)


@dataclass(frozen=True)
class TaxInputs:
    year: int
    filing_status: FilingStatus
    people: tuple[PersonTaxInput, ...]
    other_ordinary: float = 0.0  # pensions, taxable retirement withdrawals, other ordinary income
    interest: float = 0.0
    ordinary_dividends: float = 0.0
    qualified_dividends: float = 0.0
    capital_gains: float = 0.0  # this year's net realized long-term gain (negative: a loss)
    capital_loss_carryforward: float = 0.0  # unused losses from earlier years (a positive number)
    social_security: float = 0.0  # gross benefits
    ira_deduction: float = 0.0  # deductible traditional IRA contributions
    early_distribution_base: float = 0.0
    plan_529_non_qualified_base: float = 0.0  # earnings in non-qualified 529 withdrawals
    hsa_non_medical_base: float = 0.0
    dependents: tuple[DependentStatus, ...] = ()
    # Qualified education expenses by beneficiary, net of amounts paid tax-free from a 529.
    education_expenses: Mapping[str, float] = field(default_factory=dict)
    care_expenses: float = 0.0  # dependent-care expenses not reimbursed by the FSA
    state: str = "none"  # state of residence (rules/state_tax.yaml key)
    plan_529_contributions: Mapping[str, float] = field(default_factory=dict)  # by beneficiary, for state deductions
    plan_529_carryforward: Mapping[str, float] = field(default_factory=dict)  # earlier contributions not yet deducted
    health_premiums_after_tax: float = 0.0  # health insurance premiums paid with after-tax money (state subtractions)
    dependent_care_exclusion: float = 0.0  # dependent-care FSA amount excluded from wages
