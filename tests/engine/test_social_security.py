"""Social Security: SSA claiming factors, spousal and child benefits, the family maximum, and the earnings test."""

import pytest

from northward.config.rules.social_security import SocialSecurityDoc
from northward.income.social_security import family_maximum, own_benefit_factor, spousal_factor
from tests.conftest import load_yaml
from tests.engine.helpers import member, run

SS = SocialSecurityDoc.model_validate(load_yaml("rules/social_security.yaml"))
FRA_67 = 67 * 12


@pytest.mark.parametrize(
    ("claim_age", "benefit"),
    [
        (62, 700.0),
        (63, 750.0),
        (64, 800.0),
        (65, 866.67),
        (66, 933.33),
        (67, 1000.0),
        (68, 1080.0),
        (69, 1160.0),
        (70, 1240.0),
        (71, 1240.0),
    ],
)
def test_own_benefit_matches_ssa_for_fra_67(claim_age, benefit):
    """SSA's published percentages for a $1,000 PIA with full retirement age 67."""
    assert 1000 * own_benefit_factor(SS, claim_age * 12, FRA_67) == pytest.approx(benefit, abs=0.01)


@pytest.mark.parametrize(
    ("claim_age", "share"), [(62, 0.325), (63, 0.35), (64, 0.375), (65, 0.4167), (66, 0.4583), (67, 0.5), (70, 0.5)]
)
def test_spousal_benefit_matches_ssa(claim_age, share):
    assert 0.5 * spousal_factor(SS, claim_age * 12, FRA_67) == pytest.approx(share, abs=1e-4)


@pytest.mark.parametrize(("pia", "maximum"), [(1000, 1500.0), (2000, 3435.5), (3000, 5287.5), (4000, 6999.3)])
def test_family_maximum_formula_with_2026_bend_points(pia, maximum):
    assert family_maximum(SS, pia) == pytest.approx(maximum)


def household(**kw):
    worker = {**member("w", 1964, 1, 63), "social_security": {"pia_at_fra": 2000}}
    spouse = member("s", 1970, 1, 70)
    args = dict(
        members=[worker, spouse],
        accounts=[{"id": "checking", "owner": "joint", "type": "checking", "balance": 1_000_000, "interest_rate": 0.0}],
        levers={"ss_claim_ages": {"w": 62}},
        spending=0,
        horizon={"start_year": 2026, "end_year": 2032},
    )
    args.update(kw)
    return run(**args)


def test_family_maximum_prorates_child_in_care_and_child_benefits():
    kids = [
        {"id": "k1", "name": "K1", "birth_year": 2018, "birth_month": 6},
        {"id": "k2", "name": "K2", "birth_year": 2016, "birth_month": 6},
    ]
    year = household(dependents=kids).years[0]
    ss = year.flows
    # Worker claims at 62: 70% of PIA. Auxiliaries requested: child-in-care spouse 1,000 + two children at 1,000,
    # but only 3,435.50 - 2,000 = 1,435.50 fits under the family maximum, so each is prorated to 478.50.
    assert ss.social_security == pytest.approx(12 * (1400 + 1000 * 1435.5 / 3000), abs=0.01)
    assert ss.child_benefits == pytest.approx(12 * 2 * 1000 * 1435.5 / 3000, abs=0.01)


def test_spousal_benefit_starts_when_both_have_filed():
    spouse = {**member("s", 1964, 1, 70), "social_security": {"pia_at_fra": 400}}
    result = household(
        members=[{**member("w", 1964, 1, 63), "social_security": {"pia_at_fra": 2000}}, spouse],
        levers={"ss_claim_ages": {"w": 67, "s": 62}},
    )
    by_year = {y.year: y.flows.social_security for y in result.years}
    assert by_year[2026] == pytest.approx(12 * 400 * 0.70)  # spouse's own reduced benefit only
    # From 2031 the worker files at 67: spousal excess 1,000 - 400 = 600, reduced for starting at 67 -> none.
    assert by_year[2031] == pytest.approx(12 * (2000 + 400 * 0.70 + 600), abs=0.01)


def test_earnings_test_withholds_and_credits_months_back_at_fra():
    salary = [{"id": "job", "owner": "w", "type": "salary", "amount": 50000}]
    result = household(income=salary)
    by_year = {y.year: y.flows.social_security for y in result.years}
    withheld = 0.5 * (50000 - 24480)
    assert by_year[2026] == pytest.approx(12 * 1400 - withheld)
    assert by_year[2027] == pytest.approx(12 * 1400)  # retired at 63: no more withholding
    # About 9 months were withheld; from FRA (2031) the benefit is recomputed as if claimed 9 months later.
    months_early = 60 - round(withheld / 1400)
    factor = 1 - (36 * 5 / 900 + (months_early - 36) * 5 / 1200)
    assert by_year[2031] == pytest.approx(12 * 2000 * factor)
