"""Roth conversions and bracket-filling inherited-IRA withdrawals, run after the year's deficit withdrawals so a
fill-to-bracket amount sees all of the year's other income."""

from __future__ import annotations

from northward.accounts.state import AccountState
from northward.config.rules.account_types import AccountFamily, RmdRule, TaxWrapper
from northward.config.scenario import NoConversions
from northward.engine.context import SimContext
from northward.engine.results import YearFlows
from northward.engine.state import EngineState
from northward.engine.taxes import build_tax_inputs
from northward.ledger.books import Books
from northward.ledger.transaction import CASH, TaxCategory
from northward.policy.bracket_fill import room_under_bracket
from northward.policy.rmd import distribute
from northward.policy.withdrawal import _penalty_base

_EPSILON = 0.005


def conversion_pairs(ctx: SimContext, books: Books) -> list[tuple[AccountState, AccountState]]:
    policy = ctx.sim.scenario.levers.roth_conversions
    explicit = getattr(policy, "pairs", ())
    if explicit:
        return [(books.accounts[p.source], books.accounts[p.target]) for p in explicit]

    def retirement(wrapper: TaxWrapper) -> list[AccountState]:
        return [
            a for a in books.accounts.values() if a.family is AccountFamily.RETIREMENT and a.type.tax_wrapper is wrapper
        ]

    pairs = []
    for source in sorted(retirement(TaxWrapper.DEFERRED), key=lambda a: a.type.contribution_limit != "ira"):
        targets = sorted(
            (a for a in retirement(TaxWrapper.ROTH) if a.owner == source.owner),
            key=lambda a: a.type.contribution_limit != "ira",
        )
        if targets:
            pairs.append((source, targets[0]))
    return pairs


def convert_to_roth(ctx: SimContext, books: Books, state: EngineState, flows: YearFlows, year: int) -> None:
    policy = ctx.sim.scenario.levers.roth_conversions
    if isinstance(policy, NoConversions) or not policy.start_year <= year <= policy.end_year:
        return
    if policy.kind == "fixed_amount":
        target = policy.amount * ctx.prices.level(year)
    else:
        target = room_under_bracket(ctx, books, state, flows, year, policy.bracket_rate, policy.respect_phase_outs)
    if target <= 0.5:
        return
    pairs = conversion_pairs(ctx, books)
    if not pairs:
        state.notes.add("Roth conversions were skipped: no traditional account has a Roth account of the same owner")
        return

    withheld_share = 0.0
    if policy.pay_tax_from == "conversion":
        inputs = build_tax_inputs(ctx, books, state, flows, year)
        extra_tax = ctx.tax.compute(inputs, extra_ordinary=target).total - ctx.tax.compute(inputs).total
        withheld_share = min(max(extra_tax / target, 0.0), 1.0)

    remaining = target
    for source, destination in pairs:
        if remaining <= _EPSILON:
            break
        amount = min(remaining, source.balance)
        if amount <= _EPSILON:
            continue
        withheld = amount * withheld_share
        converted = amount - withheld
        books.move(
            source.id, destination.id, converted, "Roth conversion", TaxCategory.RETIREMENT, converted, source.owner
        )
        if withheld > _EPSILON:
            books.move(
                source.id,
                CASH,
                withheld,
                "Roth conversion withheld for tax",
                TaxCategory.RETIREMENT,
                withheld,
                source.owner,
            )
            penalty = _penalty_base(ctx, source, year)
            if penalty is not None:  # the withheld part is a distribution, not a conversion
                books.move(
                    source.id, "irs", 0.0, "withheld conversion: additional tax base", penalty, withheld, source.owner
                )
        flows.roth_conversions += amount
        remaining -= amount


def fill_bracket_from_inherited(ctx: SimContext, books: Books, state: EngineState, flows: YearFlows, year: int) -> None:
    strategy = ctx.sim.scenario.levers.inherited_ira
    if strategy.kind != "fill_bracket" or strategy.bracket_rate is None:
        return
    accounts = [a for a in books.accounts.values() if a.type.rmd_rule is RmdRule.INHERITED_10_YEAR and a.balance > 0]
    if not accounts:
        return
    room = room_under_bracket(ctx, books, state, flows, year, strategy.bracket_rate)
    for account in sorted(accounts, key=lambda a: a.config.inherited_year):  # oldest deadline first
        amount = min(room, account.balance)
        if amount <= _EPSILON:
            break
        distribute(books, account, amount, f"inherited IRA distribution from {account.id} (bracket fill)")
        flows.inherited_distributions += amount
        room -= amount
