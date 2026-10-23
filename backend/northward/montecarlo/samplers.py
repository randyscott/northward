"""Random draws for Monte Carlo paths: annual market returns and inflation, and ages at death.

Every path draws from its own streams, keyed by (seed, stream, path index), so a path can be regenerated on its own
for drill-down, results don't depend on how paths are split across processes, and scenarios run with the same seed
see the same draws (common random numbers). Each stream is consumed in year order, so a longer horizon only appends
years: the first N years of a path are the same whatever its length.
"""

from __future__ import annotations

import math
from typing import Protocol

import numpy as np

from northward.config.loader import SimulationInput
from northward.config.rules.market import FACTORS, MarketPreset

MARKET_STREAM, MIXING_STREAM, BOOTSTRAP_STREAM, MORTALITY_STREAM = range(4)
RETURN_FLOOR = -0.99  # no factor loses more than 99% in a year (normal and Student-t tails could pass -100%)


def generator(seed: int, stream: int, index: int) -> np.random.Generator:
    return np.random.default_rng(np.random.SeedSequence(seed, spawn_key=(stream, index)))


class MarketSampler(Protocol):
    def sample(self, seed: int, index: int, years: int) -> np.ndarray:
        """`(years × FACTORS)` nominal returns and inflation for path `index`."""
        ...


def _correlation_root(matrix: np.ndarray) -> np.ndarray:
    """A matrix L with L Lᵀ = `matrix`: the Cholesky factor, or an eigen root if the matrix is only semi-definite."""
    try:
        return np.linalg.cholesky(matrix)
    except np.linalg.LinAlgError:
        values, vectors = np.linalg.eigh(matrix)
        return vectors * np.sqrt(np.clip(values, 0.0, None))


class ParametricSampler:
    """Correlated draws from the preset's distributions. Correlated standard normals (Cholesky) drive every factor:
    `lognormal` factors match the arithmetic mean and standard deviation of the return, `normal` ones use them
    directly, and `student_t` ones divide the normal by a chi-square mixing draw shared by all Student-t factors in
    the year (a multivariate t, so crashes coincide), scaled so the standard deviation still matches. Results are
    clipped to each factor's bounds. A factor with zero standard deviation is exactly its mean."""

    def __init__(self, preset: MarketPreset):
        factors = [preset.factors[f] for f in FACTORS]
        self.means = np.array([f.mean for f in factors])
        self.std_devs = np.array([f.std_dev for f in factors])
        self.kinds = [f.distribution or preset.distribution for f in factors]
        self.lower = np.array(
            [RETURN_FLOOR if f.min_bound is None else max(f.min_bound, RETURN_FLOOR) for f in factors]
        )
        self.upper = np.array([math.inf if f.max_bound is None else f.max_bound for f in factors])
        self.root = _correlation_root(preset.correlation_matrix())
        self.degrees_of_freedom = preset.degrees_of_freedom
        # Lognormal: 1 + r = exp(mu + sigma z) with the target arithmetic mean and standard deviation.
        self.sigmas = np.sqrt(np.log1p((self.std_devs / (1 + self.means)) ** 2))
        self.mus = np.log1p(self.means) - self.sigmas**2 / 2

    def sample(self, seed: int, index: int, years: int) -> np.ndarray:
        z = generator(seed, MARKET_STREAM, index).standard_normal((years, len(FACTORS))) @ self.root.T
        t_scale = None
        if "student_t" in self.kinds:
            df = self.degrees_of_freedom
            mixing = generator(seed, MIXING_STREAM, index).chisquare(df, size=years)
            t_scale = np.sqrt((df - 2) / mixing)
        out = np.empty_like(z)
        for j, kind in enumerate(self.kinds):
            if self.std_devs[j] == 0:
                out[:, j] = self.means[j]
            elif kind == "lognormal":
                out[:, j] = np.expm1(self.mus[j] + self.sigmas[j] * z[:, j])
            elif kind == "normal":
                out[:, j] = self.means[j] + self.std_devs[j] * z[:, j]
            else:
                assert t_scale is not None
                out[:, j] = self.means[j] + self.std_devs[j] * z[:, j] * t_scale
        return np.clip(out, self.lower, self.upper)


class BootstrapSampler:
    """Resamples whole historical years in blocks of `block_length` consecutive years, each block starting at a
    uniformly chosen year and wrapping from the last year to the first (a circular block bootstrap, so every year is
    equally likely)."""

    def __init__(self, history: np.ndarray, block_length: int):
        self.history = history
        self.block_length = block_length

    def sample(self, seed: int, index: int, years: int) -> np.ndarray:
        n, length = len(self.history), self.block_length
        blocks = -(-years // length)
        starts = (generator(seed, BOOTSTRAP_STREAM, index).random(blocks) * n).astype(np.int64)
        rows = ((starts[:, None] + np.arange(length)) % n).ravel()[:years]
        return self.history[rows]


def market_sampler(sim: SimulationInput) -> MarketSampler:
    if sim.market.kind == "bootstrap":
        return BootstrapSampler(sim.rules.historical_returns.matrix(), sim.market.block_length)
    return ParametricSampler(sim.market)


def death_uniforms(seed: int, index: int, members: int) -> np.ndarray:
    """One uniform draw per household member (in household order) for path `index`."""
    return generator(seed, MORTALITY_STREAM, index).random(members)
