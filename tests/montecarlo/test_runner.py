import os
import pickle
import subprocess
import sys

import numpy as np
import pytest
import yaml

from northward.config.loader import SimulationInput, load_simulation_input
from northward.config.rules.market import FACTORS
from northward.config.source import FileSource, MemorySource
from northward.engine.simulate import simulate
from northward.engine.timeline import Timeline
from northward.lifecycle.mortality import age_at_start
from northward.montecarlo.runner import run_monte_carlo, simulate_path
from northward.montecarlo.telemetry import BUCKET_INDEX, telemetry_rows
from tests.conftest import DATA_DIR

ZERO_VOLATILITY = {f"factors.{f}.std_dev": 0.0 for f in FACTORS}


def example(scenario: str = "base", market: dict | None = None, levers: dict | None = None) -> SimulationInput:
    """An example-profile scenario, with market overrides and lever changes applied."""
    source = MemorySource.copy_of(FileSource(DATA_DIR))
    doc = yaml.safe_load(source.scenario_docs["example"][scenario])
    if market:
        doc.setdefault("market", {}).setdefault("overrides", {}).update(market)
    if levers:
        doc["levers"].update(levers)
    source.scenario_docs["example"][scenario] = yaml.safe_dump(doc)
    return load_simulation_input(source, "example", scenario)


def test_zero_variance_monte_carlo_equals_the_deterministic_run():
    sim = example(market=ZERO_VOLATILITY)
    mc = run_monte_carlo(sim, 3, seed=11, workers=1)
    deterministic = telemetry_rows(simulate(sim))
    for path in mc.telemetry:
        assert np.array_equal(path, deterministic)


def test_zero_variance_holds_for_the_full_survivor_scenario():
    sim = example("survivor", market=ZERO_VOLATILITY)
    mc = run_monte_carlo(sim, 2, seed=3, workers=1)
    assert np.array_equal(mc.telemetry[1], telemetry_rows(simulate(sim)))


def test_a_seeded_run_is_reproducible_bit_for_bit_however_it_is_split():
    sim = example()
    one = run_monte_carlo(sim, 12, seed=5, workers=1)
    pooled = run_monte_carlo(sim, 12, seed=5, workers=3, chunk_size=2)
    assert np.array_equal(one.telemetry, pooled.telemetry)
    assert np.array_equal(one.market, pooled.market)
    other_seed = run_monte_carlo(sim, 12, seed=6, workers=1)
    assert not np.array_equal(one.telemetry, other_seed.telemetry)
    # The first paths of a bigger run are the same paths.
    assert np.array_equal(run_monte_carlo(sim, 4, seed=5, workers=1).telemetry, one.telemetry[:4])


_RUN_IN_SUBPROCESS = """
import sys
import numpy as np
from northward.config.loader import load_simulation_input
from northward.config.source import FileSource
from northward.montecarlo.runner import run_monte_carlo
sim = load_simulation_input(FileSource(sys.argv[1]), "example", "survivor")
np.save(sys.argv[2], run_monte_carlo(sim, 20, seed=4, workers=1).telemetry)
"""


def test_results_dont_depend_on_the_processs_string_hash_seed(tmp_path):
    """Set iteration order changes with PYTHONHASHSEED, which differs between processes, so a rerun in a new process
    (a later CLI call, or a stored run reproduced) must not depend on it."""
    outputs = []
    for hash_seed in ("1", "2", "3"):
        out = tmp_path / f"telemetry-{hash_seed}.npy"
        env = {**os.environ, "PYTHONHASHSEED": hash_seed}
        subprocess.run([sys.executable, "-c", _RUN_IN_SUBPROCESS, str(DATA_DIR), str(out)], check=True, env=env)
        outputs.append(np.load(out))
    assert all(np.array_equal(outputs[0], other, equal_nan=True) for other in outputs[1:])


def test_any_path_can_be_rerun_with_the_ledger():
    sim = example()
    mc = run_monte_carlo(sim, 6, seed=21, workers=1)
    drill = simulate_path(sim, seed=21, index=4)
    assert drill.transactions  # the ledger is on
    assert np.array_equal(telemetry_rows(drill), mc.telemetry[4])
    stocks = np.array([y.price_level for y in drill.years])
    assert np.array_equal(stocks, mc.bucket("price_level")[4])


def test_paths_differ_and_market_arrays_hold_what_each_path_ran_on():
    sim = example()
    mc = run_monte_carlo(sim, 8, seed=2, workers=1)
    assert len({float(nw) for nw in mc.bucket("net_worth")[:, -1]}) == 8
    inflation = mc.market[:, :, FACTORS.index("inflation")]
    price = mc.bucket("price_level")
    assert np.allclose(price[:, 1:], np.cumprod(1 + inflation[:, :-1], axis=1))


def test_scenarios_compared_on_one_seed_share_their_draws():
    base = run_monte_carlo(example(), 5, seed=8, workers=1)
    later_ss = run_monte_carlo(example(levers={"ss_claim_ages": {"alex": 70, "jordan": 70}}), 5, seed=8, workers=1)
    assert np.array_equal(base.market, later_ss.market)
    assert not np.array_equal(base.bucket("social_security"), later_ss.bucket("social_security"))


def test_sampled_lifespans_vary_by_path_and_can_run_past_end_age():
    sim = example(levers={"mortality": {"kind": "sampled"}})
    mc = run_monte_carlo(sim, 200, seed=4, workers=1)
    assert not np.isnan(mc.death_ages).any()  # everyone dies within their path's horizon
    alive = mc.bucket("members_alive")
    finals = mc.start_year + mc.active.sum(axis=1) - 1
    planning_end = Timeline(example()).end_year
    assert finals.min() < planning_end - 10 and finals.max() > planning_end  # some households outlive age 95
    for i in range(20):
        timeline = Timeline(sim, mc.death_ages_of(i))
        assert finals[i] == timeline.end_year == max(p.year for p in timeline.deaths.values())
        assert np.isnan(mc.telemetry[i, finals[i] - mc.start_year + 1 :]).all()
        assert alive[i, finals[i] - mc.start_year] >= 1
    # Ages at death follow the life table (alex: male, 47 at the start; jordan: female, 44).
    table = sim.rules.mortality
    for j, member in enumerate(sim.profile.household.members):
        expected = table.expected_death_age(member.sex, age_at_start(member, 2026))
        assert mc.death_ages[:, j].mean() == pytest.approx(expected, abs=2.0)  # ~2.3 standard errors at 200 paths
        assert mc.death_ages[:, j].min() > age_at_start(member, 2026)
    drill = simulate_path(sim, seed=4, index=17, record=False)
    assert np.array_equal(telemetry_rows(drill), mc.telemetry[17, : len(drill.years)])


def test_sampled_lifespans_are_common_to_compared_scenarios():
    a = run_monte_carlo(example(levers={"mortality": {"kind": "sampled"}}), 10, seed=4, workers=1)
    b = run_monte_carlo(
        example(levers={"mortality": {"kind": "sampled"}, "ss_claim_ages": {"alex": 62, "jordan": 62}}),
        10,
        seed=4,
        workers=1,
    )
    assert np.array_equal(a.death_ages, b.death_ages)


def test_bootstrap_paths_run_on_historical_years():
    sim = example("historical_lifespans")
    mc = run_monte_carlo(sim, 4, seed=1, workers=1)
    history = sim.rules.historical_returns.matrix()
    years = mc.market[0][~np.isnan(mc.market[0, :, 0])]
    assert all((history == row).all(axis=1).any() for row in years)


def test_simulation_inputs_pickle_by_reloading_their_documents():
    sim = example()
    copy = pickle.loads(pickle.dumps(sim))
    assert copy == sim
    assert telemetry_rows(simulate(copy)).tolist() == telemetry_rows(simulate(sim)).tolist()


def test_telemetry_buckets_add_up():
    result = simulate(example("survivor"))
    rows = telemetry_rows(result)
    b = BUCKET_INDEX
    assert np.allclose(
        rows[:, b["federal_tax"]] + rows[:, b["state_tax"]] + rows[:, b["fica"]], rows[:, b["total_taxes"]]
    )
    wrappers = sum(rows[:, b[k]] for k in ("taxable", "deferred", "roth", "hsa", "education"))
    cash = np.array([y.cash for y in result.years])
    assert np.allclose(wrappers + cash, rows[:, b["total_assets"]])
    assert np.allclose(rows[:, b["liquid"]], rows[:, b["taxable"]] + cash)
    assert np.allclose(rows[:, b["net_worth"]], rows[:, b["total_assets"]] - rows[:, b["liabilities"]])
    assert rows[:, b["members_alive"]].tolist() == [len(y.ages) for y in result.years]
    assert rows[:, b["irmaa"]].max() <= rows[:, b["healthcare"]].max() <= rows[:, b["spending"]].max()
