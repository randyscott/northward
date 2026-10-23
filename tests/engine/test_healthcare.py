"""Healthcare costs: coverage by stage of life, IRMAA's two-year lookback, pre-tax premiums, and HSA reimbursement."""

import pytest

from northward.ledger.transaction import CASH
from tests.engine.helpers import STOCKS, member, moves, run
from tests.engine.test_distributions import ZERO_GROWTH

COSTS = {
    "employer_premium": 6000,
    "individual_premium_age_40": 7500,
    "part_d_premium": 420,
    "supplement_premium": 2160,
    "out_of_pocket_under_65": 1500,
    "out_of_pocket_65_plus": 2000,
    "hsa_medical": "never",
}


def couple(**kw):
    args = dict(
        members=[member("a", 1962, 1, 60), member("b", 1962, 1, 60)],  # 64 in 2026, Medicare from Jan 2027
        accounts=[
            {"id": "checking", "owner": "joint", "type": "checking", "balance": 3_000_000, "interest_rate": 0.0},
            {"id": "a_ira", "owner": "a", "type": "traditional_ira", "balance": 1_000_000, "asset_strategy": STOCKS},
            {"id": "a_roth", "owner": "a", "type": "roth_ira", "balance": 0, "asset_strategy": STOCKS},
        ],
        spending=0,
        health_costs=COSTS,
        preset=ZERO_GROWTH,
        horizon={"start_year": 2026, "end_year": 2030},
    )
    args.update(kw)
    return run(**args)


def test_unsubsidized_individual_market_before_medicare_then_medicare():
    by_year = {y.year: y.flows.spending for y in couple().years}
    # 2026: both 64, no employer coverage: 7,500 x (3.0 / 1.278) each, plus out-of-pocket.
    assert by_year[2026]["healthcare_premiums"] == pytest.approx(2 * 7500 * 3.0 / 1.278)
    assert by_year[2026]["healthcare_out_of_pocket"] == pytest.approx(2 * 1500)
    # 2027: Medicare all year: Part B (202.90/mo), Part D plan, and a supplement, per person.
    assert by_year[2027]["healthcare_premiums"] == pytest.approx(2 * (202.90 * 12 + 420 + 2160))
    assert by_year[2027]["healthcare_out_of_pocket"] == pytest.approx(2 * 2000)


def test_irmaa_uses_magi_from_two_years_earlier():
    conversion = {"kind": "fixed_amount", "amount": 300000, "start_year": 2027, "end_year": 2027}
    result = couple(levers={"roth_conversions": conversion})
    irmaa = {y.year: y.flows.spending.get("medicare_irmaa", 0.0) for y in result.years}
    agi = {y.year: y.flows.taxes.agi for y in result.years}
    assert 274000 < agi[2027] <= 342000  # joint tier 3
    assert irmaa[2027] == 0 and irmaa[2028] == 0
    assert irmaa[2029] == pytest.approx(2 * 12 * (202.90 + 37.50))  # from the 2027 return
    assert irmaa[2030] == 0


def test_employer_premium_is_pre_tax_and_covers_the_family():
    result = couple(
        members=[member("a", 1980, 1, 65), member("b", 1980, 1, 65)],
        income=[{"id": "job", "owner": "a", "type": "salary", "amount": 100000}],
        horizon={"start_year": 2026, "end_year": 2026},
    )
    flows = result.years[0].flows
    assert flows.spending["healthcare_premiums"] == pytest.approx(6000)  # no individual-market premiums
    assert flows.taxes.wages == pytest.approx(100000 - 6000)


def test_hsa_pays_qualified_costs_after_retirement():
    hsa = {"id": "a_hsa", "owner": "a", "type": "hsa", "balance": 50000, "asset_strategy": STOCKS}
    checking = {"id": "checking", "owner": "joint", "type": "checking", "balance": 3_000_000, "interest_rate": 0.0}
    result = couple(accounts=[checking, hsa], health_costs={**COSTS, "hsa_medical": "pay_when_retired"})
    y2027 = result.years[1].flows
    qualified = 2 * (202.90 * 12 + 420 + 2000)  # Part B, Part D, out-of-pocket (the supplement isn't qualified)
    assert moves(result, 2027, "a_hsa", CASH) == pytest.approx(qualified)
    assert y2027.hsa_medical == pytest.approx(qualified)
    assert y2027.taxes.agi == 0  # tax-free


def test_includes_healthcare_turns_the_model_off():
    result = couple(spending={"base": {"amount": 0, "includes_healthcare": True}})
    assert all("healthcare_premiums" not in y.flows.spending for y in result.years)


def test_hsa_contributions_stop_at_medicare():
    result = run(
        members=[member("a", 1961, 7, 70)],  # turns 65 in July 2026
        accounts=[
            {"id": "checking", "owner": "a", "type": "checking", "balance": 0},
            {"id": "hsa", "owner": "a", "type": "hsa", "balance": 0, "asset_strategy": STOCKS},
        ],
        income=[
            {
                "id": "job",
                "owner": "a",
                "type": "salary",
                "amount": 100000,
                "elections": {
                    "hsa": {"account": "hsa", "coverage": "self_only", "max": True, "include_catch_up": True}
                },
            }
        ],
        horizon={"start_year": 2026, "end_year": 2027},
    )
    assert moves(result, 2026, CASH, "hsa") == pytest.approx((4400 + 1000) * 6 / 12)
    assert moves(result, 2027, CASH, "hsa") == 0


def test_irmaa_after_a_death_uses_the_joint_return_from_two_years_earlier():
    """High-income joint year (2027), a death in 2028: in 2029 the survivor alone pays the surcharge set by the
    2027 joint return (no life-changing-event appeal is modeled)."""
    conversion = {"kind": "fixed_amount", "amount": 300000, "start_year": 2027, "end_year": 2027}
    result = couple(levers={"roth_conversions": conversion, "mortality": {"kind": "fixed", "death_ages": {"b": 66.5}}})
    by_year = {y.year: y for y in result.years}
    assert by_year[2028].flows.taxes.filing_status.value == "married_filing_jointly"  # year of death
    assert by_year[2029].flows.taxes.filing_status.value == "single"
    assert by_year[2029].flows.spending["medicare_irmaa"] == pytest.approx(12 * (202.90 + 37.50))  # one enrollee
