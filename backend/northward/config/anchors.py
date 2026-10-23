"""Timing anchors: when something starts or ends, as a calendar year, a person's age, or a life event.

Anchors are written in YAML as small mappings whose keys identify the kind:

    {year: 2031}                         # a calendar year
    {member: alex, age: 85}              # the year a household member reaches an age
    {dependent: sam, age: 18}            # the year a dependent reaches an age
    {event: retirement, member: jordan}  # a life event, resolved during simulation
"""

from __future__ import annotations

import math
from typing import Annotated, Any, Literal, Protocol, Union

from pydantic import Discriminator, Tag

from northward.config.base import Age, Identifier, StrictModel, Year


class YearAnchor(StrictModel):
    year: Year


class MemberAgeAnchor(StrictModel):
    member: Identifier
    age: Age


class DependentAgeAnchor(StrictModel):
    dependent: Identifier
    age: Age


class EventAnchor(StrictModel):
    event: Literal["retirement", "death"]
    member: Identifier


def _anchor_tag(value: Any) -> str | None:
    if isinstance(value, dict):
        if "year" in value:
            return "year"
        if "event" in value:
            return "event"
        if "dependent" in value:
            return "dependent_age"
        if "member" in value:
            return "member_age"
        return None
    return {
        YearAnchor: "year",
        EventAnchor: "event",
        DependentAgeAnchor: "dependent_age",
        MemberAgeAnchor: "member_age",
    }.get(type(value))


Anchor = Annotated[
    Union[  # noqa: UP007 - `|` between Annotated aliases isn't reliable on Python 3.10
        Annotated[YearAnchor, Tag("year")],
        Annotated[MemberAgeAnchor, Tag("member_age")],
        Annotated[DependentAgeAnchor, Tag("dependent_age")],
        Annotated[EventAnchor, Tag("event")],
    ],
    Discriminator(
        _anchor_tag,
        custom_error_type="invalid_anchor",
        custom_error_message="expected one of {year}, {member, age}, {dependent, age}, or {event, member}",
    ),
]


class _Person(Protocol):
    birth_year: int
    birth_month: int


def year_person_reaches_age(person: _Person, age: float) -> int:
    """Calendar year in which `person` reaches `age` (fractional ages count months from the birth month)."""
    whole_years = math.floor(age)
    months = round((age - whole_years) * 12)
    return person.birth_year + whole_years + (person.birth_month - 1 + months) // 12
