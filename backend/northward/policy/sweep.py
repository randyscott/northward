"""Year-end surplus cash into accounts, in the scenario's priority order."""

from __future__ import annotations

from northward.config.rules.account_types import AccountFamily
from northward.config.scenario import SweepTarget
from northward.engine.context import SimContext
from northward.engine.results import YearFlows
from northward.ledger.books import Books
from northward.ledger.transaction import CASH


def sweep_targets(ctx: SimContext, books: Books) -> tuple[SweepTarget, ...]:
    configured = ctx.sim.scenario.levers.surplus_sweep
    if configured:
        return configured
    for family in (AccountFamily.BROKERAGE, AccountFamily.CASH):
        for account in books.accounts.values():
            if account.family is family and account.type.allows_contributions:
                return (SweepTarget(account=account.id),)
    return ()


def sweep(ctx: SimContext, books: Books, flows: YearFlows, year: int) -> None:
    reserve = ctx.sim.scenario.levers.cash_reserve
    if reserve is not None:  # the cash reserve is refilled first
        account = books.accounts[reserve.account]
        room = min(books.cash, reserve.amount * ctx.prices.level(year) - account.balance)
        if room > 0.005:
            books.move(CASH, account.id, room, "refill the cash reserve")
            flows.swept += room
    for target in sweep_targets(ctx, books):
        if books.cash <= 0.005:
            return
        account = books.accounts[target.account]
        room = books.cash
        if target.up_to_balance is not None:
            room = min(room, max(0.0, target.up_to_balance * ctx.prices.level(year) - account.balance))
        if room > 0.005:
            books.move(CASH, account.id, room, "surplus sweep")
            flows.swept += room
