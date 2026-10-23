"""One simulated year: the eight lifecycle stages from README §4, in order."""

from __future__ import annotations

from northward.accounts.growth import apply_growth, credit_investment_income
from northward.engine.context import SimContext
from northward.engine.events import process_events
from northward.engine.results import YearFlows, YearState
from northward.engine.state import EngineState
from northward.engine.taxes import settle_taxes
from northward.expenses.debt import LoanState, pay_debts
from northward.expenses.spending import pay_spending
from northward.income.social_security import pay_social_security
from northward.income.streams import pay_streams
from northward.income.wages import pay_salaries
from northward.ledger.books import Books
from northward.ledger.transaction import CASH
from northward.lifecycle.healthcare import pay_healthcare
from northward.lifecycle.survivor import settle_estates
from northward.policy.contributions import make_contributions
from northward.policy.conversions import convert_to_roth, fill_bracket_from_inherited
from northward.policy.plan_529 import handle_leftovers, pay_education
from northward.policy.rmd import take_required_distributions
from northward.policy.sweep import sweep
from northward.policy.withdrawal import top_up_reserve, withdraw

_EPSILON = 0.005


def run_year(ctx: SimContext, books: Books, loans: list[LoanState], state: EngineState, year: int) -> YearState:
    books.start_year(year)
    state.start_balances = {a.id: a.balance for a in books.accounts.values()}
    flows = YearFlows()

    # 1. Estates of members who died last year, moves to another state, and scheduled events (windfalls, home
    #    sales, inheritances, which may open inherited IRAs).
    settle_estates(ctx, books, state, year)
    for move in ctx.sim.scenario.levers.relocations:
        if ctx.timeline.year_of(move.when) == year:
            state.residence = move.state
    process_events(ctx, books, loans, flows, year)

    # 2. Base inflows: wages and payroll elections, Social Security, other income, taxable-account income.
    pay_salaries(ctx, books, state, flows, year)
    pay_social_security(ctx, books, state, flows, year)
    pay_streams(ctx, books, flows, year)
    credit_investment_income(ctx, books, flows, year)

    # 3. Required distributions: lifetime RMDs and inherited-IRA distributions.
    take_required_distributions(ctx, books, state, flows, year)

    # 4. Expenses (529s pay qualified education), contributions, and deficit withdrawals; then the discretionary
    #    bracket-aware moves (inherited-IRA bracket fill, Roth conversions), which need the year's other income.
    pay_spending(ctx, books, state, flows, year)
    pay_healthcare(ctx, books, state, flows, year)
    handle_leftovers(ctx, books, state, flows, year)  # first, so a new beneficiary's costs are paid this year
    pay_education(ctx, books, state, flows, year)
    pay_debts(loans, books, flows, year)
    make_contributions(ctx, books, state, flows, year)
    if books.cash < 0:
        withdraw(ctx, books, flows, year, -books.cash)
    top_up_reserve(ctx, books, flows, year)  # after spending is covered; before taxes, which see what it sold
    fill_bracket_from_inherited(ctx, books, state, flows, year)
    convert_to_roth(ctx, books, state, flows, year)

    # 5. Taxes, settled until withdrawals made to pay them have been taxed too.
    flows.taxes = settle_taxes(ctx, books, state, flows, year)
    if books.cash < -_EPSILON:
        flows.shortfall = -books.cash
        books.move("shortfall", CASH, flows.shortfall, "unfunded spending and taxes")
        state.shortfalls.append((year, flows.shortfall))

    # 6. Surplus sweep.
    sweep(ctx, books, flows, year)

    # 7. Allocation (glide paths) and market growth.
    apply_growth(ctx, books, flows, year)

    # 8. Telemetry.
    state.magi_history[year] = flows.taxes.magi
    state.filing_history[year] = flows.taxes.filing_status
    return YearState(
        year=year,
        ages=ctx.member_ages(year),
        price_level=ctx.prices.level(year),
        flows=flows,
        balances={a.id: a.balance for a in books.accounts.values()},
        liabilities={loan.id: loan.balance for loan in loans},
        cash=books.cash,
        residence=state.residence,
    )
