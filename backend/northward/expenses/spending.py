"""Spending for a year: base amount (phases, retirement change) plus the categories that occur (docs/configuration/spending.md)."""

from __future__ import annotations

from northward.config.spending import BaseSpending, SpendingCategory
from northward.engine.context import SimContext
from northward.engine.results import YearFlows
from northward.engine.state import EngineState
from northward.ledger.books import Books
from northward.ledger.transaction import CASH


def base_amount(ctx: SimContext, base: BaseSpending, year: int) -> float:
    amount = base.amount * ctx.prices.level(year, base.index)
    if base.phases is not None:
        age = ctx.timeline.age(ctx.timeline.member(base.phases.reference), year)
        amount *= next(b.multiplier for b in base.phases.bands if b.until_age is None or age <= b.until_age)
    if year >= ctx.timeline.all_retired_year:
        amount *= 1 + base.retirement_change
    members = ctx.sim.profile.household.members
    if len(members) == 2 and any(ctx.timeline.died_before(m.id, year) for m in members):
        amount *= base.survivor_multiplier
    return amount


def occurs(ctx: SimContext, category: SpendingCategory, year: int) -> bool:
    if category.once is not None:
        return ctx.timeline.year_of(category.once) == year
    window = ctx.timeline.window(category.start, category.end)
    if window is None or not window[0] <= year <= window[1]:
        return False
    return category.every_years is None or (year - window[0]) % category.every_years == 0


def pay_spending(ctx: SimContext, books: Books, state: EngineState, flows: YearFlows, year: int) -> None:
    spending = ctx.sim.profile.spending
    base = base_amount(ctx, spending.base, year)
    books.move(CASH, "spending:base", base, "base spending")
    flows.spending["base"] += base

    dependent_care = 0.0
    for category in spending.categories:
        if not occurs(ctx, category, year):
            continue
        amount = category.amount * ctx.prices.level(year, category.index)
        books.move(CASH, f"spending:{category.id}", amount, category.description or category.id)
        flows.spending[category.id] += amount
        if "dependent_care" in category.tags:
            dependent_care += amount
        if "qualified_education" in category.tags and category.beneficiary is not None:
            flows.education_expenses[category.beneficiary] += amount
    flows.care_spending += dependent_care

    if state.fsa_pool > 0:
        reimbursed = min(state.fsa_pool, dependent_care)
        if reimbursed > 0:
            books.move("dependent_care_fsa", CASH, reimbursed, "dependent-care FSA reimbursement")
        forfeited = state.fsa_pool - reimbursed
        flows.fsa_reimbursed += reimbursed
        flows.fsa_forfeited += forfeited
        if forfeited > 0.005:
            state.fsa_forfeits.append((year, forfeited))
        state.fsa_pool = 0.0
