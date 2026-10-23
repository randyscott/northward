"""Account instances. Each account's `type` names an account-type rule, whose `family` selects the model here."""

from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import Field, TypeAdapter, ValidationError, model_validator

from northward.config.base import (
    ConfigIssue,
    Document,
    Identifier,
    Money,
    Rate,
    StrictModel,
    Year,
    issues_from_validation_error,
)
from northward.config.rules.account_types import AccountFamily, AccountTypesDoc
from northward.config.rules.glide_paths import PostTarget


class TargetDateStrategy(StrictModel):
    """Allocation follows a glide path toward `target_year`. Glide path fields may be overridden inline."""

    kind: Literal["target_date"]
    target_year: Year
    glide_path: Identifier = "linear_default"
    start_equity: Rate | None = None
    years_before: int | None = Field(default=None, gt=0)
    target_equity: Rate | None = None
    post_target: PostTarget | None = None


class StaticAllocation(StrictModel):
    kind: Literal["static_allocation"]
    stocks: Rate
    bonds: Rate
    cash: Rate = 0.0

    @model_validator(mode="after")
    def _check_sum(self) -> StaticAllocation:
        total = self.stocks + self.bonds + self.cash
        if abs(total - 1) > 1e-6:
            raise ValueError(f"stocks + bonds + cash must equal 1 (got {total:g})")
        return self


AssetStrategy = Annotated[Union[TargetDateStrategy, StaticAllocation], Field(discriminator="kind")]  # noqa: UP007


class _AccountCommon(StrictModel):
    id: Identifier
    owner: Identifier  # a member id, or "joint"
    type: Identifier
    balance: Money


class RetirementAccount(_AccountCommon):
    asset_strategy: AssetStrategy


class HsaAccount(_AccountCommon):
    asset_strategy: AssetStrategy


class InheritedAccount(_AccountCommon):
    asset_strategy: AssetStrategy
    inherited_year: Year
    # Whether the decedent had reached their required beginning date; if so, annual RMDs apply in years 1-9.
    decedent_started_rmds: bool


class BrokerageAccount(_AccountCommon):
    asset_strategy: AssetStrategy
    cost_basis: Money


class CashAccount(_AccountCommon):
    # Fixed annual rate. None: follows the market preset's cash return.
    interest_rate: Rate | None = None


class Plan529Account(_AccountCommon):
    asset_strategy: AssetStrategy
    beneficiary: Identifier  # a dependent (or a member, for adult education)
    cost_basis: Money  # contributions to date
    opened_year: Year


Account = Union[  # noqa: UP007
    RetirementAccount, HsaAccount, InheritedAccount, BrokerageAccount, CashAccount, Plan529Account
]

_FAMILY_MODELS: dict[AccountFamily, type[_AccountCommon]] = {
    AccountFamily.RETIREMENT: RetirementAccount,
    AccountFamily.HSA: HsaAccount,
    AccountFamily.INHERITED: InheritedAccount,
    AccountFamily.BROKERAGE: BrokerageAccount,
    AccountFamily.CASH: CashAccount,
    AccountFamily.EDUCATION_529: Plan529Account,
}


class AccountsDoc(Document):
    """Raw account entries; `parse_accounts` validates each against the model its account type's family selects."""

    accounts: tuple[dict[str, Any], ...] = ()


_COMMON = TypeAdapter(_AccountCommon)


def parse_accounts(
    doc: AccountsDoc, account_types: AccountTypesDoc, origin: str
) -> tuple[tuple[Account, ...], list[ConfigIssue]]:
    """Validate each account entry by its type's family. Returns the accounts that parsed and any issues found."""
    accounts: list[Account] = []
    issues: list[ConfigIssue] = []
    for index, entry in enumerate(doc.accounts):
        prefix = f"accounts[{entry.get('id', index)}]"
        common_fields = {k: entry[k] for k in ("id", "owner", "type", "balance") if k in entry}
        try:
            common = _COMMON.validate_python(common_fields)
        except ValidationError as error:
            issues.extend(issues_from_validation_error(error, origin, entry, prefix=prefix))
            continue
        account_type = account_types.get(common.type)
        if account_type is None:
            issues.append(ConfigIssue(origin, f"{prefix}.type", f"unknown account type '{common.type}'"))
            continue
        try:
            accounts.append(_FAMILY_MODELS[account_type.family].model_validate(entry))
        except ValidationError as error:
            issues.extend(issues_from_validation_error(error, origin, entry, prefix=prefix))
    ids = [a.id for a in accounts]
    for duplicate in sorted({i for i in ids if ids.count(i) > 1}):
        issues.append(ConfigIssue(origin, "accounts", f"account id '{duplicate}' is used more than once"))
    return tuple(accounts), issues
