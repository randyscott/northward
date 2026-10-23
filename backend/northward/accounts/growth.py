"""Investment income of taxable accounts (Stage 2) and market growth of every account (Stage 7)."""

from __future__ import annotations

from northward.accounts.allocation import allocation_for, taxable_income_rates, total_return
from northward.config.base import JOINT_OWNER
from northward.config.rules.account_types import TaxWrapper
from northward.engine.context import SimContext
from northward.engine.results import YearFlows
from northward.ledger.books import Books
from northward.ledger.transaction import TaxCategory


def credit_investment_income(ctx: SimContext, books: Books, flows: YearFlows, year: int) -> None:
    """Taxable accounts' interest and dividends on the start-of-year balance, taxed and reinvested."""
    market = ctx.path.year(year)
    for account in books.accounts.values():
        if account.type.tax_wrapper is not TaxWrapper.TAXABLE or account.balance <= 0:
            continue
        allocation = allocation_for(account, ctx.sim.rules.glide_paths, year)
        rates = taxable_income_rates(account, allocation, market, ctx.sim.market)
        member = None if account.owner == JOINT_OWNER else account.owner
        balance = account.balance
        for category, rate, label in (
            (TaxCategory.QUALIFIED_DIVIDEND, rates.qualified_dividends, "qualified dividends"),
            (TaxCategory.ORDINARY_DIVIDEND, rates.ordinary_dividends, "ordinary dividends"),
            (TaxCategory.INTEREST, rates.interest, "interest"),
        ):
            amount = balance * rate
            if amount != 0:
                books.move("market", account.id, amount, f"{account.id} {label}", category, amount, member)
                flows.investment_income += amount


def apply_growth(ctx: SimContext, books: Books, flows: YearFlows, year: int) -> None:
    """Returns on year-end balances. Taxable accounts grow only by price change; their income was credited."""
    market = ctx.path.year(year)
    for account in books.accounts.values():
        if account.balance <= 0:
            continue
        allocation = allocation_for(account, ctx.sim.rules.glide_paths, year)
        rate = total_return(account, allocation, market)
        if account.type.tax_wrapper is TaxWrapper.TAXABLE:
            rate -= taxable_income_rates(account, allocation, market, ctx.sim.market).total
        growth = account.balance * rate
        if abs(growth) > 1e-9:
            books.move("market", account.id, growth, f"{account.id} market growth", adds_basis=False)
            flows.growth += growth
