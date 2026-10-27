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
    """A calendar year."""

    year: Year
    """The calendar year."""


class MemberAgeAnchor(StrictModel):
    """The year a household member reaches an age."""

    member: Identifier
    """A member id from household.yaml."""
    age: Age
    """May be fractional (62.5), counted in months from the birth month."""


class DependentAgeAnchor(StrictModel):
    """The year a dependent reaches an age."""

    dependent: Identifier
    """A dependent id from household.yaml."""
    age: Age
    """May be fractional, counted in months from the birth month."""


class EventAnchor(StrictModel):
    """The year of a member's retirement or death."""

    event: Literal["retirement", "death"]
    """A death that doesn't happen within the plan never occurs."""
    member: Identifier
    """A member id from household.yaml."""


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
