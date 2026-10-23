import pytest
from pydantic import ValidationError

from northward.config.household import HouseholdDoc
from tests.conftest import load_yaml


def household(**changes):
    data = load_yaml("profiles/example/household.yaml")
    data.update(changes)
    return data


def test_example_household_loads():
    doc = HouseholdDoc.model_validate(household())
    assert [m.id for m in doc.members] == ["alex", "jordan"]
    assert doc.dependent("sam").full_time_student_ages == (18, 21)
    assert doc.dependent("riley").relationship == "child"
    assert doc.member("alex").social_security.pia_at_fra == 2850


def test_social_security_record_is_optional_and_non_negative():
    data = household()
    del data["members"][0]["social_security"]
    assert HouseholdDoc.model_validate(data).member("alex").social_security is None
    data["members"][0]["social_security"] = {"pia_at_fra": -1}
    with pytest.raises(ValidationError, match="greater than or equal to 0"):
        HouseholdDoc.model_validate(data)


def test_ids_must_be_unique_across_members_and_dependents():
    data = household()
    data["dependents"][0]["id"] = "alex"
    with pytest.raises(ValidationError, match="duplicated: alex"):
        HouseholdDoc.model_validate(data)


def test_joint_is_reserved():
    data = household()
    data["dependents"][0]["id"] = "joint"
    with pytest.raises(ValidationError, match="reserved"):
        HouseholdDoc.model_validate(data)


def test_two_members_must_file_married():
    with pytest.raises(ValidationError, match="must file jointly or separately"):
        HouseholdDoc.model_validate(household(household={"filing_status": "single"}))


def test_child_of_must_reference_members():
    data = household()
    data["dependents"][0]["child_of"] = ["alex", "casey"]
    with pytest.raises(ValidationError, match="unknown member"):
        HouseholdDoc.model_validate(data)


def test_student_ages_must_be_ordered():
    data = household()
    data["dependents"][0]["full_time_student_ages"] = [22, 18]
    with pytest.raises(ValidationError, match="first <= last"):
        HouseholdDoc.model_validate(data)


def test_unknown_fields_are_rejected():
    data = household()
    data["members"][0]["retire_age"] = 60
    with pytest.raises(ValidationError, match="Extra inputs"):
        HouseholdDoc.model_validate(data)
