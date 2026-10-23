"""State income tax: none, a hand-checked flat state, the generic features, relocation, and marital property."""

import pytest

from tests.engine.helpers import STOCKS, member, run
from tests.engine.test_distributions import ZERO_GROWTH

FLAT = {
    "name": "Flatland",
    "tax": {
        "kind": "flat",
        "rate": 0.05,
        "indexed": False,
        "standard_deduction": {
            "married_filing_jointly": 10000,
            "single": 5000,
            "married_filing_separately": 5000,
            "head_of_household": 7500,
        },
        "personal_exemptions": {"per_person": 1000, "per_dependent": 500},
    },
}


def worker(**kw):
    args = dict(
        members=[member()],
        accounts=[{"id": "checking", "owner": "pat", "type": "checking", "balance": 100000, "interest_rate": 0.0}],
        income=[{"id": "job", "owner": "pat", "type": "salary", "amount": 80000}],
        spending=30000,
        preset=ZERO_GROWTH,
        states={"FL": FLAT},
        horizon={"start_year": 2026, "end_year": 2026},
    )
    args.update(kw)
    return run(**args)


def test_no_state_tax():
    assert worker().years[0].flows.taxes.state.tax == 0


def test_flat_state_matches_a_hand_calculation():
    state = worker(state="FL").years[0].flows.taxes.state
    assert state.income == 80000
    assert state.taxable_income == 80000 - 5000 - 1000
    assert state.tax == pytest.approx(0.05 * 74000)


def test_state_tax_is_part_of_the_bill_and_the_marginal_rate():
    none, flat = worker().years[0].flows.taxes, worker(state="FL").years[0].flows.taxes
    assert flat.total - none.total == pytest.approx(flat.state.tax)
    assert flat.marginal_rate == pytest.approx(none.marginal_rate + 0.05)


def test_generic_subtractions_and_sliding_deduction():
    rules = {
        "name": "Testland",
        "tax": {
            "kind": "progressive",
            "indexed": False,
            "brackets": {
                s: [[20000, 0.03], [float("inf"), 0.06]]
                for s in ("married_filing_jointly", "single", "married_filing_separately", "head_of_household")
            },
            "exempt_social_security": True,
            "capital_gains_exclusion": 0.30,
            "retirement_income_exclusions": [{"amount": 10000, "min_age": 65}],
            "sliding_standard_deduction": {
                "maximum": {
                    s: 12000
                    for s in ("married_filing_jointly", "single", "married_filing_separately", "head_of_household")
                },
                "phase_out_start": {
                    s: 20000
                    for s in ("married_filing_jointly", "single", "married_filing_separately", "head_of_household")
                },
                "phase_out_rate": {
                    s: 0.1
                    for s in ("married_filing_jointly", "single", "married_filing_separately", "head_of_household")
                },
            },
        },
    }
    result = run(
        members=[{**member(birth_year=1955, retire=60), "social_security": {"pia_at_fra": 2000}}],
        accounts=[
            {"id": "ira", "owner": "pat", "type": "traditional_ira", "balance": 1_000_000, "asset_strategy": STOCKS},
        ],
        events=[
            {
                "id": "gain",
                "kind": "windfall",
                "when": {"year": 2026},
                "amount": 20000,
                "tax_character": "long_term_gain",
            }
        ],
        spending=0,
        preset=ZERO_GROWTH,
        states={"TL": rules},
        state="TL",
        levers={"ss_claim_ages": {"pat": 67}},
        horizon={"start_year": 2026, "end_year": 2026},
    )
    taxes = result.years[0].flows.taxes
    rmd = result.years[0].flows.rmds
    expected_income = taxes.agi - taxes.taxable_social_security - 0.30 * 20000 - min(rmd, 10000)
    assert taxes.state.income == pytest.approx(expected_income)
    assert taxes.state.deduction == pytest.approx(12000 - 0.1 * max(0, expected_income - 20000))


def test_relocation_changes_the_state_from_that_year():
    result = worker(
        state="FL",
        levers={"relocations": [{"when": {"year": 2027}, "state": "none"}]},
        horizon={"start_year": 2026, "end_year": 2027},
    )
    assert [y.residence for y in result.years] == ["FL", "none"]
    assert result.years[0].flows.taxes.state.tax > 0 and result.years[1].flows.taxes.state.tax == 0


def test_community_property_steps_up_both_halves():
    from tests.engine.test_survivor import basis_after_death

    result = basis_after_death(states={"CP": {**FLAT, "community_property": True}}, state="CP")
    after = result.years[1].flows
    assert after.realized_gains == pytest.approx(0, abs=0.01)  # full step-up: basis equals value
