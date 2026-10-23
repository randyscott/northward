"""What changes when a member dies: account retitling and basis step-up (settled at the start of the next year)."""

from __future__ import annotations

from northward.config.base import JOINT_OWNER
from northward.config.rules.account_types import AccountFamily
from northward.engine.context import SimContext
from northward.engine.state import EngineState
from northward.ledger.books import Books


def settle_estates(ctx: SimContext, books: Books, state: EngineState, year: int) -> None:
    """For a member who died last year, the surviving spouse takes over every account as their own.

    Retirement accounts and HSAs are treated as the survivor's own (RMDs follow the survivor's age). Taxable
    holdings get a stepped-up basis: all of the deceased's own accounts, and half of joint accounts (all of them
    under community / marital property)."""
    timeline = ctx.timeline
    for member_id, death in timeline.deaths.items():
        if death.year != year - 1:
            continue
        survivor = timeline.survivor_of(member_id)
        if survivor is None or not timeline.alive(survivor.id, year):
            continue
        community = state_rules(ctx, state).community_property
        for account in books.accounts.values():
            stepped_up = account.basis is not None and account.family is AccountFamily.BROKERAGE
            if account.owner == member_id:
                account.owner = survivor.id
                if stepped_up:
                    account.basis = account.balance
            elif account.owner == JOINT_OWNER and stepped_up:
                account.basis = account.balance if community else (account.basis + account.balance) / 2
        state.notes.add(f"{member_id} died in {death.year}; {survivor.id} inherited their accounts in {year}")


def state_rules(ctx: SimContext, state: EngineState):
    """The residence state's tax rules (relocations are applied by the engine each year)."""
    return ctx.sim.rules.state_tax.states[state.residence]
