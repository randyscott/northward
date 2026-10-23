"""Required distributions: lifetime RMDs and the inherited-IRA 10-year rule (Stage 3)."""

from __future__ import annotations

from northward.accounts.state import AccountState
from northward.config.accounts import InheritedAccount
from northward.config.rules.account_types import RmdRule
from northward.engine.context import SimContext
from northward.engine.results import YearFlows
from northward.engine.state import EngineState
from northward.ledger.books import Books
from northward.ledger.transaction import CASH, TaxCategory


def lifetime_rmd(ctx: SimContext, account: AccountState, state: EngineState, year: int) -> float:
    """Uniform Lifetime RMD for `year`, from the prior year-end balance."""
    member = ctx.timeline.member(account.owner)
    rmd = ctx.sim.rules.rmd
    if year < ctx.timeline.reaches(member, rmd.applicable_age(member.birth_year, member.birth_month)):
        return 0.0
    if account.type.contribution_limit == "elective_deferral" and _still_working(ctx, account.owner, year):
        return 0.0  # employer plans: delayed until retirement (non-5% owners)
    return state.start_balances.get(account.id, 0.0) / rmd.uniform_divisor(ctx.timeline.age(member, year))


def inherited_minimum(ctx: SimContext, account: AccountState, state: EngineState, year: int) -> float:
    """Required inherited-IRA distribution: annual RMDs in years 1-9 (if the decedent had begun RMDs),
    and everything by the end of the 10th year after death."""
    config = account.config
    assert isinstance(config, InheritedAccount)
    rules = ctx.sim.rules.rmd.inherited_10_year
    start_balance = state.start_balances.get(account.id, 0.0)
    years_after = year - config.inherited_year
    if years_after <= 0:
        return 0.0
    if years_after >= rules.distribution_years:
        return account.balance
    if not (config.decedent_started_rmds and rules.annual_rmds_if_decedent_started):
        return 0.0
    member = ctx.timeline.member(account.owner)
    first_age = ctx.timeline.age(member, config.inherited_year + 1)
    life_expectancy = ctx.sim.rules.rmd.single_life_expectancy(first_age) - (years_after - 1)
    return start_balance / max(life_expectancy, 1.0)


def inherited_planned(ctx: SimContext, account: AccountState, state: EngineState, year: int) -> float:
    """Distribution for the scenario's strategy (fill_bracket strategies top this up after Stage 4)."""
    minimum = inherited_minimum(ctx, account, state, year)
    config = account.config
    assert isinstance(config, InheritedAccount)
    if ctx.sim.scenario.levers.inherited_ira.kind != "even":
        return minimum
    remaining_years = config.inherited_year + ctx.sim.rules.rmd.inherited_10_year.distribution_years - year + 1
    if year <= config.inherited_year or remaining_years <= 0:
        return minimum
    return max(minimum, state.start_balances.get(account.id, 0.0) / remaining_years)


def take_required_distributions(ctx: SimContext, books: Books, state: EngineState, flows: YearFlows, year: int) -> None:
    for account in list(books.accounts.values()):
        rule = account.type.rmd_rule
        if rule is RmdRule.UNIFORM_LIFETIME:
            amount, label = lifetime_rmd(ctx, account, state, year), "RMD"
        elif rule is RmdRule.INHERITED_10_YEAR:
            amount, label = inherited_planned(ctx, account, state, year), "inherited IRA distribution"
        else:
            continue
        amount = min(amount, account.balance)
        if amount <= 0.005:
            continue
        distribute(books, account, amount, f"{label} from {account.id}")
        if rule is RmdRule.UNIFORM_LIFETIME:
            flows.rmds += amount
        else:
            flows.inherited_distributions += amount


def distribute(books: Books, account: AccountState, amount: float, description: str) -> None:
    """A taxable distribution from a deferred account into cash (no early-withdrawal penalty: required or inherited)."""
    books.move(account.id, CASH, amount, description, TaxCategory.RETIREMENT, amount, account.owner)


def _still_working(ctx: SimContext, member_id: str, year: int) -> bool:
    return any(s.owner == member_id and ctx.timeline.salary_fraction(s, year) > 0 for s in ctx.salaries)
