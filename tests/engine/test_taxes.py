"""Stage 5 in the engine: tax inputs from the books, settlement, carryforwards, and filing-status checks."""

import pytest

from northward.ledger.transaction import CASH
from tests.engine.helpers import STOCKS, member, moves, run

KID = {"id": "kid", "name": "Kid", "birth_year": 2016, "birth_month": 6, "full_time_student_ages": [18, 21]}


def test_credits_flow_from_dependents_and_tagged_spending():
    result = run(
        members=[member()],
        dependents=[KID],
        filing_status="head_of_household",
        accounts=[{"id": "checking", "owner": "pat", "type": "checking", "balance": 500000, "interest_rate": 0.0}],
        income=[{"id": "job", "owner": "pat", "type": "salary", "amount": 70000}],  # under the AOTC phase-out
        spending={
            "base": {"amount": 40000},
            "categories": [
                {"id": "care", "amount": 4000, "tags": ["dependent_care"], "end": {"dependent": "kid", "age": 12}},
                {
                    "id": "college",
                    "amount": 20000,
                    "tags": ["qualified_education"],
                    "beneficiary": "kid",
                    "start": {"dependent": "kid", "age": 18},
                    "end": {"dependent": "kid", "age": 21},
                },
            ],
        },
        horizon={"start_year": 2026, "end_year": 2038},
    )
    by_year = {y.year: y.flows.taxes for y in result.years}
    assert by_year[2026].filing_status.value == "head_of_household"
    assert by_year[2026].credits.child_tax_credit == pytest.approx(2200)
    assert by_year[2026].credits.dependent_care > 0
    assert by_year[2029].credits.dependent_care == 0  # 13 in 2029
    assert by_year[2033].credits.by_dependent["kid"] == 500  # 17: Credit for Other Dependents
    # College starts at 18 (2034): AOTC 2,500 plus ODC 500.
    assert by_year[2034].credits.by_dependent["kid"] == pytest.approx(2500 + 500)


def test_settlement_converges_through_a_credit_phase_out():
    """A single parent living off a traditional IRA near the CTC phase-out: the withdrawal must cover spending
    plus the tax it causes, including credit lost to the phase-out."""
    result = run(
        members=[member(birth_year=1966, retire=55)],
        dependents=[KID],
        filing_status="head_of_household",
        accounts=[
            {"id": "ira", "owner": "pat", "type": "traditional_ira", "balance": 3_000_000, "asset_strategy": STOCKS}
        ],
        spending=180000,
    )
    year = result.years[0]
    # Grossing up can overshoot by a few dollars; any excess is swept, never left as a deficit.
    assert year.flows.withdrawals["deferred"] == pytest.approx(180000 + year.flows.total_taxes, abs=10.0)
    assert 200000 < year.flows.taxes.agi < 244000  # inside the CTC phase-out range
    assert 0 < year.flows.taxes.credits.child_tax_credit < 2200
    assert 0 <= year.cash < 10  # any gross-up overshoot is carried (this profile has nowhere to sweep it)
    assert not any("converge" in w for w in result.warnings)


def test_settlement_needs_only_a_few_rounds_at_high_marginal_rates():
    """37% bracket plus the 10% early-withdrawal penalty: the secant gross-up keeps settlement short."""
    result = run(
        members=[member(birth_year=1980, retire=40)],
        accounts=[
            {"id": "ira", "owner": "pat", "type": "traditional_ira", "balance": 5_000_000, "asset_strategy": STOCKS}
        ],
        spending=600000,
    )
    year = result.years[0]
    assert year.flows.taxes.additional_taxes > 0
    assert year.flows.withdrawals["deferred"] == pytest.approx(600000 + year.flows.total_taxes, abs=10.0)
    assert 0 <= year.cash < 10


def test_capital_losses_carry_forward_across_years():
    result = run(
        members=[member(birth_year=1955, retire=60)],
        accounts=[
            {
                "id": "brokerage",
                "owner": "pat",
                "type": "brokerage",
                "balance": 100000,
                "cost_basis": 200000,
                "asset_strategy": {"kind": "static_allocation", "stocks": 0.0, "bonds": 0.0, "cash": 1.0},
            }
        ],
        spending=30000,
        preset={
            "factors": {
                "stocks": {"mean": 0, "std_dev": 0},
                "bonds": {"mean": 0, "std_dev": 0},
                "cash": {"mean": 0, "std_dev": 0},
                "inflation": {"mean": 0, "std_dev": 0, "distribution": "normal"},
            }
        },
    )
    # Each year sells 30,000 at half of basis: a 30,000 loss, of which 3,000 is deductible.
    carry = [y.flows.taxes.capital_loss_carryforward for y in result.years]
    assert carry == pytest.approx([27000, 54000, 81000])
    assert all(y.flows.taxes.capital_gains == -3000 for y in result.years)


def test_refundable_credits_are_paid_to_the_household():
    result = run(
        members=[member()],
        dependents=[KID],
        filing_status="head_of_household",
        accounts=[{"id": "checking", "owner": "pat", "type": "checking", "balance": 50000, "interest_rate": 0.0}],
        income=[{"id": "job", "owner": "pat", "type": "salary", "amount": 20000}],
        spending=15000,
        horizon={"start_year": 2026, "end_year": 2026},
    )
    taxes = result.years[0].flows.taxes
    assert taxes.total < 0
    assert moves(result, 2026, "irs", CASH) == pytest.approx(-taxes.total)


def test_head_of_household_without_a_dependent_files_single():
    grown = {"id": "adult", "name": "Adult", "birth_year": 2000, "birth_month": 1}
    result = run(
        members=[member()],
        dependents=[grown],
        filing_status="head_of_household",
        accounts=[{"id": "checking", "owner": "pat", "type": "checking", "balance": 50000}],
        income=[{"id": "job", "owner": "pat", "type": "salary", "amount": 60000}],
        spending=20000,
    )
    assert all(y.flows.taxes.filing_status.value == "single" for y in result.years)
    assert any("filed as single in 2026-2028" in w for w in result.warnings)


def test_marginal_rate_is_reported_each_year():
    result = run(
        members=[member()],
        accounts=[{"id": "checking", "owner": "pat", "type": "checking", "balance": 10000}],
        income=[{"id": "job", "owner": "pat", "type": "salary", "amount": 100000}],
        spending=40000,
    )
    assert result.years[0].flows.taxes.marginal_rate == pytest.approx(0.22)
