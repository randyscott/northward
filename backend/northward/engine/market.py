"""Year-by-year market outcomes the engine runs on. Deterministic runs use constants; Monte Carlo samples paths."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal, NamedTuple

import numpy as np

from northward.config.rules.market import FactorAssumption, MarketPreset


class MarketYear(NamedTuple):
    stocks: float
    bonds: float
    cash: float
    inflation: float


@dataclass(frozen=True)
class MarketPath:
    """Annual nominal returns and inflation for `start_year`, `start_year + 1`, ..."""

    start_year: int
    stocks: np.ndarray
    bonds: np.ndarray
    cash: np.ndarray
    inflation: np.ndarray

    def __post_init__(self) -> None:
        lengths = {len(self.stocks), len(self.bonds), len(self.cash), len(self.inflation)}
        if len(lengths) != 1:
            raise ValueError("every factor needs the same number of years")

    @property
    def years(self) -> int:
        return len(self.inflation)

    def year(self, year: int) -> MarketYear:
        i = year - self.start_year
        return MarketYear(float(self.stocks[i]), float(self.bonds[i]), float(self.cash[i]), float(self.inflation[i]))


def _deterministic_value(factor: FactorAssumption, distribution: str, basis: str) -> float:
    """The constant a deterministic run uses. Only lognormal factors get the geometric (median) adjustment; normal
    and Student-t factors (e.g. inflation) use their mean."""
    value = factor.mean
    if basis == "geometric" and (factor.distribution or distribution) == "lognormal" and factor.std_dev > 0:
        # Median (compounded) growth of a lognormal with this arithmetic mean and standard deviation.
        value = (1 + factor.mean) / math.sqrt(1 + (factor.std_dev / (1 + factor.mean)) ** 2) - 1
    if factor.min_bound is not None:
        value = max(value, factor.min_bound)
    if factor.max_bound is not None:
        value = min(value, factor.max_bound)
    return value


def deterministic_path(
    preset: MarketPreset, start_year: int, years: int, basis: Literal["geometric", "arithmetic"] = "geometric"
) -> MarketPath:
    values = {name: _deterministic_value(f, preset.distribution, basis) for name, f in preset.factors.items()}
    return MarketPath(start_year, *(np.full(years, values[name]) for name in ("stocks", "bonds", "cash", "inflation")))
