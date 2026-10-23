"""Stage 1: scheduled one-time events (windfalls, home sales, inheritances)."""

from __future__ import annotations

from northward.accounts.state import AccountState
from northward.config.accounts import InheritedAccount, StaticAllocation
from northward.config.events import HomeSaleEvent, InheritanceEvent, WindfallEvent
from northward.config.rules.account_types import AccountFamily
from northward.engine.context import SimContext
from northward.engine.results import YearFlows
from northward.expenses.debt import LoanState
from northward.ledger.books import Books
from northward.ledger.transaction import CASH, TaxCategory

_WINDFALL_TAX = {
    "tax_free": TaxCategory.TAX_FREE,
    "ordinary": TaxCategory.ORDINARY,
    "long_term_gain": TaxCategory.LONG_TERM_GAIN,
}
DEFAULT_INHERITED_ALLOCATION = StaticAllocation(kind="static_allocation", stocks=0.6, bonds=0.4)


def process_events(ctx: SimContext, books: Books, loans: list[LoanState], flows: YearFlows, year: int) -> None:
    for event in ctx.sim.events:
        if ctx.timeline.year_of(event.when) != year:
            continue
        source = f"event:{event.id}"
        label = event.description or event.id
        if isinstance(event, WindfallEvent):
            amount = event.amount * (ctx.prices.level(year) if event.dollars == "today" else 1.0)
            category = _WINDFALL_TAX[event.tax_character]
            books.move(source, event.deposit_to or CASH, amount, label, category, amount, event.owner)
            flows.event_inflows += amount
        elif isinstance(event, HomeSaleEvent):
            _sell_home(ctx, books, loans, flows, year, event, source, label)
        else:
            _inherit(ctx, books, flows, year, event, source, label)


def _sell_home(ctx, books, loans, flows, year, event: HomeSaleEvent, source: str, label: str) -> None:
    years = year - ctx.timeline.start_year
    growth = ctx.prices.level(year) if event.appreciation == "general" else (1 + event.appreciation) ** years
    proceeds = event.price * growth * (1 - event.selling_costs)
    status = ctx.sim.profile.household.household.filing_status
    exclusion = ctx.sim.rules.federal_tax.home_sale_exclusion.for_status(status)
    taxable_gain = max(0.0, proceeds - event.cost_basis - exclusion)
    books.move(source, CASH, proceeds, f"{label}: net proceeds", TaxCategory.LONG_TERM_GAIN, taxable_gain)
    flows.event_inflows += proceeds
    if event.pay_off is not None:
        loan = next(loan for loan in loans if loan.id == event.pay_off)
        if loan.balance > 0:
            books.move(CASH, f"liability:{loan.id}", loan.balance, f"{label}: pay off {loan.id}")
            flows.debt_payments += loan.balance
            loan.balance = 0.0


def _inherit(ctx, books: Books, flows: YearFlows, year: int, event: InheritanceEvent, source: str, label: str) -> None:
    amount = event.amount * (ctx.prices.level(year) if event.dollars == "today" else 1.0)
    if event.asset == "cash":
        books.move(source, CASH, amount, label, TaxCategory.TAX_FREE, amount, event.beneficiary)
    elif event.asset == "brokerage":
        books.move(source, event.account, amount, f"{label} (stepped-up basis)")
    else:
        account_type = next(t for t in ctx.sim.rules.account_types.account_types if t.family is AccountFamily.INHERITED)
        config = InheritedAccount(
            id=event.account,
            owner=event.beneficiary,
            type=account_type.name,
            balance=0.0,
            asset_strategy=event.asset_strategy or DEFAULT_INHERITED_ALLOCATION,
            inherited_year=year,
            decedent_started_rmds=event.decedent_started_rmds,
        )
        books.accounts[config.id] = AccountState(config, account_type)
        books.move(source, config.id, amount, label)
    flows.event_inflows += amount
