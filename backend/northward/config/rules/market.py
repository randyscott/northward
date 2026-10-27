"""Capital market assumption presets (docs/configuration/rules.md)."""

from __future__ import annotations

from typing import Literal

import numpy as np
from pydantic import Field, model_validator

from northward.config.base import Document, Identifier, Rate, StrictModel

FACTORS = ("stocks", "bonds", "cash", "inflation")
Factor = Literal["stocks", "bonds", "cash", "inflation"]
Distribution = Literal["lognormal", "normal", "student_t"]


class FactorAssumption(StrictModel):
    """Annual arithmetic mean and standard deviation (nominal), with optional sampling bounds."""

    mean: float = Field(gt=-1)
    std_dev: float = Field(ge=0)
    distribution: Distribution | None = None  # defaults to the preset's distribution
    min_bound: float | None = None
    max_bound: float | None = None

    @model_validator(mode="after")
    def _check_bounds(self) -> FactorAssumption:
        if self.min_bound is not None and self.max_bound is not None and self.min_bound >= self.max_bound:
            raise ValueError("min_bound must be less than max_bound")
        return self


class StockIncome(StrictModel):
    dividend_yield: Rate
    qualified_fraction: Rate


class BondIncome(StrictModel):
    interest_yield: Rate


class TaxableIncome(StrictModel):
    """How a taxable account's return splits into current income vs. price change. Cash returns are all interest."""

    stocks: StockIncome
    bonds: BondIncome


class InflationSpreads(StrictModel):
    """Extra annual inflation over CPI for specialized spending indexes."""

    education: float = 0.0
    healthcare: float = 0.0


class MarketPreset(StrictModel):
    """`parametric`: each year's returns are drawn from the distributions below (correlated through a Cholesky factor).
    `bootstrap`: years are resampled in blocks from rules/historical_returns.yaml; its factors and correlations are
    computed from that history by the loader (they describe the history, for deterministic runs and reports)."""

    id: Identifier
    description: str
    kind: Literal["parametric", "bootstrap"] = "parametric"
    distribution: Distribution = "lognormal"
    # Student-t degrees of freedom (fatter tails as it falls toward 2); used by factors with distribution student_t.
    degrees_of_freedom: float = Field(default=5.0, gt=2)
    block_length: int = Field(default=5, ge=1)  # bootstrap: consecutive historical years per block
    factors: dict[Factor, FactorAssumption] = {}
    # Upper-triangular pairwise correlations, e.g. {stocks: {bonds: 0.1}}. Missing pairs are 0.
    correlations: dict[Factor, dict[Factor, float]] = {}
    taxable_income: TaxableIncome
    inflation_spreads: InflationSpreads = InflationSpreads()

    @model_validator(mode="after")
    def _check(self) -> MarketPreset:
        missing = [f for f in FACTORS if f not in self.factors]
        if self.kind == "bootstrap" and len(missing) == len(FACTORS):
            if self.correlations:
                raise ValueError("bootstrap presets take their correlations from rules/historical_returns.yaml")
            return self  # factors are filled in from the history by the loader
        if missing:
            raise ValueError(f"factors missing: {', '.join(missing)}")
        seen: set[frozenset[str]] = set()
        for a, row in self.correlations.items():
            for b, rho in row.items():
                if a == b:
                    raise ValueError(f"correlation of {a} with itself is implied (1.0) and can't be set")
                pair = frozenset((a, b))
                if pair in seen:
                    raise ValueError(f"correlation between {a} and {b} is given twice")
                seen.add(pair)
                if not -1 <= rho <= 1:
                    raise ValueError(f"correlation between {a} and {b} must be in [-1, 1] (got {rho})")
        if np.linalg.eigvalsh(self.correlation_matrix()).min() < -1e-9:
            raise ValueError("correlations don't form a valid (positive semi-definite) correlation matrix")
        return self

    def correlation_matrix(self) -> np.ndarray:
        """Correlation matrix ordered as FACTORS."""
        index = {f: i for i, f in enumerate(FACTORS)}
        matrix = np.eye(len(FACTORS))
        for a, row in self.correlations.items():
            for b, rho in row.items():
                matrix[index[a], index[b]] = matrix[index[b], index[a]] = rho
        return matrix


def from_history(preset: MarketPreset, history: np.ndarray) -> MarketPreset:
    """A bootstrap preset with factors and correlations describing `history` (`years × FACTORS`): arithmetic means and
    sample standard deviations, with inflation bounded to its historical range."""
    means, std_devs = history.mean(axis=0), history.std(axis=0, ddof=1)
    corr = np.corrcoef(history.T)
    factors = {
        f: FactorAssumption(mean=float(means[i]), std_dev=float(std_devs[i]))
        for i, f in enumerate(FACTORS)
        if f != "inflation"
    }
    i = FACTORS.index("inflation")
    factors["inflation"] = FactorAssumption(
        mean=float(means[i]),
        std_dev=float(std_devs[i]),
        distribution="normal",
        min_bound=float(history[:, i].min()),
        max_bound=float(history[:, i].max()),
    )
    correlations = {
        a: {b: float(corr[ia, ib]) for ib, b in enumerate(FACTORS) if ib > ia} for ia, a in enumerate(FACTORS[:-1])
    }
    return preset.model_copy(update={"factors": factors, "correlations": correlations})


class MarketAssumptionsDoc(Document):
    presets: tuple[MarketPreset, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_unique(self) -> MarketAssumptionsDoc:
        ids = [p.id for p in self.presets]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"preset ids must be unique; duplicated: {', '.join(duplicates)}")
        return self

    def get(self, preset_id: str) -> MarketPreset | None:
        return next((p for p in self.presets if p.id == preset_id), None)
