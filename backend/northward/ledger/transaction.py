"""Immutable records of value moving between the household's cash, its accounts, and the outside world."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

# The household's clearing balance (the README's CashBook). Every other endpoint is an account id or an
# external label such as "employer", "market", "irs", "spending:<category>", or "salary:<stream>".
CASH = "cash"


class TaxCategory(str, Enum):
    """How a transaction's `taxable_amount` enters the tax calculation."""

    NONE = "none"
    WAGES = "wages"  # gross salary: income tax and FICA
    PRE_TAX_DEFERRAL = "pre_tax_deferral"  # traditional 401(k) deferral: excluded from income-tax wages only
    CAFETERIA = "cafeteria"  # payroll HSA and dependent-care FSA: excluded from income-tax and FICA wages
    ORDINARY = "ordinary"  # other ordinary income (windfalls, rentals, HSA non-medical, 529 earnings)
    RETIREMENT = (
        "retirement"  # pensions and traditional-account distributions (ordinary federally; some states exclude)
    )
    INTEREST = "interest"
    ORDINARY_DIVIDEND = "ordinary_dividend"
    QUALIFIED_DIVIDEND = "qualified_dividend"
    LONG_TERM_GAIN = "long_term_gain"  # may be negative (a realized loss)
    TAX_FREE = "tax_free"
    SOCIAL_SECURITY = "social_security"  # gross benefits; the taxable share is computed (Phase 4 pays them)
    IRA_DEDUCTION = "ira_deduction"  # deductible traditional IRA contribution (reduces AGI)
    EARLY_DISTRIBUTION = "early_distribution"  # base for the early-withdrawal additional tax
    PLAN_529_NON_QUALIFIED = "plan_529_non_qualified"  # earnings base for the 529 additional tax
    HSA_NON_MEDICAL = "hsa_non_medical"  # base for the HSA non-medical additional tax
    TAX_PAYMENT = "tax_payment"


@dataclass(frozen=True, slots=True)
class Transaction:
    year: int
    source: str
    dest: str
    amount: float  # value moved; only market growth may be negative
    description: str
    tax_category: TaxCategory = TaxCategory.NONE
    taxable_amount: float = 0.0  # the part that counts for `tax_category`
    member: str | None = None  # the person the tax item belongs to (None: joint / household)
