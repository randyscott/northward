"""529 withdrawals for qualified education (PLAN.md §4.5) and what happens to money left over afterward."""

from __future__ import annotations

from northward.accounts.state import AccountState
from northward.config.rules.account_types import AccountFamily
from northward.engine.context import SimContext
from northward.engine.results import YearFlows
from northward.engine.state import EngineState
from northward.engine.taxes import build_tax_inputs
from northward.expenses.spending import occurs
from northward.ledger.books import Books
from northward.ledger.transaction import CASH, TaxCategory
from northward.lifecycle.dependents import dependent_status

_EPSILON = 0.005


def _plans_for(books: Books, beneficiary: str) -> list[AccountState]:
    return [
        a
        for a in books.accounts.values()
        if a.family is AccountFamily.EDUCATION_529 and a.beneficiary == beneficiary and a.balance > 0
    ]


def aotc_reserve(
    ctx: SimContext, books: Books, state: EngineState, flows: YearFlows, year: int, beneficiary: str
) -> float:
    """Expenses to leave out of pocket so they can earn the American Opportunity Credit (0 if it's unavailable)."""
    rules = ctx.sim.rules.federal_tax
    dependent = ctx.sim.profile.household.dependent(beneficiary)
    if dependent is None or dependent_status(dependent, rules, year).education_credit != "american_opportunity":
        return 0.0
    inputs = build_tax_inputs(ctx, books, state, flows, year)
    phase_out = rules.credits.education.phase_out.for_status(inputs.filing_status)
    if phase_out is None or ctx.tax.compute(inputs).agi >= phase_out.end:
        return 0.0
    aotc = rules.credits.education.american_opportunity
    return aotc.tier1_expenses + aotc.tier2_expenses


def pay_education(ctx: SimContext, books: Books, state: EngineState, flows: YearFlows, year: int) -> None:
    """Pay each beneficiary's qualified education spending from their 529s, tax-free."""
    for beneficiary, expenses in list(flows.education_expenses.items()):
        plans = _plans_for(books, beneficiary)
        if not plans:
            continue
        need = max(0.0, expenses - aotc_reserve(ctx, books, state, flows, year, beneficiary))
        for plan in plans:
            amount = min(need, plan.balance)
            if amount <= _EPSILON:
                break
            books.move(plan.id, CASH, amount, f"qualified 529 withdrawal ({beneficiary})", TaxCategory.TAX_FREE, amount)
            flows.plan_529_qualified[beneficiary] += amount
            need -= amount


def education_end_year(ctx: SimContext, beneficiary: str) -> int | None:
    """Last year with qualified_education spending for `beneficiary` (None if none is planned)."""
    last = None
    for category in ctx.sim.profile.spending.categories:
        if "qualified_education" not in category.tags or category.beneficiary != beneficiary:
            continue
        for year in ctx.timeline.years:
            if occurs(ctx, category, year):
                last = year if last is None else max(last, year)
    return last


def handle_leftovers(ctx: SimContext, books: Books, state: EngineState, flows: YearFlows, year: int) -> None:
    policy = ctx.sim.scenario.levers.plan_529_leftover
    if policy == "keep":
        return
    for plan in [
        a for a in books.accounts.values() if a.family is AccountFamily.EDUCATION_529 and a.balance > _EPSILON
    ]:
        assert plan.beneficiary is not None
        end = education_end_year(ctx, plan.beneficiary)
        if end is None or year <= end:
            continue
        if policy == "change_beneficiary":
            future = [
                (start, d.id)
                for d in ctx.sim.profile.household.dependents
                if d.id != plan.beneficiary and (e := education_end_year(ctx, d.id)) is not None and e > year
                for start in [_education_start_year(ctx, d.id)]
            ]
            if future:
                plan.beneficiary = min(future)[1]
                state.notes.add(
                    f"529 {plan.id} changed beneficiary to {plan.beneficiary} after the first finished school"
                )
        elif policy == "roth_rollover":
            _roll_to_roth(ctx, books, state, flows, year, plan)
        else:
            earnings = max(0.0, plan.gain_on_withdrawal(plan.balance))
            amount = plan.balance
            books.move(
                plan.id,
                CASH,
                amount,
                f"non-qualified 529 withdrawal ({plan.id})",
                TaxCategory.ORDINARY,
                earnings,
                plan.owner,
            )
            books.move(
                plan.id,
                "irs",
                0.0,
                "non-qualified 529: additional tax base",
                TaxCategory.PLAN_529_NON_QUALIFIED,
                earnings,
                plan.owner,
            )
            flows.plan_529_other += amount


def _education_start_year(ctx: SimContext, beneficiary: str) -> int:
    for year in ctx.timeline.years:
        for category in ctx.sim.profile.spending.categories:
            if (
                "qualified_education" in category.tags
                and category.beneficiary == beneficiary
                and occurs(ctx, category, year)
            ):
                return year
    return ctx.timeline.end_year


def _roll_to_roth(
    ctx: SimContext, books: Books, state: EngineState, flows: YearFlows, year: int, plan: AccountState
) -> None:
    """Roll up to the annual IRA limit (and the lifetime cap) into the beneficiary's own Roth IRA."""
    rules = ctx.sim.rules.contribution_limits.plan_529_roth_rollover
    opened = getattr(plan.config, "opened_year", year)
    if year - opened <= rules.min_account_age_years:
        return
    beneficiary = plan.beneficiary
    assert beneficiary is not None
    used = state.plan_529_rollovers.get(beneficiary, 0.0)
    person = ctx.sim.profile.household.dependent(beneficiary) or ctx.timeline.member(beneficiary)
    annual = ctx.limits.ira(ctx.timeline.age(person, year), year)
    amount = min(plan.balance, rules.lifetime_cap - used, annual)
    if amount <= _EPSILON:
        return
    books.move(
        plan.id,
        f"roth_ira:{beneficiary}",
        amount,
        "529 rollover to the beneficiary's Roth IRA",
        TaxCategory.TAX_FREE,
        amount,
    )
    state.plan_529_rollovers[beneficiary] = used + amount
    flows.plan_529_other += amount
