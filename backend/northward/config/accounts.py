"""Account instances. Each account's `type` names an account-type rule, whose `family` selects the model here."""

from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import Field, PlainValidator, TypeAdapter, ValidationError, model_validator

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
    """Usually the owner's retirement year, or a 529 beneficiary's first college year."""
    glide_path: Identifier = "linear_default"
    """A glide path id from rules/glide_paths.yaml."""
    start_equity: Rate | None = None
    """Override: the stock share until `years_before` the target year."""
    years_before: int | None = Field(default=None, gt=0)
    """Override: how many years before the target year the stock share starts falling."""
    target_equity: Rate | None = None
    """Override: the stock share at the target year."""
    post_target: PostTarget | None = None
    """Override: keep reducing the stock share after the target year."""


class StaticAllocation(StrictModel):
    """A fixed mix, rebalanced every year. The weights must sum to 1."""

    kind: Literal["static_allocation"]
    stocks: Rate
    """Share in stocks, e.g. 0.70."""
    bonds: Rate
    """Share in bonds."""
    cash: Rate = 0.0
    """Share in cash."""

    @model_validator(mode="after")
    def _check_sum(self) -> StaticAllocation:
        total = self.stocks + self.bonds + self.cash
        if abs(total - 1) > 1e-6:
            raise ValueError(f"stocks + bonds + cash must equal 1 (got {total:g})")
        return self


AssetStrategy = Annotated[Union[TargetDateStrategy, StaticAllocation], Field(discriminator="kind")]  # noqa: UP007


class _AccountCommon(StrictModel):
    id: Identifier
    """How income elections, levers, and events refer to the account."""
    owner: Identifier
    """A member id, or `joint`. IRAs, 401(k)s, HSAs, and 529s can't be joint."""
    type: Identifier
    """An account type from rules/account_types.yaml, e.g. traditional_401k, roth_ira, brokerage, savings."""
    balance: Money
    """Balance at the start of the scenario's first year."""


_ASSET_STRATEGY = "How the account is invested: a static_allocation or a target_date glide path."


class RetirementAccount(_AccountCommon):
    """A 401(k) or IRA, traditional or Roth."""

    asset_strategy: AssetStrategy = Field(description=_ASSET_STRATEGY)


class HsaAccount(_AccountCommon):
    """A Health Savings Account."""

    asset_strategy: AssetStrategy = Field(description=_ASSET_STRATEGY)


class InheritedAccount(_AccountCommon):
    """An IRA inherited from someone other than a spouse, under the 10-year rule."""

    asset_strategy: AssetStrategy = Field(description=_ASSET_STRATEGY)
    inherited_year: Year
    """The year it was inherited; the 10-year clock starts from it."""
    decedent_started_rmds: bool
    """Whether the original owner had started RMDs. If so, annual RMDs also apply in years 1-9."""


class BrokerageAccount(_AccountCommon):
    """A taxable brokerage account."""

    asset_strategy: AssetStrategy = Field(description=_ASSET_STRATEGY)
    cost_basis: Money
    """Total cost basis of the holdings (average-cost basis is used)."""


class CashAccount(_AccountCommon):
    """A checking or savings account."""

    interest_rate: Rate | None = None
    """A fixed annual rate. Default: the market preset's cash return."""


class Plan529Account(_AccountCommon):
    """A 529 education savings plan."""

    asset_strategy: AssetStrategy = Field(description=_ASSET_STRATEGY)
    beneficiary: Identifier
    """A dependent (or a member, for adult education)."""
    cost_basis: Money
    """Contributions to date, which set the taxable earnings share of a non-qualified withdrawal."""
    opened_year: Year
    """For the 15-year rule on rollovers to a Roth IRA."""


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


def _entry(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("an account must be a mapping")
    return value


# Entries stay raw here: `parse_accounts` validates each against the model its account type's family selects, since
# the type -> family mapping is rules data. The JSON Schema offers every family's fields to editors.
AccountEntry = Annotated[
    dict[str, Any],
    PlainValidator(
        _entry,
        json_schema_input_type=Union[  # noqa: UP007
            RetirementAccount, HsaAccount, InheritedAccount, BrokerageAccount, CashAccount, Plan529Account
        ],
    ),
]


class AccountsDoc(Document):
    """Every account the household owns: owner, type, balance, and how it's invested."""

    accounts: tuple[AccountEntry, ...] = ()
    """The fields an account needs depend on its `type`."""


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
