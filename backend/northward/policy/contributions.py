"""Scenario (non-payroll) contributions: IRAs (limits, Roth phase-out, deductibility), 529s, and brokerage/cash.

IRA eligibility uses the MAGI known when contributions are made (Stage 4), before deficit withdrawals.
"""

from __future__ import annotations

from collections import defaultdict

from northward.config.base import ByFilingStatus, FilingStatus
from northward.config.rules.account_types import AccountFamily, TaxWrapper
from northward.engine.context import SimContext
from northward.engine.results import YearFlows
from northward.engine.state import EngineState
from northward.engine.taxes import build_tax_inputs
from northward.ledger.books import Books
from northward.ledger.transaction import CASH, TaxCategory


def make_contributions(ctx: SimContext, books: Books, state: EngineState, flows: YearFlows, year: int) -> None:
    contributions = [c for c in ctx.sim.scenario.levers.contributions if ctx.timeline.active(c.start, c.end, year)]
    if not contributions:
        return
    ira_used: defaultdict[str, float] = defaultdict(float)
    to_529: defaultdict[str, float] = defaultdict(float)
    magi = None
    for contribution in contributions:
        account = books.accounts[contribution.account]
        amount = contribution.amount * ctx.prices.level(year, contribution.index)
        if account.type.contribution_limit == "ira":
            if magi is None:
                inputs = build_tax_inputs(ctx, books, state, flows, year)
                magi, status = ctx.tax.compute(inputs).agi, inputs.filing_status
            requested = amount
            amount = min(
                amount, _ira_room(ctx, books, account.owner, year, ira_used, status, magi, account.type.tax_wrapper)
            )
            if amount < requested - 0.5:
                state.notes.add(
                    f"IRA contributions to {account.id} were reduced to fit the limit, earned income, or Roth phase-out"
                )
            if amount <= 0.005:
                continue
            ira_used[account.owner] += amount
            deductible = 0.0
            if account.type.tax_wrapper is TaxWrapper.DEFERRED:
                deductible = amount * _deductible_share(ctx, account.owner, year, status, magi)
                if deductible < amount - 0.5:
                    state.notes.add("some traditional IRA contributions were nondeductible (basis isn't tracked)")
            books.move(
                CASH,
                account.id,
                amount,
                f"contribution to {account.id}",
                TaxCategory.IRA_DEDUCTION,
                deductible,
                account.owner,
            )
        else:
            if account.family is AccountFamily.EDUCATION_529 and account.beneficiary is not None:
                to_529[account.beneficiary] += amount
                flows.plan_529_contributions[account.beneficiary] += amount
            books.move(CASH, account.id, amount, f"contribution to {account.id}")
        flows.contributions += amount

    donors = 2 if ctx.sim.profile.household.household.filing_status is FilingStatus.MARRIED_FILING_JOINTLY else 1
    for beneficiary, total in to_529.items():
        if total > ctx.limits.gift_exclusion(year) * donors:
            state.notes.add(
                f"529 contributions for {beneficiary} exceed the annual gift-tax exclusion (the 5-year election isn't modeled)"
            )


def _earned_income(books: Books, members: list[str]) -> float:
    return sum(books.tax_total(TaxCategory.WAGES, m) for m in members)


def _ira_room(
    ctx: SimContext,
    books: Books,
    owner: str,
    year: int,
    used: defaultdict[str, float],
    status: FilingStatus,
    magi: float,
    wrapper: TaxWrapper,
) -> float:
    member = ctx.timeline.member(owner)
    limit = ctx.limits.ira(ctx.timeline.age(member, year), year) - used[owner]
    household = [m.id for m in ctx.sim.profile.household.members]
    if status is FilingStatus.MARRIED_FILING_JOINTLY:  # spousal IRA: joint compensation, less the other's IRA
        compensation = _earned_income(books, household) - sum(v for m, v in used.items() if m != owner)
    else:
        compensation = _earned_income(books, [owner])
    room = max(0.0, min(limit, compensation - used[owner]))
    if wrapper is TaxWrapper.ROTH:
        rules = ctx.limits.rules.roth_ira_phase_out
        room *= ctx.limits.phase_out_share(
            rules.ranges, status, magi, year, rules.married_filing_separately_indexed, rules.indexed
        )
    return room


def _covered(ctx: SimContext, member: str, year: int) -> bool:
    """Active participant in a workplace plan this year (deferrals or employer match)."""
    return any(
        s.owner == member
        and ctx.timeline.salary_fraction(s, year) > 0
        and (s.elections.retirement_deferrals or s.elections.employer_match is not None)
        for s in ctx.salaries
    )


def _deductible_share(ctx: SimContext, owner: str, year: int, status: FilingStatus, magi: float) -> float:
    rules = ctx.limits.rules.traditional_ira_deduction_phase_out
    if _covered(ctx, owner, year):
        table = rules.contributor_covered
    elif status is FilingStatus.MARRIED_FILING_JOINTLY and any(
        _covered(ctx, m.id, year) for m in ctx.sim.profile.household.members if m.id != owner
    ):
        span = rules.spouse_covered_only
        table = ByFilingStatus(
            married_filing_jointly=span, single=span, married_filing_separately=span, head_of_household=span
        )
    else:
        return 1.0
    return ctx.limits.phase_out_share(table, status, magi, year, rules.married_filing_separately_indexed, rules.indexed)
