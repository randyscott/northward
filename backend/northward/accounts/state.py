"""Mutable per-simulation account state built from an account's configuration and its type rule."""

from __future__ import annotations

from northward.config.accounts import Account, BrokerageAccount, CashAccount, Plan529Account
from northward.config.rules.account_types import AccountFamily, AccountType, TaxWrapper
from northward.config.scenario import WithdrawalBucket

_FAMILY_BUCKETS: dict[AccountFamily, WithdrawalBucket | None] = {
    AccountFamily.CASH: "taxable",
    AccountFamily.BROKERAGE: "taxable",
    AccountFamily.HSA: "hsa",
    AccountFamily.EDUCATION_529: None,  # reserved for education; not part of the general withdrawal order
}


class AccountState:
    def __init__(self, config: Account, account_type: AccountType):
        self.config = config
        self.type = account_type
        self.balance = float(config.balance)
        self.owner = config.owner  # a member id or "joint"; changes when a spouse inherits it
        # Average-cost basis for taxable brokerage accounts; contributions to date for 529s.
        self.basis: float | None = (
            float(config.cost_basis) if isinstance(config, (BrokerageAccount, Plan529Account)) else None
        )
        # 529s: the current beneficiary (may change under the leftover policy).
        self.beneficiary: str | None = config.beneficiary if isinstance(config, Plan529Account) else None

    @property
    def id(self) -> str:
        return self.config.id

    @property
    def family(self) -> AccountFamily:
        return self.type.family

    @property
    def is_cash(self) -> bool:
        return isinstance(self.config, CashAccount)

    @property
    def bucket(self) -> WithdrawalBucket | None:
        """Which withdrawal-order bucket the account belongs to."""
        if self.family in _FAMILY_BUCKETS:
            return _FAMILY_BUCKETS[self.family]
        return "roth" if self.type.tax_wrapper is TaxWrapper.ROTH else "deferred"

    def add(self, amount: float, adds_basis: bool = True) -> None:
        self.balance += amount
        if self.basis is not None and adds_basis:
            self.basis += amount

    def remove(self, amount: float) -> None:
        if self.basis is not None and self.balance > 0:
            self.basis -= self.basis * min(amount / self.balance, 1.0)
        self.balance -= amount
        if abs(self.balance) < 1e-9:
            self.balance = 0.0

    def gain_on_withdrawal(self, amount: float) -> float:
        """Realized gain (average cost) if `amount` were withdrawn now; 0 for accounts without basis."""
        if self.basis is None or self.balance <= 0:
            return 0.0
        return amount - self.basis * min(amount / self.balance, 1.0)
