"""Hand-checked 2026 federal returns (zero inflation, so the rules apply at face value)."""

import numpy as np
import pytest

from northward.config.base import FilingStatus
from northward.config.household import Dependent
from northward.config.rules.federal_tax import FederalTaxDoc
from northward.lifecycle.dependents import dependent_status
from northward.tax.credits import care_credit_rate
from northward.tax.federal import FederalTax
from northward.tax.indexing import PriceIndex
from northward.tax.inputs import PersonTaxInput, TaxInputs
from tests.conftest import load_yaml

RULES = FederalTaxDoc.model_validate(load_yaml("rules/federal_tax.yaml"))
TAX = FederalTax(RULES, PriceIndex(2026, np.zeros(10), 0.0, {"education": 0.0, "healthcare": 0.0}), 0.0)
MFJ, SINGLE, MFS, HOH = (
    FilingStatus.MARRIED_FILING_JOINTLY,
    FilingStatus.SINGLE,
    FilingStatus.MARRIED_FILING_SEPARATELY,
    FilingStatus.HEAD_OF_HOUSEHOLD,
)


def person(wages=0.0, age=45, member="a"):
    return PersonTaxInput(member, age, wages, wages)


def kid(id, age, year=2026, **kw):
    dependent = Dependent(id=id, name=id, birth_year=year - age, birth_month=6, **kw)
    return dependent_status(dependent, RULES, year)


ONE_EARNER = (person(),)


def tax(status=MFJ, people=ONE_EARNER, year=2026, marginal=False, **kw):
    inputs = TaxInputs(year=year, filing_status=status, people=tuple(people), **kw)
    result = TAX.compute(inputs)
    return TAX.with_marginal_rate(inputs, result) if marginal else result


def test_capital_gains_straddle_the_zero_and_fifteen_percent_brackets():
    # Ordinary taxable income 80,000 (112,200 - 32,200); 40,000 of gains fill 0% to 98,900, the rest at 15%.
    r = tax(people=[person(112200)], capital_gains=40000)
    assert r.ordinary_tax == pytest.approx(2480 + (80000 - 24800) * 0.12)
    assert r.capital_gains_tax == pytest.approx((120000 - 98900) * 0.15)


def test_net_investment_income_tax_and_additional_medicare():
    r = tax(SINGLE, people=[person(220000)], interest=10000, qualified_dividends=20000)
    assert r.agi == 250000
    assert r.net_investment_income_tax == pytest.approx(0.038 * 30000)  # NII (30k) < MAGI excess (50k)
    assert r.medicare_tax == pytest.approx(0.0145 * 220000 + 0.009 * 20000)
    small = tax(SINGLE, people=[person(195000)], interest=10000)
    assert small.net_investment_income_tax == pytest.approx(0.038 * 5000)  # MAGI excess (5k) < NII


@pytest.mark.parametrize(
    ("benefits", "other", "taxable"),
    [
        (20000, 10000, 0.0),  # provisional 20,000 < 32,000
        (30000, 20000, 1500.0),  # provisional 35,000: half the excess over 32,000
        (40000, 60000, 34000.0),  # provisional 80,000: capped at 85% of benefits
    ],
)
def test_social_security_taxability(benefits, other, taxable):
    r = tax(
        people=[person(age=67, member="a"), person(age=67, member="b")], social_security=benefits, other_ordinary=other
    )
    assert r.taxable_social_security == pytest.approx(taxable)


def test_retired_couple_with_85_percent_taxable_benefits_and_senior_deduction():
    r = tax(
        people=[person(age=67, member="a"), person(age=67, member="b")], social_security=40000, other_ordinary=60000
    )
    assert r.agi == pytest.approx(94000)
    assert r.standard_deduction == pytest.approx(32200 + 2 * 1650)
    assert r.senior_deduction == pytest.approx(2 * 6000)  # MAGI under 150,000
    assert r.taxable_income == pytest.approx(94000 - 35500 - 12000)
    assert r.income_tax == pytest.approx(2480 + (46500 - 24800) * 0.12)


def test_senior_deduction_phases_out_per_person_and_raises_the_marginal_rate():
    seniors = [person(age=66, member="a"), person(age=66, member="b")]
    r = tax(people=seniors, other_ordinary=170000, marginal=True)
    assert r.senior_deduction == pytest.approx(2 * (6000 - 0.06 * 20000))
    # In the 22% bracket, each extra dollar also removes 2 x 6 cents of deduction.
    assert r.marginal_rate == pytest.approx(0.22 * 1.12)
    assert tax(people=seniors, other_ordinary=250000).senior_deduction == 0
    assert tax(MFS, people=seniors[:1], other_ordinary=50000).senior_deduction == 0
    assert tax(people=seniors, other_ordinary=50000, year=2029).senior_deduction == 0


def test_child_tax_credit_phase_out_counts_each_thousand_or_fraction():
    kids = (kid("k1", 8), kid("k2", 12))
    assert tax(people=[person(420000)], dependents=kids).credits.child_tax_credit == pytest.approx(4400 - 20 * 50)
    assert tax(people=[person(400500)], dependents=kids).credits.child_tax_credit == pytest.approx(4400 - 50)
    with_teen = tax(people=[person(100000)], dependents=(*kids, kid("teen", 17)))
    assert with_teen.credits.child_tax_credit == pytest.approx(2 * 2200 + 500)  # ODC for the 17-year-old
    assert with_teen.credits.by_dependent == {"k1": 2200, "k2": 2200, "teen": 500}


def test_refundable_additional_child_tax_credit():
    # HoH, 20,000 of wages: no income tax after the 24,150 deduction, so the CTC is refundable up to 1,700.
    r = tax(HOH, people=[person(20000)], dependents=(kid("k", 6),))
    assert r.income_tax == 0 and r.credits.child_tax_credit == 0
    assert r.credits.additional_child_tax_credit == pytest.approx(1700)
    assert r.total == pytest.approx(20000 * 0.0765 - 1700)  # a net refund of FICA


def test_head_of_household_return_with_care_and_child_credits():
    r = tax(HOH, people=[person(80000, age=40)], dependents=(kid("k", 10),), care_expenses=5000)
    assert r.taxable_income == pytest.approx(80000 - 24150)
    assert r.income_tax_before_credits == pytest.approx(1770 + (55850 - 17700) * 0.12)
    # Care credit: 35% floor, minus 3 points for AGI 5,000 over 75,000 (each 2,000 or fraction), on the 3,000 cap.
    assert r.credits.dependent_care == pytest.approx(3000 * 0.32)
    assert r.credits.child_tax_credit == pytest.approx(2200)
    assert r.income_tax == pytest.approx(6348 - 960 - 2200)


@pytest.mark.parametrize(
    ("status", "agi", "rate"),
    [
        (SINGLE, 15000, 0.50),
        (SINGLE, 43000, 0.36),
        (SINGLE, 43001, 0.35),
        (SINGLE, 103001, 0.20),
        (MFJ, 200000, 0.22),
        (MFJ, 206001, 0.20),
    ],
)
def test_care_credit_rate_schedule(status, agi, rate):
    assert care_credit_rate(RULES.credits, status, agi) == pytest.approx(rate)


def test_care_credit_is_reduced_by_fsa_benefits_and_unavailable_to_mfs():
    kids = (kid("a", 5), kid("b", 8))
    couple = [person(90000, member="a"), person(60000, member="b")]
    r = tax(people=couple, dependents=kids, care_expenses=5000, dependent_care_exclusion=5000)
    assert r.credits.dependent_care == pytest.approx((6000 - 5000) * 0.35)
    assert care_credit_rate(RULES.credits, MFS, 50000) is None
    one_earner = tax(people=[person(150000, member="a"), person(0, member="b")], dependents=kids, care_expenses=6000)
    assert one_earner.credits.dependent_care == 0  # limited to the lower earner's earned income


def test_american_opportunity_credit_with_529_coordination():
    freshman = kid("s", 19, full_time_student_ages=(18, 21))  # 2nd student year: AOTC
    people = [person(150000)]
    # 10,000 of tuition, 7,000 paid from a 529: only 3,000 counts.
    r = tax(people=people, dependents=(freshman,), education_expenses={"s": 3000})
    assert r.credits.american_opportunity + r.credits.american_opportunity_refundable == pytest.approx(2000 + 250)
    assert r.credits.american_opportunity_refundable == pytest.approx(0.4 * 2250)
    # Leaving 4,000 out of pocket earns the full credit.
    full = tax(people=people, dependents=(freshman,), education_expenses={"s": 4000})
    assert full.credits.by_dependent["s"] == pytest.approx(2500 + 500)  # AOTC + ODC
    halfway = tax(people=[person(170000)], dependents=(freshman,), education_expenses={"s": 4000})
    assert halfway.credits.american_opportunity_refundable == pytest.approx(0.4 * 1250)  # half phased out


def test_lifetime_learning_credit_after_the_aotc_years():
    senior = kid("s", 22, full_time_student_ages=(18, 23))  # 5th student year
    r = tax(people=[person(100000)], dependents=(senior,), education_expenses={"s": 12000})
    assert r.credits.lifetime_learning == pytest.approx(2000)
    assert r.credits.american_opportunity == 0
    assert (
        tax(
            MFS, people=[person(100000)], dependents=(senior,), education_expenses={"s": 12000}
        ).credits.lifetime_learning
        == 0
    )


def test_capital_losses_offset_3000_and_carry_forward():
    r = tax(SINGLE, people=[person(100000)], capital_gains=-10000)
    assert (r.capital_gains, r.capital_loss_carryforward, r.agi) == (-3000, 7000, 97000)
    later = tax(SINGLE, people=[person(100000)], capital_gains=5000, capital_loss_carryforward=7000)
    assert (later.capital_gains, later.capital_loss_carryforward) == (-2000, 0)
    assert tax(MFS, people=[person(100000)], capital_gains=-10000).capital_gains == -1500


def test_nonrefundable_credits_never_make_income_tax_negative():
    r = tax(SINGLE, people=[person(30000)], dependents=(kid("a", 17), kid("b", 18), kid("c", 18)))
    assert r.income_tax == pytest.approx(0)
    assert r.credits.child_tax_credit == pytest.approx(r.income_tax_before_credits)


@pytest.mark.parametrize(
    ("age", "kw", "dependent", "ctc", "care", "education"),
    [
        (10, {}, True, True, True, "lifetime_learning"),
        (16, {}, True, True, False, "lifetime_learning"),
        (18, {}, True, False, False, "lifetime_learning"),
        (20, {}, False, False, False, None),  # not a student, too old for a qualifying child
        (20, {"full_time_student_ages": (18, 21)}, True, False, False, "american_opportunity"),
        (23, {"full_time_student_ages": (18, 23)}, True, False, False, "lifetime_learning"),
        (23, {"full_time_student_ages": (18, 23), "lives_with_household_until_age": 22}, False, False, False, None),
        (30, {"disabled": True}, True, False, True, "lifetime_learning"),
    ],
)
def test_dependent_status(age, kw, dependent, ctc, care, education):
    status = kid("k", age, **kw)
    assert (status.is_dependent, status.ctc, status.care, status.education_credit) == (dependent, ctc, care, education)
