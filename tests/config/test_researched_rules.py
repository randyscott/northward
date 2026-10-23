"""Sanity checks on the verified 2026 rule data and the helpers that read it."""

import pytest
from pydantic import TypeAdapter, ValidationError

from northward.config.base import FilingStatus, FractionalRate
from northward.config.rules.contribution_limits import ContributionLimitsDoc
from northward.config.rules.federal_tax import BracketSchedule, FederalTaxDoc
from northward.config.rules.rmd import RmdDoc
from northward.config.rules.social_security import SocialSecurityDoc
from tests.conftest import load_yaml

FEDERAL = FederalTaxDoc.model_validate(load_yaml("rules/federal_tax.yaml"))
RMD = RmdDoc.model_validate(load_yaml("rules/rmd.yaml"))
SS = SocialSecurityDoc.model_validate(load_yaml("rules/social_security.yaml"))
LIMITS = ContributionLimitsDoc.model_validate(load_yaml("rules/contribution_limits.yaml"))
QSS = FilingStatus.QUALIFYING_SURVIVING_SPOUSE


def test_qualifying_surviving_spouse_uses_joint_values_unless_overridden():
    assert FEDERAL.ordinary_income_brackets.schedules.for_status(QSS)[0] == (24800, 0.10)
    assert FEDERAL.standard_deduction.amounts.for_status(QSS) == 32200
    # ...but is an unmarried filer for these provisions
    assert FEDERAL.fica.additional_medicare_threshold.for_status(QSS) == 200000
    assert FEDERAL.social_security_taxability.thresholds.for_status(QSS).base == 25000


def test_married_filing_separately_is_ineligible_where_the_statute_says_so():
    mfs = FilingStatus.MARRIED_FILING_SEPARATELY
    assert FEDERAL.senior_deduction.magi_threshold.for_status(mfs) is None
    assert FEDERAL.credits.education.phase_out.for_status(mfs) is None


@pytest.mark.parametrize(
    ("schedule", "message"),
    [
        ([[10000, 0.1], [5000, 0.2], [float("inf"), 0.3]], "strictly increase"),
        ([[10000, 0.1], [20000, 0.2]], "must be .inf"),
        ([[10000, 0.3], [float("inf"), 0.2]], "must not decrease"),
    ],
)
def test_bracket_schedule_validation(schedule, message):
    with pytest.raises(ValidationError, match=message):
        TypeAdapter(BracketSchedule).validate_python(schedule)


@pytest.mark.parametrize(
    ("birth", "age"),
    [((1949, 6), 70.5), ((1949, 7), 72), ((1955, 1), 73), ((1959, 12), 73), ((1960, 1), 75), ((1983, 9), 75)],
)
def test_rmd_applicable_age(birth, age):
    assert RMD.applicable_age(*birth) == age


def test_rmd_tables():
    assert RMD.uniform_divisor(75) == 24.6
    assert RMD.uniform_divisor(125) == 2.0  # "120 and older"
    assert RMD.single_life_expectancy(50) == 36.2
    assert len(RMD.single_life) == 121 and len(RMD.uniform_lifetime) == 49


def test_rmd_tables_must_be_consecutive():
    data = load_yaml("rules/rmd.yaml")
    del data["uniform_lifetime"][80]
    with pytest.raises(ValidationError, match="consecutive"):
        RmdDoc.model_validate(data)


def test_full_retirement_ages():
    assert SS.full_retirement_age_for(1954) == (66, 0)
    assert SS.full_retirement_age_for(1958) == (66, 8)
    assert SS.full_retirement_age_for(1983) == (67, 0)
    assert SS.survivor_full_retirement_age_for(1960) == (66, 8)  # the survivor table lags the worker table


def test_early_reduction_at_62_matches_ssa():
    months_early = 60  # FRA 67
    r = SS.early_reduction
    reduction = r.first_months * r.first_rate_per_month + (months_early - r.first_months) * r.additional_rate_per_month
    assert reduction == pytest.approx(0.30)
    s = SS.spousal.early_reduction
    spousal = s.first_months * s.first_rate_per_month + (months_early - s.first_months) * s.additional_rate_per_month
    assert SS.spousal.fraction_of_pia * (1 - spousal) == pytest.approx(0.325)


def test_fractional_rates():
    adapter = TypeAdapter(FractionalRate)
    assert adapter.validate_python("5/9%") == pytest.approx(0.0055556, rel=1e-4)
    assert adapter.validate_python(0.08) == 0.08
    with pytest.raises(ValidationError):
        adapter.validate_python("5/9")


def test_contribution_limits():
    assert (LIMITS.elective_deferral.limit, LIMITS.ira.limit, LIMITS.hsa.family) == (24500, 7500, 8750)
    assert LIMITS.dependent_care_fsa.household_limit == 7500
