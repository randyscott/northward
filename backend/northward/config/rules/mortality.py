"""Period life table for sampling ages at death (Monte Carlo) and summarizing survival."""

from __future__ import annotations

import numpy as np
from pydantic import Field, field_validator

from northward.config.base import Document
from northward.config.rules.federal_tax import Metadata


def _check(table: dict[int, float]) -> dict[int, float]:
    ages = sorted(table)
    if ages != list(range(ages[0], ages[-1] + 1)) or ages[0] != 0:
        raise ValueError("life table ages must run consecutively from 0")
    if any(not 0 < q <= 1 for q in table.values()):
        raise ValueError("death probabilities must be in (0, 1]")
    return table


class MortalityDoc(Document):
    metadata: Metadata
    male: dict[int, float] = Field(min_length=1)
    female: dict[int, float] = Field(min_length=1)

    @field_validator("male", "female")
    @classmethod
    def _check_tables(cls, table: dict[int, float]) -> dict[int, float]:
        return _check(table)

    def death_probability(self, sex: str | None, age: int) -> float:
        """q_x for `sex` (None: the average of the two tables); certain death past the last age."""
        tables = [self.male] if sex == "male" else [self.female] if sex == "female" else [self.male, self.female]
        last = min(max(t) for t in tables)
        if age >= last:
            return 1.0
        return sum(t[age] for t in tables) / len(tables)

    def death_distribution(self, sex: str | None, age: float) -> tuple[np.ndarray, np.ndarray]:
        """For someone alive at exact `age`: possible ages at death (the middle of each remaining year of age) and the
        cumulative probability of having died by each. Deaths are spread evenly through a year of age."""
        whole = int(age)
        ages, deaths, alive = [], [], 1.0
        for x in range(whole, 200):
            low = age if x == whole else float(x)
            q = self.death_probability(sex, x)
            if x == whole and q < 1:
                q *= x + 1 - low  # only the rest of the current year of age remains
            ages.append((low + x + 1) / 2)
            deaths.append(alive * q)
            alive *= 1 - q
            if q >= 1:
                break
        return np.array(ages), np.cumsum(deaths)

    def death_age(self, sex: str | None, age: float, u: float) -> float:
        """Age at death for someone alive at exact `age`, by inverting the distribution at the uniform draw `u`."""
        ages, cdf = self.death_distribution(sex, age)
        return float(ages[min(int(np.searchsorted(cdf, u, side="right")), len(ages) - 1)])

    def expected_death_age(self, sex: str | None, age: float) -> float:
        ages, cdf = self.death_distribution(sex, age)
        return float(np.dot(ages, np.diff(cdf, prepend=0.0)))

    def sample_death_age(self, sex: str | None, current_age: float, rng: np.random.Generator) -> float:
        """Age at death for someone alive at exact age `current_age`."""
        return self.death_age(sex, current_age, rng.random())

    def life_expectancy(self, sex: str | None, age: int) -> float:
        """Remaining (curtate + 1/2) life expectancy, for reports and sanity checks."""
        alive, total = 1.0, 0.0
        for x in range(age, 200):
            q = self.death_probability(sex, x)
            total += alive * (1 - q / 2)
            alive *= 1 - q
            if alive < 1e-12:
                break
        return total
