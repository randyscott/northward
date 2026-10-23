"""RMDs, inherited IRAs, and Roth conversions."""

import pytest

from northward.ledger.transaction import CASH
from tests.engine.helpers import STOCKS, member, moves, run

ZERO_GROWTH = {
    "factors": {
        "stocks": {"mean": 0.0, "std_dev": 0.0},
        "bonds": {"mean": 0.0, "std_dev": 0.0},
        "cash": {"mean": 0.0, "std_dev": 0.0},
        "inflation": {"mean": 0.0, "std_dev": 0.0, "distribution": "normal"},
    }
}


def test_rmd_matches_the_uniform_lifetime_table():
    result = run(
        members=[member(birth_year=1951, retire=65)],
        accounts=[
            {"id": "ira", "owner": "pat", "type": "traditional_ira", "balance": 500000, "asset_strategy": STOCKS}
        ],
        horizon={"start_year": 2026, "end_year": 2027},
    )
    assert result.years[0].flows.rmds == pytest.approx(500000 / 24.6)  # age 75
    after = (500000 - 500000 / 24.6) * 1.05
    assert result.years[1].flows.rmds == pytest.approx(after / 23.7)  # age 76, prior year-end balance


def test_rmds_start_at_75_for_1960_births_and_401k_waits_for_retirement():
    common = dict(horizon={"start_year": 2034, "end_year": 2036})
    ira = run(
        members=[member(birth_year=1960, retire=60)],
        accounts=[
            {"id": "ira", "owner": "pat", "type": "traditional_ira", "balance": 100000, "asset_strategy": STOCKS}
        ],
        **common,
    )
    assert [y.flows.rmds > 0 for y in ira.years] == [False, True, True]  # turns 75 in 2035
    working = run(
        members=[member(birth_year=1960, retire=77)],
        accounts=[
            {"id": "k401", "owner": "pat", "type": "traditional_401k", "balance": 100000, "asset_strategy": STOCKS},
            {"id": "checking", "owner": "pat", "type": "checking", "balance": 0},
        ],
        income=[{"id": "job", "owner": "pat", "type": "salary", "amount": 50000}],
        **common,
    )
    assert all(y.flows.rmds == 0 for y in working.years)  # still working: the employer plan waits


INHERITANCE = {
    "id": "aunt",
    "kind": "inheritance",
    "when": {"year": 2026},
    "amount": 100000,
    "beneficiary": "pat",
    "asset": "inherited_ira",
    "account": "aunt_ira",
}


def test_inherited_ira_minimum_rmds_then_full_distribution_in_year_ten():
    result = run(**_inherited_args({"kind": "minimum_then_final"}))
    by_year = {y.year: y.flows.inherited_distributions for y in result.years}
    assert by_year[2026] == 0  # year of death
    assert by_year[2027] == pytest.approx(100000 / 36.2)  # single life at 50
    balance = 100000 - 100000 / 36.2
    assert by_year[2028] == pytest.approx(balance / 35.2)  # minus one each year
    remaining = sum(by_year[y] for y in range(2027, 2036))
    assert by_year[2036] == pytest.approx(100000 - remaining)  # emptied in the 10th year
    assert by_year[2037] == 0


def test_inherited_ira_even_strategy():
    result = run(**_inherited_args({"kind": "even"}))
    by_year = {y.year: y.flows.inherited_distributions for y in result.years}
    assert by_year[2027] == pytest.approx(100000 / 10)
    assert sum(by_year.values()) == pytest.approx(100000)


def _inherited_args(strategy):
    return dict(
        members=[member(birth_year=1977, retire=45)],
        accounts=[{"id": "checking", "owner": "pat", "type": "checking", "balance": 1_000_000, "interest_rate": 0.0}],
        levers={"inherited_ira": strategy},
        preset=ZERO_GROWTH,
        horizon={"start_year": 2026, "end_year": 2037},
        events=[INHERITANCE],
    )


def retired_couple(conversions, **kw):
    args = dict(
        members=[
            {**member("a", 1960, 1, 60), "social_security": {"pia_at_fra": 2500}},
            {**member("b", 1960, 1, 60), "social_security": {"pia_at_fra": 1500}},
        ],
        accounts=[
            {"id": "a_ira", "owner": "a", "type": "traditional_ira", "balance": 2_000_000, "asset_strategy": STOCKS},
            {"id": "a_roth", "owner": "a", "type": "roth_ira", "balance": 0, "asset_strategy": STOCKS},
            {
                "id": "brokerage",
                "owner": "joint",
                "type": "brokerage",
                "balance": 500000,
                "cost_basis": 500000,
                "asset_strategy": STOCKS,
            },
        ],
        spending=60000,
        levers={"ss_claim_ages": {"a": 66, "b": 66}, "roth_conversions": conversions},
        preset=ZERO_GROWTH,
        horizon={"start_year": 2026, "end_year": 2026},
    )
    args.update(kw)
    return run(**args)


def test_fill_to_22_percent_bracket_lands_within_a_dollar():
    """Couple at 66 with Social Security and the senior deduction: each converted dollar also makes more of the
    benefits taxable and shrinks the senior deduction, so the amount has to be solved for."""
    result = retired_couple({"kind": "fill_bracket", "bracket_rate": 0.22, "start_year": 2026, "end_year": 2026})
    taxes = result.years[0].flows.taxes
    ordinary_taxable = taxes.ordinary_income - taxes.deduction
    assert 211400 - 1 <= ordinary_taxable <= 211400
    assert result.years[0].flows.roth_conversions > 150000
    assert taxes.taxable_social_security == pytest.approx(0.85 * result.years[0].flows.social_security)


def test_respect_phase_outs_stops_at_the_senior_deduction_threshold():
    result = retired_couple(
        {"kind": "fill_bracket", "bracket_rate": 0.22, "start_year": 2026, "end_year": 2026, "respect_phase_outs": True}
    )
    taxes = result.years[0].flows.taxes
    assert taxes.agi == pytest.approx(150000, abs=1.0)
    assert taxes.senior_deduction == pytest.approx(12000)


def test_fixed_conversion_paying_tax_from_the_conversion():
    result = retired_couple(
        {"kind": "fixed_amount", "amount": 50000, "start_year": 2026, "end_year": 2026, "pay_tax_from": "conversion"}
    )
    year = result.years[0]
    to_roth = moves(result, 2026, "a_ira", "a_roth")
    withheld = moves(result, 2026, "a_ira", CASH)
    assert to_roth + withheld == pytest.approx(50000)
    assert 0 < withheld < 50000 * 0.25
    assert year.flows.roth_conversions == pytest.approx(50000)
