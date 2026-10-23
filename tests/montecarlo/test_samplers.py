import copy

import numpy as np
import pytest

from northward.config.loader import load_rules
from northward.config.rules.market import FACTORS, MarketPreset
from northward.config.source import FileSource
from northward.montecarlo.samplers import RETURN_FLOOR, BootstrapSampler, ParametricSampler, death_uniforms
from tests.conftest import DATA_DIR, load_yaml

RULES = load_rules(FileSource(DATA_DIR))
STOCKS, BONDS, CASH, INFLATION = range(4)


def preset(**changes) -> MarketPreset:
    data = copy.deepcopy(load_yaml("rules/market_assumptions.yaml")["presets"][0])  # forward_conservative
    data.update(changes)
    return MarketPreset.model_validate(data)


def unbounded(**changes) -> MarketPreset:
    """forward_conservative with inflation unbounded and lognormal, so sample moments can be checked exactly."""
    data = copy.deepcopy(load_yaml("rules/market_assumptions.yaml")["presets"][0])
    data["factors"]["inflation"] = {"mean": 0.025, "std_dev": 0.012}
    data.update(changes)
    return MarketPreset.model_validate(data)


def test_lognormal_draws_match_the_preset_moments_and_correlations():
    p = unbounded()
    draws = ParametricSampler(p).sample(seed=1, index=0, years=400_000)
    for j, factor in enumerate(FACTORS):
        assert draws[:, j].mean() == pytest.approx(p.factors[factor].mean, abs=0.001)
        assert draws[:, j].std() == pytest.approx(p.factors[factor].std_dev, rel=0.01)
    corr = np.corrcoef(draws.T)
    # Lognormal transforms shrink correlations very slightly; they stay within 0.01 here.
    assert np.allclose(corr, p.correlation_matrix(), atol=0.01)
    assert draws.min() > -1


def test_normal_inflation_is_clipped_to_its_bounds():
    draws = ParametricSampler(preset()).sample(seed=2, index=0, years=100_000)
    assert draws[:, INFLATION].min() == 0.0 and draws[:, INFLATION].max() <= 0.08
    assert (draws[:, INFLATION] == 0.0).mean() == pytest.approx(0.019, abs=0.003)  # P(N(2.5%, 1.2%) < 0) ≈ 1.9%


def test_student_t_matches_the_standard_deviation_with_fatter_tails():
    p = unbounded(distribution="student_t", degrees_of_freedom=5)
    draws = ParametricSampler(p).sample(seed=3, index=0, years=400_000)
    stocks = draws[:, STOCKS]
    assert stocks.mean() == pytest.approx(0.07, abs=0.002)
    assert stocks.std() == pytest.approx(0.17, rel=0.03)
    z = (stocks - stocks.mean()) / stocks.std()
    assert (z**4).mean() - 3 > 2  # excess kurtosis (6 in theory for 5 degrees of freedom); a normal has 0
    assert stocks.min() >= RETURN_FLOOR
    # A shared mixing draw makes extreme years coincide across factors (a multivariate t).
    extreme = np.abs(z) > 4
    assert np.abs(draws[extreme, BONDS] - 0.045).mean() > 2 * np.abs(draws[:, BONDS] - 0.045).mean()


def test_zero_volatility_returns_exactly_the_mean():
    factors = {f: {"mean": m, "std_dev": 0.0} for f, m in zip(FACTORS, (0.06, 0.04, 0.02, 0.03), strict=True)}
    draws = ParametricSampler(preset(factors=factors)).sample(seed=4, index=0, years=50)
    assert (draws == np.array([0.06, 0.04, 0.02, 0.03])).all()


@pytest.mark.parametrize("distribution", ["lognormal", "student_t"])
def test_draws_are_reproducible_per_path_and_longer_horizons_only_append(distribution):
    sampler = ParametricSampler(unbounded(distribution=distribution))
    first = sampler.sample(seed=9, index=5, years=30)
    assert np.array_equal(first, sampler.sample(seed=9, index=5, years=30))
    assert np.array_equal(first[:12], sampler.sample(seed=9, index=5, years=12))
    assert not np.array_equal(first, sampler.sample(seed=9, index=6, years=30))
    assert not np.array_equal(first, sampler.sample(seed=10, index=5, years=30))


def test_bootstrap_resamples_whole_years_in_wrapping_blocks():
    history = RULES.historical_returns.matrix()
    sampler = BootstrapSampler(history, block_length=5)
    draws = sampler.sample(seed=1, index=0, years=53)
    rows = [int(np.flatnonzero((history == row).all(axis=1))[0]) for row in draws]  # each draw is a historical year
    for block in range(0, 50, 5):
        start = rows[block]
        assert rows[block : block + 5] == [(start + k) % len(history) for k in range(5)]
    assert np.array_equal(draws[:20], sampler.sample(seed=1, index=0, years=20))
    # Every year (including the last ones, thanks to the wraparound) is drawn about equally often.
    many = np.concatenate([sampler.sample(seed=2, index=i, years=100) for i in range(400)])
    counts = np.array([(many[:, STOCKS] == history[y, STOCKS]).sum() for y in range(len(history))])
    assert counts.min() > 0.75 * counts.mean() and counts.max() < 1.25 * counts.mean()


def test_death_draws_are_per_path_and_member():
    assert np.array_equal(death_uniforms(1, 3, 2), death_uniforms(1, 3, 2))
    assert death_uniforms(1, 3, 2)[0] == death_uniforms(1, 3, 1)[0]
    assert not np.array_equal(death_uniforms(1, 3, 2), death_uniforms(1, 4, 2))
