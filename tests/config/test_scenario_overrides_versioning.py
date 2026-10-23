import pytest
from pydantic import ValidationError

from northward.config import versioning
from northward.config.overrides import OverrideError, apply_overrides
from northward.config.scenario import ClaimAge, FillBracketConversions, ScenarioDoc
from tests.conftest import load_yaml


def test_example_scenarios_load():
    base = ScenarioDoc.model_validate(load_yaml("profiles/example/scenarios/base.yaml"))
    assert base.levers.ss_claim_ages["alex"] == ClaimAge(years=67)
    alt = ScenarioDoc.model_validate(load_yaml("profiles/example/scenarios/early_retire_roth_fill.yaml"))
    assert alt.levers.ss_claim_ages["jordan"] == ClaimAge(years=67, months=6)
    assert isinstance(alt.levers.roth_conversions, FillBracketConversions)


@pytest.mark.parametrize("claim", [61, 71, {"years": 70, "months": 1}])
def test_claim_age_range(claim):
    with pytest.raises(ValidationError):
        ClaimAge.model_validate(claim)


def test_withdrawal_order_must_be_a_permutation():
    data = load_yaml("profiles/example/scenarios/base.yaml")
    data["levers"]["withdrawal_order"] = ["taxable", "taxable", "roth", "hsa"]
    with pytest.raises(ValidationError, match="exactly once"):
        ScenarioDoc.model_validate(data)


def test_overrides_address_list_items_by_id():
    data = {"members": [{"id": "alex", "age": 62}, {"id": "jordan", "age": 65}]}
    result = apply_overrides(data, {"members.jordan.age": 60})
    assert result["members"][1]["age"] == 60
    assert data["members"][1]["age"] == 65  # input is not modified


def test_overrides_can_add_a_final_key_but_not_intermediate_ones():
    assert apply_overrides({"a": {}}, {"a.b": 1}) == {"a": {"b": 1}}
    with pytest.raises(OverrideError, match="'x' not found"):
        apply_overrides({"a": {}}, {"x.b": 1})


def test_override_unknown_list_item():
    with pytest.raises(OverrideError, match="no item 'casey' in members"):
        apply_overrides({"members": [{"id": "alex"}]}, {"members.casey.age": 60})


def test_upgrade_requires_schema_version():
    with pytest.raises(ValueError, match="schema_version is missing"):
        versioning.upgrade_document("household", {"members": []})


def test_upgrade_rejects_newer_documents():
    with pytest.raises(ValueError, match="newer than"):
        versioning.upgrade_document("household", {"schema_version": 99})


def test_registered_upgrades_run_in_order(monkeypatch):
    monkeypatch.setitem(versioning.CURRENT_SCHEMA_VERSIONS, "household", 3)
    monkeypatch.setattr(versioning, "_UPGRADES", {})
    versioning.register_upgrade("household", 1)(lambda d: {**d, "steps": ["1->2"]})
    versioning.register_upgrade("household", 2)(lambda d: {**d, "steps": [*d["steps"], "2->3"]})
    assert versioning.upgrade_document("household", {"schema_version": 1}) == {
        "schema_version": 3,
        "steps": ["1->2", "2->3"],
    }


def test_missing_upgrade_is_reported(monkeypatch):
    monkeypatch.setitem(versioning.CURRENT_SCHEMA_VERSIONS, "household", 2)
    monkeypatch.setattr(versioning, "_UPGRADES", {})
    with pytest.raises(ValueError, match="no upgrade registered"):
        versioning.upgrade_document("household", {"schema_version": 1})
