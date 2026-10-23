"""Price levels from the simulated inflation path, for indexing tax thresholds, limits, and spending."""

from __future__ import annotations

import math
from typing import Literal

import numpy as np

Index = Literal["general", "education", "healthcare", "none"]


class PriceIndex:
    """Price level at the start of each year, 1.0 at `start_year`.

    Years before the simulation (e.g. a rules file's base year) extrapolate backward at `pre_start_inflation`.
    `education` and `healthcare` compound CPI plus a spread.
    """

    def __init__(self, start_year: int, inflation: np.ndarray, pre_start_inflation: float, spreads: dict[str, float]):
        self.start_year = start_year
        self.pre_start_inflation = pre_start_inflation
        self.spreads = {"general": 0.0, **spreads}
        self._levels = {
            name: np.concatenate(([1.0], np.cumprod(1 + inflation + spread))) for name, spread in self.spreads.items()
        }
        self._cola = np.maximum.accumulate(self._levels["general"])

    def level(self, year: int, index: Index = "general") -> float:
        if index == "none":
            return 1.0
        offset = year - self.start_year
        if offset < 0:
            return (1 + self.pre_start_inflation + self.spreads[index]) ** offset
        levels = self._levels[index]
        return float(levels[min(offset, len(levels) - 1)])

    def cola_level(self, year: int) -> float:
        """Benefit level for a cost-of-living adjustment that never goes negative: after deflation, benefits hold
        until prices pass their previous peak (Social Security COLAs)."""
        offset = year - self.start_year
        if offset < 0:
            return self.level(year)
        return float(self._cola[min(offset, len(self._cola) - 1)])

    def factor(self, from_year: int, to_year: int, index: Index = "general") -> float:
        return self.level(to_year, index) / self.level(from_year, index)

    def indexed(self, amount: float, base_year: int, year: int, rounding: float | None = None) -> float:
        """`amount` stated for `base_year`, inflated to `year`; rounded down to a multiple of `rounding` if given."""
        value = amount * self.factor(base_year, year)
        if rounding:
            value = math.floor(value / rounding + 1e-9) * rounding
        return value
