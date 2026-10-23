"""Unit tests for the engine's building blocks."""

import numpy as np
import pytest

from northward.accounts.allocation import glide_path_equity
from northward.config.accounts import TargetDateStrategy
from northward.config.rules.glide_paths import GlidePathsDoc
from northward.config.rules.market import MarketAssumptionsDoc
from northward.engine.market import deterministic_path
from northward.engine.timeline import Point, age_point
from northward.tax.federal import bracket_tax
from northward.tax.indexing import PriceIndex
from tests.conftest import load_yaml
from tests.engine.helpers import STOCKS, member, moves, run

GLIDE = GlidePathsDoc.model_validate(load_yaml("rules/glide_paths.yaml")).get("linear_default")
PRESETS = MarketAssumptionsDoc.model_validate(load_yaml("rules/market_assumptions.yaml"))


def strategy(**kw):
    return TargetDateStrategy(kind="target_date", target_year=2040, **kw)


@pytest.mark.parametrize(("year", "equity"), [(1990, 0.9), (2000, 0.9), (2020, 0.7), (2040, 0.5), (2060, 0.5)])
def test_linear_glide_path(year, equity):
    assert glide_path_equity(GLIDE, strategy(), year) == pytest.approx(equity)


def test_glide_path_inline_overrides_and_post_target_segment():
    assert glide_path_equity(GLIDE, strategy(target_equity=0.6), 2040) == pytest.approx(0.6)
    post = {"years_after": 10, "final_equity": 0.3}
    assert glide_path_equity(GLIDE, strategy(post_target=post), 2045) == pytest.approx(0.4)
    assert glide_path_equity(GLIDE, strategy(post_target=post), 2060) == pytest.approx(0.3)


def test_deterministic_returns_default_to_the_geometric_mean():
    preset = PRESETS.get("forward_conservative")
    geometric = deterministic_path(preset, 2026, 3)
    arithmetic = deterministic_path(preset, 2026, 3, "arithmetic")
    assert geometric.stocks[0] == pytest.approx(1.07 / np.sqrt(1 + (0.17 / 1.07) ** 2) - 1)
    assert geometric.stocks[0] == pytest.approx(0.0568, abs=1e-4)
    assert arithmetic.stocks[0] == 0.07
    assert geometric.inflation[0] == arithmetic.inflation[0] == 0.025  # normal: the mean


def test_price_index_levels_and_indexing():
    prices = PriceIndex(2026, np.array([0.02, 0.03, 0.04]), pre_start_inflation=0.025, spreads={"education": 0.01})
    assert prices.level(2026) == 1.0
    assert prices.level(2028) == pytest.approx(1.02 * 1.03)
    assert prices.level(2028, "education") == pytest.approx(1.03 * 1.04)
    assert prices.level(2025) == pytest.approx(1 / 1.025)
    assert prices.level(2040) == pytest.approx(1.02 * 1.03 * 1.04)  # held flat past the path
    assert prices.indexed(24500, 2026, 2028, rounding=500) == 25500  # 25,994.5 rounds down
    assert prices.level(2030, "none") == 1.0


def test_bracket_tax_slices():
    schedule = ((10000, 0.1), (50000, 0.2), (float("inf"), 0.3))
    assert bracket_tax(schedule, 0, 60000) == pytest.approx(1000 + 8000 + 3000)
    assert bracket_tax(schedule, 40000, 60000) == pytest.approx(2000 + 3000)  # gains stacked on ordinary income
    assert bracket_tax(schedule, 0, 60000, scale=2.0) == pytest.approx(2000 + 8000)


def test_age_points():
    july = member(birth_year=1976, birth_month=7)
    assert age_point(type("P", (), july)(), 65) == Point(2041, 6 / 12)
    january = member(birth_year=1976, birth_month=1)
    assert age_point(type("P", (), january)(), 59.5) == Point(2035, 6 / 12)


def loan_run(liabilities, years=40):
    return run(
        members=[member(retire=40)],
        accounts=[{"id": "checking", "owner": "pat", "type": "checking", "balance": 2_000_000}],
        liabilities=liabilities,
        horizon={"start_year": 2026, "end_year": 2026 + years - 1},
    )


def test_amortizing_loan_pays_off_on_schedule():
    loan = {"id": "car", "kind": "amortizing", "balance": 18000, "annual_rate": 0.059, "remaining_term_months": 36}
    result = loan_run([loan], years=4)
    balances = [y.liabilities["car"] for y in result.years]
    assert balances[2] == pytest.approx(0, abs=0.01) and balances[3] == 0
    payment = 18000 * (0.059 / 12) / (1 - (1 + 0.059 / 12) ** -36)
    assert result.years[0].flows.debt_payments == pytest.approx(12 * payment)
    assert sum(y.flows.debt_payments for y in result.years) == pytest.approx(36 * payment, abs=0.01)


def test_interest_only_loan_repaid_at_payoff():
    loan = {"id": "heloc", "kind": "interest_only", "balance": 50000, "annual_rate": 0.08, "payoff": {"year": 2028}}
    result = loan_run([loan], years=4)
    assert [round(y.flows.debt_payments) for y in result.years] == [4000, 4000, 54000, 0]


def spending_run(spending, **kw):
    return run(
        members=[member(birth_year=1966, birth_month=7, retire=62)],  # retires mid-2028
        accounts=[{"id": "checking", "owner": "pat", "type": "checking", "balance": 5_000_000}],
        spending=spending,
        horizon={"start_year": 2026, "end_year": 2045},
        preset={"inflation_spreads": {"education": 0.05}},
        **kw,
    )


def test_spending_categories_schedule():
    result = spending_run(
        {
            "base": {"amount": 1000},
            "categories": [
                {"id": "car", "amount": 100, "every_years": 3, "start": {"year": 2027}, "end": {"year": 2034}},
                {"id": "roof", "amount": 50, "once": {"year": 2030}},
                {
                    "id": "travel",
                    "amount": 10,
                    "start": {"event": "retirement", "member": "pat"},
                    "end": {"member": "pat", "age": 64},
                },
                {"id": "never", "amount": 1, "start": {"event": "death", "member": "pat"}},
            ],
        }
    )
    by_year = {y.year: dict(y.flows.spending) for y in result.years}
    assert [y for y in by_year if "car" in by_year[y]] == [2027, 2030, 2033]
    assert [y for y in by_year if "roof" in by_year[y]] == [2030]
    assert [y for y in by_year if "travel" in by_year[y]] == [2028, 2029, 2030]
    assert not any("never" in s for s in by_year.values())


def test_base_spending_phases_retirement_change_and_education_index():
    result = spending_run(
        {
            "base": {
                "amount": 1000,
                "retirement_change": -0.1,
                "phases": {"reference": "pat", "bands": [{"until_age": 70, "multiplier": 1.0}, {"multiplier": 0.5}]},
            },
            "categories": [
                {"id": "school", "amount": 100, "index": "education", "start": {"year": 2027}, "end": {"year": 2027}}
            ],
        }
    )
    base = {y.year: y.flows.spending["base"] for y in result.years}
    assert base[2028] == pytest.approx(1000)  # retires in July 2028, so fully retired from 2029
    assert base[2029] == pytest.approx(900)
    assert base[2037] == pytest.approx(450)  # age 71
    assert result.years[1].flows.spending["school"] == pytest.approx(105)


def test_scenario_contributions_follow_their_window():
    result = run(
        members=[member()],
        accounts=[
            {"id": "checking", "owner": "pat", "type": "checking", "balance": 100000},
            {"id": "roth", "owner": "pat", "type": "roth_ira", "balance": 0, "asset_strategy": STOCKS},
        ],
        income=[{"id": "job", "owner": "pat", "type": "salary", "amount": 60000}],  # IRAs need earned income
        levers={"contributions": [{"account": "roth", "amount": 7000, "end": {"year": 2027}}]},
    )
    assert [moves(result, y, "cash", "roth") for y in (2026, 2027, 2028)] == [7000, 7000, 0]
