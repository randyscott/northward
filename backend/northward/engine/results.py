"""What a simulation produces: per-year flows and balances, the transaction log, and warnings."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from northward.ledger.transaction import Transaction
from northward.tax.federal import TaxReturn


@dataclass
class YearFlows:
    """Totals for one year, accumulated as the stages run (available even when the ledger isn't recorded)."""

    gross_wages: float = 0.0
    traditional_deferrals: float = 0.0
    roth_deferrals: float = 0.0
    employer_contributions: float = 0.0  # 401(k) match and employer HSA money
    hsa_contributions: float = 0.0  # employee payroll HSA
    fsa_elections: float = 0.0
    fsa_reimbursed: float = 0.0
    fsa_forfeited: float = 0.0
    pension_income: float = 0.0
    social_security: float = 0.0  # benefits to members (own, spousal, child-in-care)
    child_benefits: float = 0.0  # Social Security paid to dependents (their income)
    rmds: float = 0.0
    inherited_distributions: float = 0.0
    roth_conversions: float = 0.0
    event_inflows: float = 0.0
    hsa_medical: float = 0.0  # tax-free HSA reimbursements of medical costs
    after_tax_health_premiums: float = 0.0  # premiums not paid pre-tax or from an HSA (for state subtractions)
    other_income: float = 0.0
    investment_income: float = 0.0  # interest and dividends of taxable accounts
    spending: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    education_expenses: dict[str, float] = field(default_factory=lambda: defaultdict(float))  # by beneficiary
    care_spending: float = 0.0  # dependent_care-tagged spending
    plan_529_qualified: dict[str, float] = field(default_factory=lambda: defaultdict(float))  # by beneficiary
    plan_529_contributions: dict[str, float] = field(default_factory=lambda: defaultdict(float))  # by beneficiary
    plan_529_other: float = 0.0  # rollovers to the beneficiary's Roth and non-qualified withdrawals
    debt_payments: float = 0.0
    contributions: float = 0.0  # scenario (non-payroll) contributions
    withdrawals: dict[str, float] = field(default_factory=lambda: defaultdict(float))  # by withdrawal bucket
    realized_gains: float = 0.0
    taxes: TaxReturn | None = None
    swept: float = 0.0
    reserve_drawn: float = 0.0  # taken from the cash reserve, after every other account was used up
    reserve_topped_up: float = 0.0  # moved into the cash reserve to keep it at its (indexed) level
    shortfall: float = 0.0  # spending and taxes that couldn't be funded
    growth: float = 0.0  # market growth, excluding income already credited

    @property
    def total_spending(self) -> float:
        return sum(self.spending.values())

    @property
    def total_taxes(self) -> float:
        return 0.0 if self.taxes is None else self.taxes.total


@dataclass(frozen=True)
class YearState:
    year: int
    ages: dict[str, int]
    price_level: float  # general price level relative to the start year (divide by it for today's dollars)
    flows: YearFlows
    balances: dict[str, float]  # year-end account balances
    liabilities: dict[str, float]  # year-end loan balances
    cash: float  # unswept cash carried to next year
    residence: str = "none"

    @property
    def total_assets(self) -> float:
        return self.cash + sum(self.balances.values())

    @property
    def total_liabilities(self) -> float:
        return sum(self.liabilities.values())

    @property
    def net_worth(self) -> float:
        return self.total_assets - self.total_liabilities


@dataclass(frozen=True)
class SimulationResult:
    profile: str
    scenario: str
    years: tuple[YearState, ...]
    transactions: tuple[Transaction, ...]  # empty when the ledger wasn't recorded
    warnings: tuple[str, ...]
    starting_balances: dict[str, float]
    # Withdrawal bucket of every account, including ones opened during the run (taxable, deferred, roth, hsa, or
    # education for 529s).
    account_buckets: dict[str, str] = field(default_factory=dict)
    death_ages: dict[str, float] = field(default_factory=dict)  # members who die within the horizon
