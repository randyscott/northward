"""Each dependent's tax status for a year (PLAN.md §4.4), derived from their age at year end."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from northward.config.household import Dependent
from northward.config.rules.federal_tax import FederalTaxDoc

EducationCredit = Literal["american_opportunity", "lifetime_learning"]


@dataclass(frozen=True)
class DependentStatus:
    id: str
    age: int
    is_dependent: bool  # claimable this year (qualifying child, or other relative living with the household)
    ctc: bool  # Child Tax Credit
    other_dependent: bool  # Credit for Other Dependents
    care: bool  # qualifying person for the Child and Dependent Care Credit / FSA
    student: bool  # full-time student this year
    education_credit: EducationCredit | None  # which education credit their qualified expenses can use


def dependent_status(dependent: Dependent, rules: FederalTaxDoc, year: int) -> DependentStatus:
    tests = rules.dependent_age_tests
    age = year - dependent.birth_year
    lives_with = dependent.lives_with_household_until_age is None or age <= dependent.lives_with_household_until_age
    ages = dependent.full_time_student_ages
    student = ages is not None and ages[0] <= age <= ages[1]
    if dependent.relationship == "child":
        is_dependent = lives_with and (
            dependent.disabled or age < tests.qualifying_child_under_age or (student and age < tests.student_under_age)
        )
    else:
        is_dependent = lives_with  # qualifying relative; the gross-income and support tests aren't modeled
    ctc = is_dependent and dependent.relationship == "child" and age < tests.ctc_under_age
    education: EducationCredit | None = None
    if is_dependent:
        max_years = rules.credits.education.american_opportunity.max_years
        first_years = student and ages is not None and age - ages[0] < max_years
        education = "american_opportunity" if first_years else "lifetime_learning"
    return DependentStatus(
        id=dependent.id,
        age=age,
        is_dependent=is_dependent,
        ctc=ctc,
        other_dependent=is_dependent and not ctc,
        care=is_dependent and (dependent.disabled or age < tests.care_under_age),
        student=student,
        education_credit=education,
    )
