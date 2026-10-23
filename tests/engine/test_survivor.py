"""Deaths and survivors: filing status, Social Security survivor benefits, accounts, spending, and mortality."""

import numpy as np
import pytest

from northward.config.loader import load_rules
from northward.config.source import FileSource
from tests.conftest import DATA_DIR
from tests.engine.helpers import STOCKS, member, run
from tests.engine.test_distributions import ZERO_GROWTH

WORKER = {**member("w", 1964, 1, 62), "social_security": {"pia_at_fra": 2000}}
SPOUSE = {**member("s", 1980, 1, 67), "social_security": {"pia_at_fra": 800}}
CHILD = {"id": "kid", "name": "Kid", "birth_year": 2018, "birth_month": 6}


def widowed(**kw):
    args = dict(
        members=[WORKER, SPOUSE],
        dependents=[CHILD],
        accounts=[
            {"id": "w_ira", "owner": "w", "type": "traditional_ira", "balance": 300000, "asset_strategy": STOCKS},
            {
                "id": "brokerage",
                "owner": "joint",
                "type": "brokerage",
                "balance": 400000,
                "cost_basis": 100000,
                "asset_strategy": STOCKS,
            },
            {"id": "checking", "owner": "joint", "type": "checking", "balance": 2_000_000, "interest_rate": 0.0},
        ],
        spending=40000,
        levers={"ss_claim_ages": {"w": 62, "s": 67}, "mortality": {"kind": "fixed", "death_ages": {"w": 65.5}}},
        preset=ZERO_GROWTH,
        horizon={"start_year": 2026, "end_year": 2042},
    )
    args.update(kw)
    return run(**args)


def test_filing_status_after_a_death_with_a_minor_child():
    result = widowed()
    status = {y.year: y.flows.taxes.filing_status.value for y in result.years}
    assert [status[y] for y in (2026, 2029)] == ["married_filing_jointly"] * 2  # year of death is joint
    assert [status[y] for y in (2030, 2031)] == ["qualifying_surviving_spouse"] * 2
    assert [status[y] for y in (2032, 2036)] == ["head_of_household"] * 2  # child is 18 in 2036
    assert status[2037] == "single"
    assert not any("filed as single" in w for w in result.warnings)  # expected transitions, not fallbacks


def test_survivor_social_security():
    result = widowed()
    ss = {y.year: (y.flows.social_security, y.flows.child_benefits) for y in result.years}
    # 2030: the spouse (50) gets the mother's benefit (75% of PIA, child under 16); the child gets 75% of PIA.
    assert ss[2030] == pytest.approx((12 * 1500, 12 * 1500))
    # 2034: the child is 16, so the mother's benefit stops; the child's continues until 18.
    assert ss[2034] == pytest.approx((0, 12 * 1500))
    assert ss[2036] == pytest.approx((0, 0))
    # 2040: the widow turns 60. The worker claimed at 62 (70% = 1,400), so the widow's limit applies:
    # max(1,400, 82.5% x 2,000) = 1,650, reduced to 71.5% for starting at 60.
    assert ss[2040][0] == pytest.approx(12 * 1650 * 0.715)


def test_accounts_pass_to_the_survivor_with_a_basis_step_up():
    result = widowed()
    by_year = {y.year: y for y in result.years}
    assert "w died in 2029; s inherited their accounts in 2030" in result.warnings
    # The spouse is 50 in 2030 and treats the IRA as their own: no RMDs until their own applicable age.
    assert all(by_year[y].flows.rmds == 0 for y in range(2030, 2043))
    assert by_year[2030].flows.spending["base"] == pytest.approx(40000 * 0.75)


def basis_after_death(**kw):
    """Joint brokerage (400k, basis 100k) that funds 30,000 of survivor spending in 2030."""
    return widowed(
        members=[member("w", 1964, 1, 62), member("s", 1980, 1, 67)],
        dependents=[],
        accounts=[
            {
                "id": "brokerage",
                "owner": "joint",
                "type": "brokerage",
                "balance": 400000,
                "cost_basis": 100000,
                "asset_strategy": STOCKS,
            },
        ],
        levers={"mortality": {"kind": "fixed", "death_ages": {"w": 65.5}}},
        horizon={"start_year": 2029, "end_year": 2030},
        **kw,
    )


def test_joint_brokerage_basis_steps_up_by_half_outside_community_property_states():
    result = basis_after_death()
    before, after = (y.flows for y in result.years)
    assert before.realized_gains == pytest.approx(40000 * 0.75)  # basis 25% of value
    # After the death: basis = half the old basis + half the value = 250,000 of the remaining ~360,000.
    remaining = 400000 - 40000
    basis = (100000 * (remaining / 400000) + remaining) / 2
    assert after.realized_gains == pytest.approx(30000 * (1 - basis / remaining))


def test_everyone_dying_ends_the_simulation():
    result = widowed(levers={"mortality": {"kind": "fixed", "death_ages": {"w": 65.5, "s": 55.5}}})
    assert result.years[-1].year == 2035


def test_life_table_sampling_matches_published_life_expectancy():
    mortality = load_rules(FileSource(DATA_DIR)).mortality
    assert mortality.life_expectancy("male", 65) == pytest.approx(18.12, abs=0.01)
    assert mortality.life_expectancy("female", 65) == pytest.approx(20.66, abs=0.01)
    rng = np.random.default_rng(7)
    ages = [mortality.sample_death_age("female", 65, rng) for _ in range(20000)]
    assert np.mean(ages) == pytest.approx(65 + 20.66, abs=0.2)
    assert max(ages) <= 120
