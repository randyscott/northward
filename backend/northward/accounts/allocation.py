"""Asset allocation for an account in a given year, and the returns and taxable income that follow from it."""

from __future__ import annotations

from typing import NamedTuple

from northward.accounts.state import AccountState
from northward.config.accounts import CashAccount, StaticAllocation, TargetDateStrategy
from northward.config.rules.glide_paths import GlidePath, GlidePathsDoc
from northward.config.rules.market import MarketPreset
from northward.engine.market import MarketYear


class Allocation(NamedTuple):
    stocks: float
    bonds: float
    cash: float


def glide_path_equity(glide_path: GlidePath, strategy: TargetDateStrategy, year: int) -> float:
    """Equity share for `year` (docs/configuration/rules.md), with the account's inline overrides applied."""
    start = strategy.start_equity if strategy.start_equity is not None else glide_path.start_equity
    years_before = strategy.years_before if strategy.years_before is not None else glide_path.years_before
    target = strategy.target_equity if strategy.target_equity is not None else glide_path.target_equity
    post = strategy.post_target if strategy.post_target is not None else glide_path.post_target
    to_target = strategy.target_year - year
    if to_target >= years_before:
        return start
    if to_target >= 0:
        return target + (start - target) * to_target / years_before
    if post is None:
        return target
    since = -to_target
    if since >= post.years_after:
        return post.final_equity
    return target + (post.final_equity - target) * since / post.years_after


def allocation_for(account: AccountState, glide_paths: GlidePathsDoc, year: int) -> Allocation:
    if isinstance(account.config, CashAccount):
        return Allocation(0.0, 0.0, 1.0)
    strategy = account.config.asset_strategy
    if isinstance(strategy, StaticAllocation):
        return Allocation(strategy.stocks, strategy.bonds, strategy.cash)
    glide_path = glide_paths.get(strategy.glide_path)
    assert glide_path is not None  # validated by the loader
    equity = glide_path_equity(glide_path, strategy, year)
    rest = 1 - equity
    return Allocation(equity, rest * glide_path.non_equity.bonds, rest * glide_path.non_equity.cash)


def total_return(account: AccountState, allocation: Allocation, market: MarketYear) -> float:
    if isinstance(account.config, CashAccount) and account.config.interest_rate is not None:
        return account.config.interest_rate
    return allocation.stocks * market.stocks + allocation.bonds * market.bonds + allocation.cash * market.cash


class TaxableIncome(NamedTuple):
    """Annual income of a taxable account per dollar of balance, before it is reinvested."""

    qualified_dividends: float
    ordinary_dividends: float
    interest: float

    @property
    def total(self) -> float:
        return self.qualified_dividends + self.ordinary_dividends + self.interest


def taxable_income_rates(
    account: AccountState, allocation: Allocation, market: MarketYear, preset: MarketPreset
) -> TaxableIncome:
    """Cash accounts pay all of their return as interest; brokerage accounts pay dividends and bond/cash interest."""
    if account.is_cash:
        return TaxableIncome(0.0, 0.0, total_return(account, allocation, market))
    income = preset.taxable_income
    dividends = allocation.stocks * income.stocks.dividend_yield
    interest = allocation.bonds * income.bonds.interest_yield + allocation.cash * market.cash
    qualified = dividends * income.stocks.qualified_fraction
    return TaxableIncome(qualified, dividends - qualified, interest)
