"""Monte Carlo configuration: historical returns, Student-t and bootstrap presets, goals, and sampled mortality."""

import numpy as np
import pytest
from pydantic import ValidationError

from northward.config.loader import load_rules, load_simulation_input
from northward.config.rules.historical_returns import HistoricalReturnsDoc
from northward.config.rules.market import FACTORS, MarketPreset
from northward.config.source import FileSource
from northward.engine.simulate import simulate
from northward.engine.timeline import Timeline
from northward.lifecycle.mortality import age_at_start, planned_death_ages
from northward.tax.indexing import PriceIndex
from tests.config.test_loader import edit, edit_scenario, issues, source  # noqa: F401 (fixture)
from tests.conftest import DATA_DIR, load_yaml

RULES = load_rules(FileSource(DATA_DIR))
HISTORY = RULES.historical_returns.matrix()


def test_historical_returns_cover_1928_to_2025():
    returns = RULES.historical_returns.returns
    assert (min(returns), max(returns), len(returns)) == (1928, 2025, 98)
    assert returns[2008].stocks == pytest.approx(-0.3655, abs=1e-4)
    assert returns[1932].inflation == pytest.approx(-0.1027, abs=1e-4)  # deflation years are kept
    assert returns[1946].inflation == pytest.approx(0.1813, abs=1e-4)


def test_historical_years_must_be_consecutive():
    data = load_yaml("rules/historical_returns.yaml")
    del data["returns"][1950]
    with pytest.raises(ValidationError, match="consecutive"):
        HistoricalReturnsDoc.model_validate(data)


def test_historical_us_preset_is_computed_from_the_history():
    preset = RULES.market_assumptions.get("historical_us")
    means, std_devs = HISTORY.mean(axis=0), HISTORY.std(axis=0, ddof=1)
    for i, factor in enumerate(FACTORS):
        assert preset.factors[factor].mean == pytest.approx(means[i], abs=0.0005), factor
        assert preset.factors[factor].std_dev == pytest.approx(std_devs[i], abs=0.0005), factor
    assert np.allclose(preset.correlation_matrix(), np.corrcoef(HISTORY.T), atol=0.005)
    inflation = preset.factors["inflation"]
    assert inflation.min_bound <= HISTORY[:, 3].min() + 0.0005 and inflation.max_bound >= HISTORY[:, 3].max() - 0.0005


def test_bootstrap_preset_describes_the_history(source):  # noqa: F811
    edit_scenario(source, lambda d: d.update(market={"preset": "bootstrap", "overrides": {"block_length": 8}}))
    sim = load_simulation_input(source, "example", "base")
    assert sim.market.kind == "bootstrap" and sim.market.block_length == 8
    assert sim.market.factors["stocks"].mean == pytest.approx(HISTORY[:, 0].mean())
    assert np.allclose(sim.market.correlation_matrix(), np.corrcoef(HISTORY.T))
    simulate(sim)  # a deterministic run uses the historical averages


def test_bootstrap_presets_reject_factor_overrides(source):  # noqa: F811
    edit_scenario(
        source, lambda d: d.update(market={"preset": "bootstrap", "overrides": {"factors.stocks.mean": 0.05}})
    )
    assert any("can't override factors.stocks.mean" in i for i in issues(source))


def test_preset_validation_for_new_kinds():
    data = load_yaml("rules/market_assumptions.yaml")["presets"]
    forward, bootstrap = data[0], data[2]
    MarketPreset.model_validate({**forward, "distribution": "student_t", "degrees_of_freedom": 4})
    with pytest.raises(ValidationError, match="greater than 2"):
        MarketPreset.model_validate({**forward, "distribution": "student_t", "degrees_of_freedom": 2})
    with pytest.raises(ValidationError, match="correlations from rules/historical_returns"):
        MarketPreset.model_validate({**bootstrap, "correlations": {"stocks": {"bonds": 0.1}}})
    with pytest.raises(ValidationError, match="factors missing"):
        MarketPreset.model_validate({**forward, "factors": {"stocks": {"mean": 0.07, "std_dev": 0.17}}})


def test_goals_default_when_the_document_is_missing(source):  # noqa: F811
    del source.profile_docs["example"]["goals"]
    goals = load_simulation_input(source, "example", "base").profile.goals
    assert goals.success.no_shortfall and goals.success.liquidity_floor is None
    assert goals.legacy.heirs_tax_rate == 0.25


def test_goals_are_validated_and_can_be_overridden_by_a_scenario(source):  # noqa: F811
    goals = load_simulation_input(source, "example", "base").profile.goals
    assert goals.success.liquidity_floor.amount == 50_000
    edit_scenario(source, lambda d: d.update(overrides={"goals": {"success.liquidity_floor.amount": 80_000}}))
    assert load_simulation_input(source, "example", "base").profile.goals.success.liquidity_floor.amount == 80_000

    edit(
        source, "goals", lambda d: d["success"]["liquidity_floor"].update(start={"event": "retirement", "member": "x"})
    )
    assert "profiles/example/goals.yaml: success.liquidity_floor.start: unknown member 'x'" in issues(source)
    edit(source, "goals", lambda d: d["legacy"].update(heirs_tax_rate=1.5))
    assert any("legacy.heirs_tax_rate" in i for i in issues(source))


def test_sampled_mortality_uses_life_expectancy_in_deterministic_runs(source):  # noqa: F811
    edit_scenario(source, lambda d: d["levers"].update(mortality={"kind": "sampled"}))
    sim = load_simulation_input(source, "example", "base")
    ages = planned_death_ages(sim)
    for member in sim.profile.household.members:
        expected = RULES.mortality.expected_death_age(member.sex, age_at_start(member, 2026))
        assert ages[member.id] == pytest.approx(expected, abs=1 / 24)
    result = simulate(sim)
    assert result.years[-1].year == max(p.year for p in Timeline(sim).deaths.values())


def test_sampled_lifespans_past_end_age_extend_the_horizon(source):  # noqa: F811
    edit_scenario(source, lambda d: d["levers"].update(mortality={"kind": "sampled"}))
    sim = load_simulation_input(source, "example", "base")
    timeline = Timeline(sim, {"alex": 101.5, "jordan": 90.5})
    assert timeline.end_year == 1978 + 102  # alex dies in 2080, past the age-95 horizon (2076)
    # A fixed lever caps deaths at the horizon.
    edit_scenario(source, lambda d: d["levers"].update(mortality={"kind": "fixed", "death_ages": {"alex": 101.5}}))
    assert Timeline(load_simulation_input(source, "example", "base")).end_year == 2076


def test_life_table_inversion():
    table = RULES.mortality
    ages, cdf = table.death_distribution("female", 44.25)
    assert ages[0] == pytest.approx((44.25 + 45) / 2) and ages[1] == 45.5
    assert cdf[-1] == pytest.approx(1.0)
    assert table.death_age("female", 44.25, 0.0) == ages[0]
    assert table.death_age("female", 44.25, 0.5) == ages[int(np.searchsorted(cdf, 0.5, side="right"))]
    assert table.expected_death_age("male", 65) == pytest.approx(65 + table.life_expectancy("male", 65))


def test_cost_of_living_adjustments_never_go_negative():
    prices = PriceIndex(2026, np.array([0.03, -0.10, 0.04, 0.08, 0.02]), 0.025, {})
    levels = [prices.level(y) for y in range(2026, 2032)]
    cola = [prices.cola_level(y) for y in range(2026, 2032)]
    assert cola[:2] == levels[:2]
    assert cola[2] == cola[3] == levels[1]  # held through deflation until prices pass their old peak
    assert cola[4] == levels[4] and cola[5] == levels[5]
