import numpy as np
import pytest

from northward.config.goals import GoalsDoc
from northward.config.loader import load_simulation_input
from northward.config.source import FileSource
from northward.montecarlo import stats, telemetry
from northward.montecarlo.telemetry import BUCKET_INDEX, BUCKETS, MonteCarloResult
from tests.conftest import DATA_DIR

SIM = load_simulation_input(FileSource(DATA_DIR), "example", "base")  # alex retires in 2040
YEARS = 20  # 2026-2045


def mc(values: dict[str, list[list[float]]], sims: int = 3, seed: int = 1, scenario: str = "base") -> MonteCarloResult:
    """Telemetry with flat defaults (price level 1, $1M everywhere) and the given per-path, per-year overrides."""
    data = np.zeros((sims, YEARS, len(BUCKETS)))
    data[:, :, BUCKET_INDEX["price_level"]] = 1.0
    for name in ("net_worth", "total_assets", "liquid", "taxable"):
        data[:, :, BUCKET_INDEX[name]] = 1_000_000
    for name, rows in values.items():
        for i, row in enumerate(rows):
            data[i, : len(row), BUCKET_INDEX[name]] = row
    return MonteCarloResult(
        profile="example",
        scenario=scenario,
        seed=seed,
        preset="test",
        sampler="parametric",
        mortality="none",
        start_year=2026,
        members=("alex", "jordan"),
        telemetry=data,
        market=np.zeros((sims, YEARS, 4)),
        death_ages=np.full((sims, 2), np.nan),
        engine_version="test",
    )


def goals(**success) -> GoalsDoc:
    return GoalsDoc.model_validate({"schema_version": 1, "success": success})


def test_any_shortfall_beyond_the_tolerance_fails_a_path():
    shortfalls = [[0.0] * 5 + [0.5], [0.0] * 7 + [2.0, 50.0], [0.0]]
    result = stats.evaluate_success(mc({"shortfall": shortfalls}), SIM, goals())
    assert result.success.tolist() == [True, False, True]
    assert result.first_failure.tolist() == [-1, 7, -1]
    assert result.probability == pytest.approx(2 / 3)
    assert stats.evaluate_success(mc({"shortfall": shortfalls}), SIM, goals(no_shortfall=False)).success.all()
    loose = stats.evaluate_success(mc({"shortfall": shortfalls}), SIM, goals(shortfall_tolerance=100))
    assert loose.success.all()


def test_the_liquidity_floor_is_in_todays_dollars_and_starts_at_its_anchor():
    floor = {"amount": 50_000, "start": {"event": "retirement", "member": "alex"}}
    liquid = [
        [10_000] * 14 + [60_000] * 6,  # short only before alex retires in 2040: passes
        [60_000] * 16 + [90_000] * 4,  # 90k nominal is 45k in today's dollars from 2042 (price level 2): fails
        [60_000] * 20,
    ]
    price = [[1.0] * 20, [1.0] * 16 + [2.0] * 4, [1.0] * 20]
    result = stats.evaluate_success(mc({"liquid": liquid, "price_level": price}), SIM, goals(liquidity_floor=floor))
    assert result.success.tolist() == [True, False, True]
    assert result.failures["liquidity_floor"].tolist() == [False, True, False]
    assert 2026 + result.first_failure[1] == 2042
    always = goals(liquidity_floor={"amount": 50_000})
    assert stats.evaluate_success(mc({"liquid": liquid, "price_level": price}), SIM, always).success.tolist() == [
        False,
        False,
        True,
    ]


def test_years_after_a_path_ends_are_ignored():
    run = mc({"shortfall": [[0.0] * 10]})
    run.telemetry[0, 10:, :] = np.nan  # path 0 ended in 2035
    run.telemetry[0, 9, BUCKET_INDEX["net_worth"]] = 400_000
    floor = goals(liquidity_floor={"amount": 50_000})
    assert stats.evaluate_success(run, SIM, floor).success.all()
    outcomes = stats.path_outcomes(run, GoalsDoc(schema_version=1))
    assert outcomes.terminal_net_worth[0] == 400_000
    assert outcomes.final_year.tolist() == [2035, 2045, 2045]


def test_legacy_haircuts_pre_tax_accounts_at_the_heirs_rate():
    run = mc({"deferred": [[0.0] * 19 + [400_000]], "hsa": [[0.0] * 19 + [100_000]], "price_level": [[2.0] * 20]})
    outcomes = stats.path_outcomes(
        run, GoalsDoc.model_validate({"schema_version": 1, "legacy": {"heirs_tax_rate": 0.3}})
    )
    assert outcomes.legacy_after_tax[0] == 1_000_000 - 0.3 * 500_000
    assert outcomes.legacy_after_tax_real[0] == outcomes.legacy_after_tax[0] / 2
    assert outcomes.legacy_after_tax[1] == 1_000_000


def test_lifetime_taxes_sum_nominal_and_real_dollars():
    run = mc({"total_taxes": [[10_000] * 20], "price_level": [[1.0] * 10 + [2.0] * 10]})
    outcomes = stats.path_outcomes(run, GoalsDoc(schema_version=1))
    assert outcomes.lifetime_taxes[0] == 200_000
    assert outcomes.lifetime_taxes_real[0] == 150_000


def test_bands_and_representative_paths():
    net_worth = [[100.0 * (i + 1)] * 20 for i in range(5)]
    run = mc({"net_worth": net_worth}, sims=5)
    run.telemetry[4, 15:, :] = np.nan
    bands = stats.bands(run)
    assert bands["net_worth"]["nominal"]["p50"][0] == 300
    assert bands["net_worth"]["nominal"]["p50"][19] == 250  # paths 0-3 only
    assert "real" not in bands["members_alive"]
    assert stats.representative_paths(np.array([5.0, 1.0, 3.0, 2.0, 4.0])) == {
        "p10": 1,
        "p25": 3,
        "p50": 2,
        "p75": 4,
        "p90": 0,
    }


def test_summary_counts_first_failure_years():
    run = mc({"shortfall": [[0.0] * 7 + [5.0], [0.0] * 3 + [5.0], [0.0] * 7 + [5.0]]})
    summary = stats.summarize(run, SIM, goals())
    assert summary["success"]["probability"] == 0
    assert summary["success"]["first_failure_year"] == {2029: 1, 2033: 2}
    assert summary["success"]["median_first_failure_year"] == 2033
    assert summary["paths_running"] == [3] * 20


def test_comparisons_are_paired_by_path():
    base = mc(
        {"net_worth": [[1_000.0] * 20, [2_000.0] * 20, [3_000.0] * 20], "shortfall": [[0.0], [0.0], [0.0] * 4 + [9.0]]}
    )
    other = mc(
        {"net_worth": [[1_500.0] * 20, [1_000.0] * 20, [3_600.0] * 20], "shortfall": [[0.0], [0.0] * 2 + [9.0], [0.0]]},
        scenario="other",
    )
    result = stats.compare([(base, SIM), (other, SIM)], goals())
    vs = result["scenarios"][1]["vs_first"]
    assert vs["legacy_higher_probability"] == pytest.approx(2 / 3)
    assert vs["legacy_after_tax_real_difference"]["p50"] == 500
    assert vs["succeeds_where_first_fails"] == pytest.approx(1 / 3)
    assert vs["fails_where_first_succeeds"] == pytest.approx(1 / 3)
    with pytest.raises(ValueError, match="same seed"):
        stats.compare([(base, SIM), (mc({}, seed=2), SIM)], goals())


def test_telemetry_round_trips_through_npz(tmp_path):
    run = mc({"shortfall": [[0.0] * 3 + [5.0]]})
    run.telemetry[2, 12:, :] = np.nan
    loaded = telemetry.load(telemetry.save(run, tmp_path / "t.npz"))
    assert np.array_equal(loaded.telemetry, run.telemetry, equal_nan=True)
    assert (loaded.profile, loaded.scenario, loaded.members) == (run.profile, run.scenario, run.members)
    assert stats.summarize(loaded, SIM, goals())["success"] == stats.summarize(run, SIM, goals())["success"]


def test_reports_never_round_rare_failures_away():
    from northward.montecarlo.report import _percent

    assert [_percent(v) for v in (0.0, 0.0001, 0.0006, 0.5, 0.9994, 0.9999, 1.0)] == [
        "0.0%",
        "<0.1%",
        "0.1%",
        "50.0%",
        "99.9%",
        ">99.9%",
        "100.0%",
    ]
