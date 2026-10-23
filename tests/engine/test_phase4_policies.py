"""Contribution limits, 529 withdrawals and leftovers, and scheduled events."""

import pytest

from northward.ledger.transaction import CASH
from tests.engine.helpers import STOCKS, member, moves, run
from tests.engine.test_distributions import ZERO_GROWTH

CHECKING = {"id": "checking", "owner": "pat", "type": "checking", "balance": 500000, "interest_rate": 0.0}


def one_person(salary, contributions=(), accounts=(), **kw):
    return run(
        members=[member(birth_year=1971)],  # 55 in 2026: IRA catch-up applies
        accounts=[CHECKING, *accounts],
        income=[{"id": "job", "owner": "pat", "type": "salary", "amount": salary, **kw.pop("salary_extra", {})}],
        levers={"contributions": list(contributions)},
        horizon={"start_year": 2026, "end_year": 2026},
        **kw,
    )


ROTH = {"id": "roth", "owner": "pat", "type": "roth_ira", "balance": 0, "asset_strategy": STOCKS}
IRA = {"id": "ira", "owner": "pat", "type": "traditional_ira", "balance": 0, "asset_strategy": STOCKS}
K401 = {"id": "k401", "owner": "pat", "type": "traditional_401k", "balance": 0, "asset_strategy": STOCKS}


def test_ira_contributions_are_capped_at_the_limit_plus_catch_up():
    result = one_person(100000, [{"account": "roth", "amount": 20000}], [ROTH])
    assert moves(result, 2026, CASH, "roth") == 7500 + 1100
    assert any("IRA contributions to roth were reduced" in w for w in result.warnings)


def test_roth_ira_phase_out():
    # MAGI 160,500 is halfway through the single 153,000-168,000 range.
    result = one_person(160500, [{"account": "roth", "amount": 8600}], [ROTH])
    assert moves(result, 2026, CASH, "roth") == pytest.approx(8600 * 0.5)


def test_traditional_ira_deduction_phases_out_for_covered_workers():
    covered = {"elections": {"retirement_deferrals": [{"account": "k401", "amount": 1000}]}}
    # MAGI after the 1,000 deferral: 86,000, halfway through the covered single range (81,000-91,000).
    result = one_person(87000, [{"account": "ira", "amount": 8600}], [IRA, K401], salary_extra=covered)
    assert result.years[0].flows.taxes.agi == pytest.approx(86000 - 8600 * 0.5)
    uncovered = one_person(86000, [{"account": "ira", "amount": 8600}], [IRA])
    assert uncovered.years[0].flows.taxes.agi == pytest.approx(86000 - 8600)


def test_employer_additions_are_capped_by_415c():
    rich_match = {
        "elections": {
            "retirement_deferrals": [{"account": "k401", "max": True}],
            "employer_match": {"account": "k401", "tiers": [{"match": 3.0, "up_to": 0.5}]},
        }
    }
    result = one_person(300000, accounts=[K401], salary_extra=rich_match)
    assert moves(result, 2026, "employer", "k401") == pytest.approx(72000 - 24500)


def test_family_hsa_limit_is_shared_between_spouses():
    def salary(who):
        return {
            "id": f"{who}_job",
            "owner": who,
            "type": "salary",
            "amount": 100000,
            "elections": {
                "hsa": {"account": f"{who}_hsa", "coverage": "family" if who == "a" else "self_only", "max": True}
            },
        }

    result = run(
        members=[member("a", 1980), member("b", 1966)],  # b is 60: HSA catch-up
        accounts=[
            {"id": "checking", "owner": "joint", "type": "checking", "balance": 0},
            *({"id": f"{w}_hsa", "owner": w, "type": "hsa", "balance": 0, "asset_strategy": STOCKS} for w in "ab"),
        ],
        income=[salary("a"), salary("b")],
        horizon={"start_year": 2026, "end_year": 2026},
    )
    assert moves(result, 2026, CASH, "a_hsa") == pytest.approx(8750 / 2)
    assert moves(result, 2026, CASH, "b_hsa") == pytest.approx(8750 / 2 + 1000)


def college_family(leftover="keep", **kw):
    kid = {"id": "kid", "name": "Kid", "birth_year": 2008, "birth_month": 6, "full_time_student_ages": [18, 21]}
    younger = {"id": "sib", "name": "Sib", "birth_year": 2012, "birth_month": 6, "full_time_student_ages": [18, 21]}
    return run(
        members=[member("a", 1974), member("b", 1977)],
        dependents=[kid, younger],
        accounts=[
            {"id": "checking", "owner": "joint", "type": "checking", "balance": 1_000_000, "interest_rate": 0.0},
            {
                "id": "kid_529",
                "owner": "a",
                "type": "plan_529",
                "beneficiary": "kid",
                "balance": 150000,
                "cost_basis": 100000,
                "opened_year": 2009,
                "asset_strategy": {"kind": "static_allocation", "stocks": 0, "bonds": 0, "cash": 1},
            },
        ],
        income=[{"id": "job", "owner": "a", "type": "salary", "amount": 120000}],
        spending={
            "base": {"amount": 0},
            "categories": [
                {
                    "id": f"{k}_college",
                    "amount": 30000,
                    "tags": ["qualified_education"],
                    "beneficiary": k,
                    "start": {"dependent": k, "age": 18},
                    "end": {"dependent": k, "age": 21},
                }
                for k in ("kid", "sib")
            ],
        },
        preset=ZERO_GROWTH,
        levers={"plan_529_leftover": leftover},
        horizon={"start_year": 2026, "end_year": 2034},
        **kw,
    )


def test_529_pays_college_but_leaves_4000_for_the_aotc():
    result = college_family()
    first = result.years[0].flows  # kid is 18 in 2026
    assert first.plan_529_qualified["kid"] == pytest.approx(30000 - 4000)
    assert (
        first.taxes.credits.american_opportunity + first.taxes.credits.american_opportunity_refundable
        == pytest.approx(2500)
    )
    assert first.taxes.agi == pytest.approx(120000)  # qualified withdrawals are tax-free


def test_leftover_529_can_change_beneficiary_or_be_withdrawn():
    changed = college_family("change_beneficiary")
    by_year = {y.year: y.flows.plan_529_qualified for y in changed.years}
    assert by_year[2030].get("sib", 0) > 0  # kid finished in 2029; the remainder pays for sib
    withdrawn = college_family("withdraw")
    year = next(y for y in withdrawn.years if y.year == 2030)
    assert year.flows.plan_529_other > 0 and year.flows.taxes.additional_taxes > 0
    assert year.balances["kid_529"] == 0


def test_leftover_529_rolls_to_the_beneficiarys_roth_up_to_the_lifetime_cap():
    result = college_family("roth_rollover")
    rolled = sum(moves(result, y.year, "kid_529", "roth_ira:kid") for y in result.years)
    assert rolled == pytest.approx(35000)


def test_scheduled_events():
    result = run(
        members=[member("a", 1965), member("b", 1966)],
        accounts=[
            {"id": "checking", "owner": "joint", "type": "checking", "balance": 10000, "interest_rate": 0.0},
            {
                "id": "brokerage",
                "owner": "joint",
                "type": "brokerage",
                "balance": 0,
                "cost_basis": 0,
                "asset_strategy": STOCKS,
            },
        ],
        liabilities=[
            {"id": "mortgage", "kind": "amortizing", "balance": 200000, "annual_rate": 0.05, "monthly_payment": 1500}
        ],
        events=[
            {
                "id": "bonus",
                "kind": "windfall",
                "when": {"year": 2026},
                "amount": 20000,
                "tax_character": "ordinary",
                "owner": "a",
            },
            {
                "id": "house",
                "kind": "home_sale",
                "when": {"year": 2027},
                "price": 900000,
                "cost_basis": 300000,
                "pay_off": "mortgage",
            },
            {
                "id": "gift",
                "kind": "inheritance",
                "when": {"year": 2028},
                "amount": 50000,
                "beneficiary": "b",
                "asset": "brokerage",
                "account": "brokerage",
            },
        ],
        preset=ZERO_GROWTH,
        horizon={"start_year": 2026, "end_year": 2028},
    )
    y2026, y2027, y2028 = (y.flows for y in result.years)
    assert y2026.taxes.other_ordinary == pytest.approx(20000)
    # 900,000 less 6% selling costs = 846,000; gain 546,000 less the 500,000 joint exclusion.
    assert y2027.taxes.capital_gains == pytest.approx(46000)
    assert result.years[1].liabilities["mortgage"] == 0
    assert moves(result, 2028, "event:gift", "brokerage") == 50000
    assert y2028.taxes.agi == pytest.approx(0)  # inheritances aren't income
