"""Calendar arithmetic for a simulation: horizon, ages, retirement points, and anchor resolution."""

from __future__ import annotations

import math
from typing import NamedTuple, Protocol

from northward.config.anchors import Anchor, DependentAgeAnchor, EventAnchor, MemberAgeAnchor, YearAnchor
from northward.config.household import Dependent, HouseholdDoc, Member
from northward.config.income import SalaryStream
from northward.config.loader import SimulationInput
from northward.lifecycle.mortality import is_sampled, planned_death_ages


class _Person(Protocol):
    birth_year: int
    birth_month: int


class Point(NamedTuple):
    """A moment within a calendar year: `fraction` is the share of `year` that has elapsed before it."""

    year: int
    fraction: float


def age_point(person: _Person, age: float) -> Point:
    whole = math.floor(age)
    months = round((age - whole) * 12)
    month_index = person.birth_month - 1 + months  # months after January of the birth year's anniversary
    return Point(person.birth_year + whole + month_index // 12, (month_index % 12) / 12)


class Timeline:
    def __init__(self, sim: SimulationInput, death_ages: dict[str, float] | None = None):
        """`death_ages` (a Monte Carlo path's draws) replaces the deaths the scenario's mortality lever plans."""
        self.household: HouseholdDoc = sim.profile.household
        horizon = sim.scenario.horizon
        members = self.household.members
        if death_ages is None:
            death_ages = planned_death_ages(sim)
        self.deaths: dict[str, Point] = {m.id: age_point(m, death_ages[m.id]) for m in members if m.id in death_ages}
        self.start_year = horizon.start_year
        self.end_year = horizon.end_year or max(age_point(m, horizon.end_age).year for m in members)
        if len(self.deaths) == len(members):  # the simulation ends with the last death...
            last_death = max(p.year for p in self.deaths.values())
            # ...which, when lifespans are sampled, may come after end_age.
            reaches_end_age = is_sampled(sim) and horizon.end_year is None
            self.end_year = last_death if reaches_end_age else min(self.end_year, last_death)
        self.death_ages = {m: age for m, age in death_ages.items() if self.deaths[m].year <= self.end_year}
        self.years = range(self.start_year, self.end_year + 1)
        # Work stops at retirement, or at death if that comes first.
        self.retirement = {
            m.id: min(age_point(m, m.target_retirement_age), self.deaths.get(m.id, Point(9999, 0.0))) for m in members
        }
        # The first year every member is retired (or deceased) for the whole year.
        self.all_retired_year = max(p.year + (1 if p.fraction > 0 else 0) for p in self.retirement.values())

    def member(self, member_id: str) -> Member:
        member = self.household.member(member_id)
        assert member is not None  # validated by the loader
        return member

    def dependent(self, dependent_id: str) -> Dependent:
        dependent = self.household.dependent(dependent_id)
        assert dependent is not None
        return dependent

    @staticmethod
    def age(person: _Person, year: int) -> int:
        """Age attained during `year` (i.e. at year end)."""
        return year - person.birth_year

    def point_at_age(self, member_id: str, age: float) -> Point:
        return age_point(self.member(member_id), age)

    def reaches(self, person: _Person, age: float) -> int:
        """Year `person` reaches `age`."""
        return age_point(person, age).year

    def point(self, anchor: Anchor) -> Point | None:
        """When an anchor falls. None: it doesn't happen during the simulation (a death after the plan ends)."""
        if isinstance(anchor, YearAnchor):
            return Point(anchor.year, 0.0)
        if isinstance(anchor, MemberAgeAnchor):
            return age_point(self.member(anchor.member), anchor.age)
        if isinstance(anchor, DependentAgeAnchor):
            return age_point(self.dependent(anchor.dependent), anchor.age)
        assert isinstance(anchor, EventAnchor)
        if anchor.event == "retirement":
            return self.retirement[anchor.member]
        return self.deaths.get(anchor.member)  # None: doesn't die within the horizon

    def year_of(self, anchor: Anchor) -> int | None:
        point = self.point(anchor)
        return None if point is None else point.year

    def window(self, start: Anchor | None, end: Anchor | None) -> tuple[int, int] | None:
        """Inclusive active years for a start/end pair. None if it never starts."""
        first = self.start_year if start is None else self.year_of(start)
        if first is None:
            return None
        last = self.end_year if end is None else self.year_of(end)
        return first, self.end_year if last is None else last

    def active(self, start: Anchor | None, end: Anchor | None, year: int) -> bool:
        window = self.window(start, end)
        return window is not None and window[0] <= year <= window[1]

    def alive(self, member_id: str, year: int) -> bool:
        """Alive for at least part of `year`."""
        death = self.deaths.get(member_id)
        return death is None or year <= death.year

    def died_before(self, member_id: str, year: int) -> bool:
        death = self.deaths.get(member_id)
        return death is not None and death.year < year

    def living_members(self, year: int) -> list[Member]:
        return [m for m in self.household.members if self.alive(m.id, year)]

    def survivor_of(self, member_id: str) -> Member | None:
        return next((m for m in self.household.members if m.id != member_id), None)

    def salary_fraction(self, stream: SalaryStream, year: int) -> float:
        """Share of `year` the salary is paid. It stops at the owner's retirement unless `end` says otherwise;
        a calendar-year `end` is inclusive (paid through that year)."""
        if stream.end is None:
            stop: Point | None = self.retirement[stream.owner]
        elif isinstance(stream.end, YearAnchor):
            stop = Point(stream.end.year + 1, 0.0)
        else:
            stop = self.point(stream.end)
        death = self.deaths.get(stream.owner)
        if death is not None:
            stop = death if stop is None else min(stop, death)
        if stop is None or year < stop.year:
            return 1.0
        return stop.fraction if year == stop.year else 0.0
