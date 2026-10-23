"""The household's books: cash clearing balance, account balances, the transaction log, and yearly tax totals."""

from __future__ import annotations

from collections import defaultdict

from northward.accounts.state import AccountState
from northward.ledger.transaction import CASH, TaxCategory, Transaction


class Books:
    """Every movement of value goes through `move`, which updates balances and records a `Transaction`.

    Tax totals accumulate even when the log is off (Monte Carlo), so taxes can always be computed.
    """

    def __init__(self, accounts: dict[str, AccountState], record: bool = True):
        self.accounts = accounts
        self.cash = 0.0
        self.record = record
        self.transactions: list[Transaction] = []
        self.year = 0
        self._tax_totals: defaultdict[tuple[TaxCategory, str | None], float] = defaultdict(float)

    def start_year(self, year: int) -> None:
        self.year = year
        self._tax_totals.clear()

    def move(
        self,
        source: str,
        dest: str,
        amount: float,
        description: str,
        tax_category: TaxCategory = TaxCategory.NONE,
        taxable_amount: float = 0.0,
        member: str | None = None,
        adds_basis: bool = True,
    ) -> None:
        """Move `amount` from `source` to `dest`. Deposits into basis-tracking accounts add to basis unless
        `adds_basis` is False (price growth). Withdrawals from them remove basis at the average cost."""
        if source == CASH:
            self.cash -= amount
        elif source in self.accounts:
            self.accounts[source].remove(amount)
        if dest == CASH:
            self.cash += amount
        elif dest in self.accounts:
            self.accounts[dest].add(amount, adds_basis=adds_basis)
        if tax_category is not TaxCategory.NONE:
            self._tax_totals[(tax_category, member)] += taxable_amount
        if self.record:
            self.transactions.append(
                Transaction(self.year, source, dest, amount, description, tax_category, taxable_amount, member)
            )

    def tax_total(self, category: TaxCategory, member: str | None = None, *, any_member: bool = False) -> float:
        """This year's taxable total for `category`: for one member (or joint items with None), or everyone."""
        if any_member:
            return sum(v for (c, _), v in self._tax_totals.items() if c is category)
        return self._tax_totals.get((category, member), 0.0)

    def total_assets(self) -> float:
        return self.cash + sum(a.balance for a in self.accounts.values())
