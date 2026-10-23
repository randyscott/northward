"""Required minimum distribution rules: applicable ages and life-expectancy tables."""

from __future__ import annotations

from itertools import pairwise

from pydantic import Field, field_validator, model_validator

from northward.config.base import Age, Document, Month, StrictModel, Year
from northward.config.rules.federal_tax import Metadata


class RmdStartAge(StrictModel):
    """Applicable age for births through `born_through_year`/`born_through_month` (None: all later births)."""

    born_through_year: Year | None = None
    born_through_month: Month = 12
    age: Age


class Inherited10YearRule(StrictModel):
    distribution_years: int = Field(gt=0)
    annual_rmds_if_decedent_started: bool
    penalty_enforced_from: Year


def _check_table(table: dict[int, float]) -> dict[int, float]:
    ages = sorted(table)
    if ages != list(range(ages[0], ages[-1] + 1)):
        raise ValueError("table ages must be consecutive")
    values = [table[a] for a in ages]
    if any(v <= 0 for v in values) or any(a < b for a, b in pairwise(values)):
        raise ValueError("table values must be positive and must not increase with age")
    return table


class RmdDoc(Document):
    metadata: Metadata
    start_age: tuple[RmdStartAge, ...] = Field(min_length=1)
    uniform_lifetime: dict[int, float] = Field(min_length=1)
    single_life: dict[int, float] = Field(min_length=1)
    inherited_10_year: Inherited10YearRule

    @field_validator("uniform_lifetime", "single_life")
    @classmethod
    def _check_tables(cls, table: dict[int, float]) -> dict[int, float]:
        return _check_table(table)

    @model_validator(mode="after")
    def _check_start_ages(self) -> RmdDoc:
        *leading, last = self.start_age
        if last.born_through_year is not None:
            raise ValueError("the last start_age entry must omit born_through_year (it covers all later births)")
        bounds = [(e.born_through_year, e.born_through_month) for e in leading]
        if any(e[0] is None for e in bounds):
            raise ValueError("only the last start_age entry may omit born_through_year")
        if any(a >= b for a, b in pairwise(bounds)):
            raise ValueError("start_age entries must be in increasing birth-date order")
        return self

    def applicable_age(self, birth_year: int, birth_month: int) -> float:
        for entry in self.start_age:
            if entry.born_through_year is None or (birth_year, birth_month) <= (
                entry.born_through_year,
                entry.born_through_month,
            ):
                return entry.age
        raise AssertionError("unreachable: the last entry is open-ended")

    @staticmethod
    def _lookup(table: dict[int, float], age: int) -> float:
        return table[min(max(age, min(table)), max(table))]

    def uniform_divisor(self, age: int) -> float:
        return self._lookup(self.uniform_lifetime, age)

    def single_life_expectancy(self, age: int) -> float:
        return self._lookup(self.single_life, age)
