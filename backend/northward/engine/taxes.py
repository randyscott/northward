"""Stage 5: turn the year's books into `TaxInputs`, compute the federal return, and settle it."""

from __future__ import annotations

from northward.config.base import FilingStatus
from northward.engine.context import SimContext
from northward.engine.results import YearFlows
from northward.engine.state import EngineState
from northward.ledger.books import Books
from northward.ledger.transaction import CASH, TaxCategory
from northward.lifecycle.dependents import DependentStatus, dependent_status
from northward.policy.withdrawal import withdraw
from northward.tax.federal import TaxReturn
from northward.tax.inputs import PersonTaxInput, TaxInputs

MAX_TAX_ITERATIONS = 25
MAX_GROSS_UP_RATE = 0.6
_EPSILON = 0.005


def dependent_statuses(ctx: SimContext, year: int) -> tuple[DependentStatus, ...]:
    rules = ctx.sim.rules.federal_tax
    return tuple(dependent_status(d, rules, year) for d in ctx.sim.profile.household.dependents)


def filing_status(ctx: SimContext, dependents: tuple[DependentStatus, ...], year: int) -> tuple[FilingStatus, bool]:
    """This year's filing status, and whether a configured HoH/QSS status had to fall back to single.

    After a spouse's death the survivor files jointly for the year of death, then as a qualifying surviving
    spouse for two years if they have a dependent child, then head of household while a dependent remains."""
    household = ctx.sim.profile.household
    status = household.household.filing_status
    any_dependent = any(d.is_dependent for d in dependents)
    dependent_child = any(d.is_dependent and household.dependent(d.id).relationship == "child" for d in dependents)
    widowed = [m for m in household.members if ctx.timeline.died_before(m.id, year)]
    if len(household.members) == 2 and len(widowed) == 1:
        death_year = ctx.timeline.deaths[widowed[0].id].year
        if dependent_child and year <= death_year + 2:
            return FilingStatus.QUALIFYING_SURVIVING_SPOUSE, False
        return (FilingStatus.HEAD_OF_HOUSEHOLD if any_dependent else FilingStatus.SINGLE), False
    if status is FilingStatus.HEAD_OF_HOUSEHOLD and not any_dependent:
        return FilingStatus.SINGLE, True
    if status is FilingStatus.QUALIFYING_SURVIVING_SPOUSE and not dependent_child:
        return FilingStatus.SINGLE, True
    return status, False


def build_tax_inputs(ctx: SimContext, books: Books, state: EngineState, flows: YearFlows, year: int) -> TaxInputs:
    def total(category: TaxCategory) -> float:
        return books.tax_total(category, any_member=True)

    people = []
    for member in ctx.timeline.living_members(year):
        wages = books.tax_total(TaxCategory.WAGES, member.id)
        cafeteria = books.tax_total(TaxCategory.CAFETERIA, member.id)
        deferred = books.tax_total(TaxCategory.PRE_TAX_DEFERRAL, member.id)
        retirement = books.tax_total(TaxCategory.RETIREMENT, member.id)
        age = ctx.timeline.age(member, year)
        people.append(PersonTaxInput(member.id, age, wages - cafeteria - deferred, wages - cafeteria, retirement))
    dependents = dependent_statuses(ctx, year)
    return TaxInputs(
        year=year,
        filing_status=filing_status(ctx, dependents, year)[0],
        people=tuple(people),
        other_ordinary=total(TaxCategory.ORDINARY) + total(TaxCategory.RETIREMENT),
        interest=total(TaxCategory.INTEREST),
        ordinary_dividends=total(TaxCategory.ORDINARY_DIVIDEND),
        qualified_dividends=total(TaxCategory.QUALIFIED_DIVIDEND),
        capital_gains=total(TaxCategory.LONG_TERM_GAIN),
        capital_loss_carryforward=state.capital_loss_carryforward,
        social_security=total(TaxCategory.SOCIAL_SECURITY),
        ira_deduction=total(TaxCategory.IRA_DEDUCTION),
        early_distribution_base=total(TaxCategory.EARLY_DISTRIBUTION),
        plan_529_non_qualified_base=total(TaxCategory.PLAN_529_NON_QUALIFIED),
        hsa_non_medical_base=total(TaxCategory.HSA_NON_MEDICAL),
        dependents=dependents,
        # Expenses paid tax-free from a 529 can't also earn an education credit.
        education_expenses={
            b: max(0.0, e - flows.plan_529_qualified.get(b, 0.0)) for b, e in flows.education_expenses.items()
        },
        care_expenses=max(0.0, flows.care_spending - flows.fsa_reimbursed),
        dependent_care_exclusion=flows.fsa_reimbursed,
        state=state.residence,
        plan_529_contributions=dict(flows.plan_529_contributions),
        plan_529_carryforward=dict(state.state_529_carryforward),
        health_premiums_after_tax=flows.after_tax_health_premiums,
    )


def _settle(books: Books, amount: float) -> float:
    """Pay (or, for refundable credits, receive) `amount`; returns what actually moved."""
    if amount > _EPSILON:
        books.move(CASH, "irs", amount, "federal income tax and FICA", TaxCategory.TAX_PAYMENT, amount)
        return amount
    if amount < -_EPSILON:
        books.move("irs", CASH, -amount, "refundable credits")
        return amount
    return 0.0


def settle_taxes(ctx: SimContext, books: Books, state: EngineState, flows: YearFlows, year: int) -> TaxReturn:
    """Pay the year's tax. If that overdraws cash, withdraw more and re-tax until the change is negligible.

    Each extra withdrawal is grossed up by the tax rate observed on the previous one (a secant step), so
    settlement usually converges in a few rounds even through phase-outs and penalties. A gross-up can overshoot
    by a few dollars; the excess is swept like any other surplus.
    """
    paid = rate = 0.0
    last_total: float | None = None
    last_withdrawn = 0.0
    rounds = 0
    for _ in range(MAX_TAX_ITERATIONS):
        rounds += 1
        inputs = build_tax_inputs(ctx, books, state, flows, year)
        result = ctx.tax.compute(inputs)
        if last_total is not None and last_withdrawn >= 100:
            # Capped: step-wise phase-outs (e.g. $50 of CTC per $1,000) can make small secants misleadingly steep.
            rate = min(max((result.total - last_total) / last_withdrawn, 0.0), MAX_GROSS_UP_RATE)
        paid += _settle(books, result.total - paid)
        if books.cash >= -_EPSILON:
            break
        request = -books.cash / (1 - rate)
        unmet = withdraw(ctx, books, flows, year, request)
        last_total, last_withdrawn = result.total, request - unmet
        if unmet > _EPSILON:
            # Accounts are exhausted: tax what was withdrawn; the remaining deficit is a shortfall.
            inputs = build_tax_inputs(ctx, books, state, flows, year)
            result = ctx.tax.compute(inputs)
            paid += _settle(books, result.total - paid)
            break
    else:
        state.unconverged_tax_years.append(year)
    state.tax_iterations.append(rounds)

    if filing_status(ctx, inputs.dependents, year)[1]:
        configured = ctx.sim.profile.household.household.filing_status
        state.status_fallbacks.append((year, configured, inputs.filing_status))
    state.capital_loss_carryforward = result.capital_loss_carryforward
    state.state_529_carryforward = dict(result.state.plan_529_carryforward)
    return ctx.tax.with_marginal_rate(inputs, result)
