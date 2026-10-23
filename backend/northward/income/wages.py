"""Salaries and their payroll elections: 401(k) deferrals, employer match, HSA, and dependent-care FSA."""

from __future__ import annotations

from collections import defaultdict

from northward.config.income import SalaryStream
from northward.config.rules.account_types import TaxWrapper
from northward.engine.context import SimContext
from northward.engine.results import YearFlows
from northward.engine.state import EngineState
from northward.ledger.books import Books
from northward.ledger.transaction import CASH, TaxCategory


def pay_salaries(ctx: SimContext, books: Books, state: EngineState, flows: YearFlows, year: int) -> None:
    # The elective-deferral limit and catch-up are per person, across all of a member's employers.
    used_limit: defaultdict[str, float] = defaultdict(float)
    used_catch_up: defaultdict[str, float] = defaultdict(float)
    # If either spouse has family HSA coverage, both are treated as family and split one family limit equally.
    electing = {s.owner for s in ctx.salaries if s.elections.hsa and ctx.timeline.salary_fraction(s, year) > 0}
    family = any(s.elections.hsa.coverage == "family" for s in ctx.salaries if s.elections.hsa and s.owner in electing)
    hsa_share = 1 / len(electing) if family and electing else 1.0
    for stream in ctx.salaries:
        _pay_salary(ctx, books, state, flows, year, stream, used_limit, used_catch_up, family, hsa_share)


def _pay_salary(
    ctx: SimContext,
    books: Books,
    state: EngineState,
    flows: YearFlows,
    year: int,
    stream: SalaryStream,
    used_limit: defaultdict[str, float],
    used_catch_up: defaultdict[str, float],
    hsa_family: bool = False,
    hsa_share: float = 1.0,
) -> None:
    timeline, prices, limits = ctx.timeline, ctx.prices, ctx.limits
    fraction = timeline.salary_fraction(stream, year)
    if fraction <= 0:
        state.prior_year_fica_wages[stream.id] = 0.0
        return
    start, owner = timeline.start_year, stream.owner
    real = stream.real_growth_rate
    if real is None:
        real = ctx.sim.scenario.macro.salary_growth.real_growth_rate
    gross = stream.amount * prices.factor(start, year) * (1 + real) ** (year - start) * fraction
    books.move(f"salary:{stream.id}", CASH, gross, f"{stream.id} gross pay", TaxCategory.WAGES, gross, owner)
    flows.gross_wages += gross

    elections = stream.elections
    age = timeline.age(timeline.member(owner), year)

    # HSA and FSA first: they're fixed elections, and deferrals can't exceed what's left of pay.
    hsa_employee = 0.0
    if elections.hsa is not None:
        hsa = elections.hsa
        coverage = "family" if hsa_family else hsa.coverage
        catch_up = limits.hsa(coverage, age, year) - limits.hsa(coverage, 0, year)
        # Enrolling in Medicare (at 65) ends HSA eligibility: prorate to the months before.
        medicare = timeline.point_at_age(owner, ctx.sim.rules.healthcare.medicare.eligibility_age)
        eligible = 1.0 if year < medicare.year else (medicare.fraction if year == medicare.year else 0.0)
        limit = (limits.hsa(coverage, 0, year) * hsa_share + catch_up) * min(fraction, eligible)
        employer = min(prices.indexed(hsa.employer, start, year) * fraction, limit)
        room = limit - employer
        hsa_employee = room if hsa.max else min(prices.indexed(hsa.amount or 0.0, start, year) * fraction, room)
        if hsa_employee > 0:
            books.move(CASH, hsa.account, hsa_employee, "payroll HSA", TaxCategory.CAFETERIA, hsa_employee, owner)
        if employer > 0:
            books.move("employer", hsa.account, employer, "employer HSA contribution")
        flows.hsa_contributions += hsa_employee
        flows.employer_contributions += employer

    fsa_amount = 0.0
    fsa = elections.dependent_care_fsa
    if fsa is not None and _fsa_active(ctx, year, fsa.until):
        fsa_amount = fsa.annual * fraction
        books.move(
            CASH,
            "dependent_care_fsa",
            fsa_amount,
            "dependent-care FSA election",
            TaxCategory.CAFETERIA,
            fsa_amount,
            owner,
        )
        flows.fsa_elections += fsa_amount
        state.fsa_pool += fsa_amount

    # Deferrals: fixed ones first, then a `max` deferral fills whatever limit remains.
    limit_room = max(0.0, limits.elective_deferral(year) * fraction - used_limit[owner])
    catch_up_room = max(0.0, limits.deferral_catch_up(age, year) * fraction - used_catch_up[owner])
    roth_catch_up = limits.roth_catch_up_required(state.prior_year_fica_wages.get(stream.id, stream.amount), year)
    pay_left = max(0.0, gross - hsa_employee - fsa_amount)
    employee_total = regular_total = 0.0
    for deferral in sorted(elections.retirement_deferrals, key=lambda d: d.max):
        if deferral.percent is not None:
            requested = deferral.percent * gross
        elif deferral.amount is not None:
            requested = prices.indexed(deferral.amount, start, year) * fraction
        else:
            requested = limit_room + (catch_up_room if deferral.include_catch_up else 0.0)
        requested = min(requested, pay_left)
        regular = min(requested, limit_room)
        catch_up = min(requested - regular, catch_up_room) if deferral.include_catch_up else 0.0
        limit_room -= regular
        catch_up_room -= catch_up
        pay_left -= regular + catch_up
        used_limit[owner] += regular
        used_catch_up[owner] += catch_up
        employee_total += regular + catch_up
        regular_total += regular
        catch_up_account = deferral.account
        if deferral.roth_catch_up_account is not None and roth_catch_up:
            catch_up_account = deferral.roth_catch_up_account
        if catch_up_account == deferral.account:
            _post_deferral(books, flows, deferral.account, regular + catch_up, owner, "401(k) deferral")
        else:
            _post_deferral(books, flows, deferral.account, regular, owner, "401(k) deferral")
            _post_deferral(books, flows, catch_up_account, catch_up, owner, "401(k) catch-up (Roth required)")

    if elections.employer_match is not None and employee_total > 0:
        deferral_rate = employee_total / gross
        match, floor = 0.0, 0.0
        for tier in elections.employer_match.tiers:
            match += tier.match * max(0.0, min(deferral_rate, tier.up_to) - floor) * gross
            floor = tier.up_to
        # §415(c): employee deferrals (excluding catch-ups) plus employer additions are capped.
        match = min(match, max(0.0, limits.annual_additions(year) * fraction - regular_total))
        if match > 0:
            books.move("employer", elections.employer_match.account, match, "employer 401(k) match")
            flows.employer_contributions += match

    state.prior_year_fica_wages[stream.id] = gross - hsa_employee - fsa_amount


def _post_deferral(
    books: Books, flows: YearFlows, account_id: str, amount: float, owner: str, description: str
) -> None:
    if amount <= 0:
        return
    if books.accounts[account_id].type.tax_wrapper is TaxWrapper.DEFERRED:
        books.move(CASH, account_id, amount, description, TaxCategory.PRE_TAX_DEFERRAL, amount, owner)
        flows.traditional_deferrals += amount
    else:
        books.move(CASH, account_id, amount, f"Roth {description}")
        flows.roth_deferrals += amount


def _fsa_active(ctx: SimContext, year: int, until) -> bool:
    if until is not None:
        last = ctx.timeline.year_of(until)
        if last is not None and year > last:
            return False
    care_under = ctx.sim.rules.federal_tax.dependent_age_tests.care_under_age
    return any(d.disabled or ctx.timeline.age(d, year) < care_under for d in ctx.sim.profile.household.dependents)
