"""Hand-checked 2026 Wisconsin returns (zero inflation, so the 2026 amounts apply at face value)."""

import numpy as np
import pytest

from northward.config.base import FilingStatus
from northward.config.household import Dependent
from northward.config.rules.federal_tax import FederalTaxDoc
from northward.config.rules.state_tax import StateTaxDoc
from northward.lifecycle.dependents import dependent_status
from northward.tax.federal import FederalTax
from northward.tax.indexing import PriceIndex
from northward.tax.inputs import PersonTaxInput, TaxInputs
from tests.conftest import load_yaml

FEDERAL = FederalTaxDoc.model_validate(load_yaml("rules/federal_tax.yaml"))
STATES = StateTaxDoc.model_validate(load_yaml("rules/state_tax.yaml"))
TAX = FederalTax(FEDERAL, PriceIndex(2026, np.zeros(10), 0.0, {"education": 0.0, "healthcare": 0.0}), 0.0, STATES)
MFJ, HOH = FilingStatus.MARRIED_FILING_JOINTLY, FilingStatus.HEAD_OF_HOUSEHOLD


def person(member, wages=0.0, age=45, retirement=0.0):
    return PersonTaxInput(member, age, wages, wages, retirement)


def wisconsin(status=MFJ, people=(), **kw):
    return TAX.compute(TaxInputs(year=2026, filing_status=status, people=tuple(people), state="WI", **kw)).state


def test_working_couple_matches_dor_schedule():
    state = wisconsin(people=[person("a", 100000), person("b", 50000)])
    assert state.income == 150000
    assert state.deduction == pytest.approx(25840 - 0.19778 * (150000 - 29040))
    assert state.exemptions == 1400
    # DOR's 2026 shortcut for MFJ taxable income over $100k: 5.3% x TI - $804.69.
    assert state.tax_before_credits == pytest.approx(0.053 * state.taxable_income - 804.69, abs=0.02)
    assert state.credits == pytest.approx(0.03 * 16000)  # married couple credit, lower earner capped at 16,000


def test_retired_couple_age_67_subtraction_social_security_and_capital_gains():
    people = [person("a", age=68, retirement=80000), person("b", age=68)]
    state = wisconsin(people=people, other_ordinary=80000, social_security=50000, capital_gains=10000)
    # Federal AGI 132,500 (85% of benefits taxable) -> Wisconsin: minus SS 42,500, 30% of gains, and the pooled
    # $48,000 retirement subtraction (both 67+, even though one spouse received all of it).
    assert state.retirement_subtraction == 48000
    assert state.income == pytest.approx(132500 - 42500 - 3000 - 48000)
    assert state.deduction == pytest.approx(25840 - 0.19778 * (39000 - 29040))
    assert state.exemptions == 2 * (700 + 250)
    assert state.tax == pytest.approx(0.035 * (39000 - state.deduction - 1900))
    assert state.credits_forgone


def test_age_67_subtraction_counts_only_the_eligible_spouses_income():
    people = [person("a", age=67, retirement=10000), person("b", age=60, retirement=50000)]
    state = wisconsin(people=people, other_ordinary=60000)
    assert state.retirement_subtraction == 10000


def test_credits_are_kept_when_they_beat_the_subtraction():
    """A working 67-year-old with a small IRA withdrawal: the married couple credit is worth more than the
    subtraction, so the subtraction isn't claimed."""
    people = [person("a", 60000, age=67, retirement=500), person("b", 60000, age=50)]
    state = wisconsin(people=people, other_ordinary=500)
    assert state.retirement_subtraction == 0 and not state.credits_forgone
    assert state.credits == pytest.approx(480)


def test_head_of_household_deduction_floors_at_the_single_schedule():
    kid = dependent_status(Dependent(id="k", name="K", birth_year=2016, birth_month=1), FEDERAL, 2026)
    state = wisconsin(HOH, people=[person("a", 80000)], dependents=(kid,))
    assert state.deduction == pytest.approx(13960 - 0.12 * (80000 - 20120))  # single beats HoH's steeper slope


def test_529_subtraction_carries_forward():
    first = wisconsin(people=[person("a", 90000)], plan_529_contributions={"kid": 8000})
    assert first.income == pytest.approx(90000 - 5280)
    assert first.plan_529_carryforward == {"kid": pytest.approx(2720)}
    second = wisconsin(people=[person("a", 90000)], plan_529_carryforward={"kid": 2720})
    assert second.income == pytest.approx(90000 - 2720) and second.plan_529_carryforward == {}


def test_after_tax_health_premiums_are_subtracted():
    state = wisconsin(
        people=[person("a", age=70, retirement=60000)], other_ordinary=60000, health_premiums_after_tax=6000
    )
    assert state.income == pytest.approx(60000 - 6000 - 24000)  # premiums and the age-67 subtraction


def test_wisconsin_adds_a_third_of_federal_penalties():
    state = wisconsin(people=[person("a", age=40)], other_ordinary=20000, early_distribution_base=20000)
    no_penalty = wisconsin(people=[person("a", age=40)], other_ordinary=20000)
    assert state.tax - no_penalty.tax == pytest.approx(0.33 * 0.10 * 20000)
