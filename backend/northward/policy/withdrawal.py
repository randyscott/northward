"""Covering a cash deficit by withdrawing from accounts in the scenario's withdrawal order."""

from __future__ import annotations

from northward.accounts.state import AccountState
from northward.config.base import JOINT_OWNER
from northward.config.rules.account_types import AccountFamily
from northward.engine.context import SimContext
from northward.engine.results import YearFlows
from northward.ledger.books import Books
from northward.ledger.transaction import CASH, TaxCategory

_EPSILON = 0.005


def _penalty_base(ctx: SimContext, account: AccountState, year: int) -> TaxCategory | None:
    """The additional-tax category a withdrawal this year would trigger, if any.

    The penalty age is treated as reached for the whole year it falls in. Inherited accounts are exempt
    (death exception); Roth withdrawals are treated as tax- and penalty-free (basis isn't tracked yet).
    """
    member = ctx.sim.profile.household.member(account.owner)
    if member is None:
        return None
    if account.family is AccountFamily.RETIREMENT and account.bucket == "deferred":
        age = account.type.early_withdrawal_penalty_age
        if age is not None and year < ctx.timeline.reaches(member, age):
            return TaxCategory.EARLY_DISTRIBUTION
    elif account.family is AccountFamily.HSA:
        if year < ctx.timeline.reaches(member, ctx.sim.rules.federal_tax.penalties.hsa_penalty_free_age):
            return TaxCategory.HSA_NON_MEDICAL
    return None


def _accounts_in(books: Books, bucket: str) -> list[AccountState]:
    accounts = [a for a in books.accounts.values() if a.bucket == bucket]
    return sorted(accounts, key=lambda a: not a.is_cash)  # within "taxable", spend cash before selling investments


def reserved(ctx: SimContext, account: AccountState, year: int) -> float:
    """The part of `account`'s balance held back as the scenario's cash reserve this year (nominal dollars)."""
    reserve = ctx.sim.scenario.levers.cash_reserve
    return reserve.amount * ctx.prices.level(year) if reserve is not None and reserve.account == account.id else 0.0


def withdraw(
    ctx: SimContext, books: Books, flows: YearFlows, year: int, needed: float, use_reserve: bool = True
) -> float:
    """Withdraw up to `needed` into cash. Returns the part that couldn't be covered.

    Accounts are drawn in the withdrawal order, leaving the cash reserve in place; the reserve is the last resort
    (unless `use_reserve` is off)."""
    block_early = ctx.sim.scenario.levers.early_withdrawals == "block"
    for bucket in ctx.sim.scenario.levers.withdrawal_order:
        for account in _accounts_in(books, bucket):
            if needed <= _EPSILON:
                return 0.0
            available = account.balance - reserved(ctx, account, year)
            if available <= _EPSILON:
                continue
            penalty = _penalty_base(ctx, account, year)
            if penalty is not None and block_early:
                continue
            amount = min(available, needed)
            _post(books, flows, account, amount, penalty)
            flows.withdrawals[bucket] += amount
            needed -= amount
    reserve = ctx.sim.scenario.levers.cash_reserve
    if reserve is not None and use_reserve and needed > _EPSILON:
        account = books.accounts[reserve.account]
        amount = min(max(0.0, account.balance), needed)
        if amount > _EPSILON:
            _post(books, flows, account, amount, _penalty_base(ctx, account, year))
            flows.withdrawals[account.bucket or "taxable"] += amount
            flows.reserve_drawn += amount
            needed -= amount
    return max(0.0, needed) if needed > _EPSILON else 0.0


def top_up_reserve(ctx: SimContext, books: Books, flows: YearFlows, year: int) -> None:
    """Bring the cash reserve back to its level for this year (it's indexed, and its interest may lag inflation):
    from the year's cash first, then from the other accounts in the withdrawal order, never from the reserve itself.
    Runs after the year's spending is covered, so refilling it never takes priority over spending."""
    reserve = ctx.sim.scenario.levers.cash_reserve
    if reserve is None:
        return
    account = books.accounts[reserve.account]
    gap = reserve.amount * ctx.prices.level(year) - account.balance
    if gap <= _EPSILON:
        return
    from_accounts = gap - min(max(0.0, books.cash), gap)
    unmet = withdraw(ctx, books, flows, year, from_accounts, use_reserve=False) if from_accounts > _EPSILON else 0.0
    amount = gap - unmet
    if amount > _EPSILON:
        books.move(CASH, account.id, amount, "top up the cash reserve")
        flows.reserve_topped_up += amount


def _post(books: Books, flows: YearFlows, account: AccountState, amount: float, penalty: TaxCategory | None) -> None:
    member = None if account.owner == JOINT_OWNER else account.owner
    description = f"withdrawal from {account.id}"
    if account.bucket == "deferred":
        books.move(account.id, CASH, amount, description, TaxCategory.RETIREMENT, amount, member)
    elif account.bucket == "hsa":
        books.move(account.id, CASH, amount, description, TaxCategory.ORDINARY, amount, member)
    elif account.bucket == "roth":
        books.move(account.id, CASH, amount, description, TaxCategory.TAX_FREE, amount, member)
    elif account.basis is not None:
        gain = account.gain_on_withdrawal(amount)
        books.move(account.id, CASH, amount, description, TaxCategory.LONG_TERM_GAIN, gain, member)
        flows.realized_gains += gain
    else:
        books.move(account.id, CASH, amount, description)
    if penalty is not None:
        # A tax-only record (no value moves) carrying the base for the additional tax.
        books.move(account.id, "irs", 0.0, f"{description}: additional tax base", penalty, amount, member)
