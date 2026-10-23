"""Run a simulation over the whole horizon."""

from __future__ import annotations

from northward.accounts.state import AccountState
from northward.config.loader import SimulationInput
from northward.engine.context import SimContext
from northward.engine.market import MarketPath, deterministic_path
from northward.engine.results import SimulationResult
from northward.engine.state import EngineState
from northward.engine.timeline import Timeline
from northward.engine.year_step import run_year
from northward.expenses.debt import LoanState
from northward.ledger.books import Books


def simulate(
    sim: SimulationInput,
    path: MarketPath | None = None,
    record: bool = True,
    death_ages: dict[str, float] | None = None,
) -> SimulationResult:
    """Simulate `sim` on `path` (default: the deterministic path for the scenario's market preset).

    `record=False` skips the transaction log (for Monte Carlo); year states are always produced. `death_ages`
    replaces the deaths planned by the scenario's mortality lever (a Monte Carlo path's draws).
    """
    timeline = Timeline(sim, death_ages)
    if path is None:
        basis = sim.scenario.market.deterministic_returns
        path = deterministic_path(sim.market, timeline.start_year, len(timeline.years), basis)
    ctx = SimContext.build(sim, path, death_ages)
    account_types = sim.rules.account_types
    books = Books({a.id: AccountState(a, account_types.get(a.type)) for a in sim.profile.accounts}, record=record)
    loans = [LoanState(liability, timeline) for liability in sim.profile.liabilities.liabilities]
    state = EngineState(
        prior_year_fica_wages={s.id: s.amount for s in ctx.salaries}, residence=sim.profile.household.household.state
    )
    starting = {a.id: a.balance for a in books.accounts.values()}

    years = tuple(run_year(ctx, books, loans, state, year) for year in timeline.years)
    reserve = sim.scenario.levers.cash_reserve
    drawn = [y.year for y in years if y.flows.reserve_drawn > 0.005]
    if reserve is not None and drawn:
        total = sum(y.flows.reserve_drawn for y in years)
        state.notes.add(
            f"the cash reserve in {reserve.account} was drawn on in {len(drawn)} year(s) from {drawn[0]} "
            f"({total:,.0f} in all), after every other account was used up"
        )
    return SimulationResult(
        profile=sim.profile_name,
        scenario=sim.scenario_name,
        years=years,
        transactions=tuple(books.transactions),
        warnings=tuple(_warnings(state)),
        starting_balances=starting,
        account_buckets={a.id: a.bucket or "education" for a in books.accounts.values()},
        death_ages=dict(ctx.timeline.death_ages),
    )


def _span(years: list[int]) -> str:
    return f"{years[0]}" if len(years) == 1 else f"{years[0]}-{years[-1]}"


def _warnings(state: EngineState) -> list[str]:
    warnings = []
    if state.fsa_forfeits:
        total = sum(amount for _, amount in state.fsa_forfeits)
        years = [y for y, _ in state.fsa_forfeits]
        warnings.append(
            f"dependent-care FSA: {total:,.0f} forfeited in {_span(years)} because there wasn't enough "
            "dependent_care-tagged spending to reimburse"
        )
    if state.shortfalls:
        total = sum(amount for _, amount in state.shortfalls)
        years = [y for y, _ in state.shortfalls]
        warnings.append(f"spending and taxes of {total:,.0f} couldn't be funded ({len(years)} years from {years[0]})")
    if state.status_fallbacks:
        years = [y for y, _, _ in state.status_fallbacks]
        _, configured, used = state.status_fallbacks[0]
        warnings.append(
            f"filing status {configured.value} needs a qualifying dependent; filed as {used.value} in {_span(years)}"
        )
    warnings.extend(sorted(state.notes))
    if state.unconverged_tax_years:
        warnings.append(f"tax settlement didn't converge in {_span(state.unconverged_tax_years)}")
    return warnings
