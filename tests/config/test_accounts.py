import pytest

from northward.config.accounts import (
    AccountsDoc,
    BrokerageAccount,
    CashAccount,
    Plan529Account,
    RetirementAccount,
    StaticAllocation,
    TargetDateStrategy,
    parse_accounts,
)
from northward.config.rules.account_types import AccountTypesDoc
from tests.conftest import load_yaml

ACCOUNT_TYPES = AccountTypesDoc.model_validate(load_yaml("rules/account_types.yaml"))


def parse(entries):
    doc = AccountsDoc.model_validate({"schema_version": 1, "accounts": entries})
    return parse_accounts(doc, ACCOUNT_TYPES, "accounts.yaml")


def test_example_accounts_parse_into_family_models():
    accounts, issues = parse(load_yaml("profiles/example/accounts.yaml")["accounts"])
    assert issues == []
    by_id = {a.id: a for a in accounts}
    assert isinstance(by_id["alex_401k"], RetirementAccount)
    assert isinstance(by_id["alex_401k"].asset_strategy, TargetDateStrategy)
    assert isinstance(by_id["joint_brokerage"], BrokerageAccount)
    assert isinstance(by_id["joint_brokerage"].asset_strategy, StaticAllocation)
    assert isinstance(by_id["joint_checking"], CashAccount)
    assert by_id["joint_checking"].interest_rate is None
    assert isinstance(by_id["sam_529"], Plan529Account)


def test_allocation_weights_must_sum_to_one():
    _, issues = parse(
        [
            {
                "id": "b",
                "owner": "joint",
                "type": "brokerage",
                "balance": 1,
                "cost_basis": 1,
                "asset_strategy": {"kind": "static_allocation", "stocks": 0.7, "bonds": 0.2},
            }
        ]
    )
    assert [str(i) for i in issues] == [
        "accounts.yaml: accounts[b].asset_strategy: stocks + bonds + cash must equal 1 (got 0.9)"
    ]


def test_family_specific_fields_are_required():
    _, issues = parse(
        [
            {
                "id": "b",
                "owner": "joint",
                "type": "brokerage",
                "balance": 1,
                "asset_strategy": {"kind": "static_allocation", "stocks": 1, "bonds": 0},
            }
        ]
    )
    assert [(i.location, i.message) for i in issues] == [("accounts[b].cost_basis", "Field required")]


def test_fields_from_other_families_are_rejected():
    _, issues = parse([{"id": "s", "owner": "joint", "type": "savings", "balance": 1, "cost_basis": 5}])
    assert [(i.location, i.message) for i in issues] == [("accounts[s].cost_basis", "Extra inputs are not permitted")]


def test_unknown_account_type():
    _, issues = parse([{"id": "x", "owner": "alex", "type": "annuity", "balance": 1}])
    assert [(i.location, i.message) for i in issues] == [("accounts[x].type", "unknown account type 'annuity'")]


def test_duplicate_ids():
    entry = {"id": "c", "owner": "joint", "type": "checking", "balance": 1}
    _, issues = parse([entry, entry])
    assert [i.message for i in issues] == ["account id 'c' is used more than once"]


@pytest.mark.parametrize("balance", [-1, "lots"])
def test_balance_must_be_a_non_negative_number(balance):
    _, issues = parse([{"id": "c", "owner": "joint", "type": "checking", "balance": balance}])
    assert len(issues) == 1 and issues[0].location == "accounts[c].balance"
