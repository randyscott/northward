"""Annual historical returns and inflation, for the block-bootstrap sampler and the `historical_us` preset (D38)."""

from __future__ import annotations

import numpy as np
from pydantic import Field, field_validator

from northward.config.base import Document, StrictModel
from northward.config.rules.federal_tax import Metadata
from northward.config.rules.market import FACTORS


class HistoricalYear(StrictModel):
    """Nominal total returns and CPI inflation for one calendar year."""

    stocks: float = Field(gt=-1)
    bonds: float = Field(gt=-1)
    cash: float = Field(gt=-1)
    inflation: float = Field(gt=-1)


class HistoricalReturnsDoc(Document):
    metadata: Metadata
    returns: dict[int, HistoricalYear] = Field(min_length=2)

    @field_validator("returns")
    @classmethod
    def _check_years(cls, returns: dict[int, HistoricalYear]) -> dict[int, HistoricalYear]:
        years = sorted(returns)
        if years != list(range(years[0], years[-1] + 1)):
            raise ValueError("years must be consecutive")
        return returns

    def matrix(self) -> np.ndarray:
        """`(years × factors)` array in year order, columns ordered as FACTORS."""
        return np.array([[getattr(self.returns[y], f) for f in FACTORS] for y in sorted(self.returns)])
