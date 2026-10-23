"""Pensions and other (non-salary) income."""

from __future__ import annotations

from northward.config.base import JOINT_OWNER
from northward.config.income import PensionStream
from northward.engine.context import SimContext
from northward.engine.results import YearFlows
from northward.ledger.books import Books
from northward.ledger.transaction import CASH, TaxCategory


def pay_streams(ctx: SimContext, books: Books, flows: YearFlows, year: int) -> None:
    timeline, prices = ctx.timeline, ctx.prices
    for stream in ctx.other_streams:
        if isinstance(stream, PensionStream):
            first = timeline.year_of(stream.start)
            if first is None or year < first:
                continue
            growth = prices.factor(first, year) if stream.cola == "cpi" else (1 + stream.cola) ** (year - first)
            amount, recipient = stream.annual_amount * growth, stream.owner
            if timeline.died_before(stream.owner, year):  # the survivor's share continues, if any
                survivor = timeline.survivor_of(stream.owner)
                if survivor is None or not timeline.alive(survivor.id, year) or stream.survivor_fraction <= 0:
                    continue
                amount, recipient = amount * stream.survivor_fraction, survivor.id
            books.move(f"pension:{stream.id}", CASH, amount, f"{stream.id}", TaxCategory.RETIREMENT, amount, recipient)
            flows.pension_income += amount
        else:
            if not timeline.active(stream.start, stream.end, year):
                continue
            amount = stream.amount * prices.level(year, stream.index)
            category = TaxCategory.ORDINARY if stream.tax_character == "ordinary" else TaxCategory.TAX_FREE
            member = None if stream.owner == JOINT_OWNER else stream.owner
            if member is not None and timeline.died_before(member, year):
                survivor = timeline.survivor_of(member)
                member = survivor.id if survivor is not None else None
            books.move(f"income:{stream.id}", CASH, amount, stream.description or stream.id, category, amount, member)
            flows.other_income += amount
