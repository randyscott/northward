import pytest
from pydantic import TypeAdapter, ValidationError

from northward.config.anchors import (
    Anchor,
    DependentAgeAnchor,
    EventAnchor,
    MemberAgeAnchor,
    YearAnchor,
    year_person_reaches_age,
)
from northward.config.household import Member

ANCHOR = TypeAdapter(Anchor)


@pytest.mark.parametrize(
    ("raw", "expected_type"),
    [
        ({"year": 2031}, YearAnchor),
        ({"member": "alex", "age": 85}, MemberAgeAnchor),
        ({"dependent": "sam", "age": 18}, DependentAgeAnchor),
        ({"event": "retirement", "member": "alex"}, EventAnchor),
    ],
)
def test_anchor_kinds(raw, expected_type):
    assert isinstance(ANCHOR.validate_python(raw), expected_type)


def test_unrecognized_anchor_names_the_valid_shapes():
    with pytest.raises(ValidationError, match=r"expected one of \{year\}"):
        ANCHOR.validate_python({"when": 2031})


def test_anchor_rejects_extra_keys():
    with pytest.raises(ValidationError, match="Extra inputs"):
        ANCHOR.validate_python({"year": 2031, "age": 5})


def test_year_person_reaches_age_handles_fractional_ages():
    member = Member(id="alex", name="A", birth_year=1978, birth_month=9, target_retirement_age=62)
    assert year_person_reaches_age(member, 62) == 2040
    # 59.5 = 59 years + 6 months; born September, so the half-birthday falls in March of the following year.
    assert year_person_reaches_age(member, 59.5) == 2038
    march_born = Member(id="b", name="B", birth_year=1978, birth_month=3, target_retirement_age=62)
    assert year_person_reaches_age(march_born, 59.5) == 2037
