"""Loan balances and annual debt service."""

from __future__ import annotations

from northward.config.liabilities import AmortizingLoan, InterestOnlyLoan, Liability
from northward.engine.results import YearFlows
from northward.engine.timeline import Timeline
from northward.ledger.books import Books
from northward.ledger.transaction import CASH


class LoanState:
    def __init__(self, liability: Liability, timeline: Timeline):
        self.config = liability
        self.balance = float(liability.balance)
        self.monthly_rate = liability.annual_rate / 12
        self.payoff_year: int | None = None
        self.payment = 0.0
        if isinstance(liability, AmortizingLoan):
            self.payment = (
                liability.monthly_payment or self._level_payment(liability)
            ) + liability.extra_monthly_payment
        else:
            self.payoff_year = timeline.year_of(liability.payoff)

    def _level_payment(self, loan: AmortizingLoan) -> float:
        n, r = loan.remaining_term_months, self.monthly_rate
        assert n is not None
        return self.balance / n if r == 0 else self.balance * r / (1 - (1 + r) ** -n)

    @property
    def id(self) -> str:
        return self.config.id

    def pay_year(self, year: int) -> float:
        """Pay one year of debt service; returns the total paid."""
        if self.balance <= 0:
            return 0.0
        if isinstance(self.config, InterestOnlyLoan):
            paid = self.balance * self.config.annual_rate
            if self.payoff_year is not None and year >= self.payoff_year:
                paid += self.balance
                self.balance = 0.0
            return paid
        paid = 0.0
        for _ in range(12):
            if self.balance <= 0:
                break
            owed = self.balance * (1 + self.monthly_rate)
            payment = min(self.payment, owed)
            self.balance = owed - payment
            paid += payment
        if self.balance < 0.005:
            self.balance = 0.0
        return paid


def pay_debts(loans: list[LoanState], books: Books, flows: YearFlows, year: int) -> None:
    for loan in loans:
        paid = loan.pay_year(year)
        if paid > 0:
            books.move(CASH, f"liability:{loan.id}", paid, f"{loan.id} payments")
            flows.debt_payments += paid
