"""Household document: filing status, adult members, and dependents."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from northward.config.base import JOINT_OWNER, Age, Document, FilingStatus, Identifier, Money, Month, StrictModel, Year


class SocialSecurityRecord(StrictModel):
    """A member's own Social Security record."""

    pia_at_fra: Money
    """Monthly benefit at full retirement age (the Primary Insurance Amount), in today's dollars, from the SSA
    statement."""


class Member(StrictModel):
    """An adult in the household who can own accounts, earn income, and claim Social Security."""

    id: Identifier
    """How other documents refer to this person."""
    name: str
    """Display name."""
    birth_year: Year
    """Year of birth."""
    birth_month: Month
    """1-12. Used for age 59 1/2, Social Security claiming months, and retirement proration."""
    target_retirement_age: Age
    """When salary stops (prorated by month in that year). May be fractional, e.g. 62.5."""
    social_security: SocialSecurityRecord | None = None
    """The member's own Social Security record. Leave out if they have none; spousal and survivor benefits still
    apply."""
    sex: Literal["male", "female"] | None = None
    """Picks the life table when lifespans are sampled. Without it, the average of both tables is used."""


class Dependent(StrictModel):
    """A child or other relative the household supports and may claim for tax purposes."""

    id: Identifier
    """How other documents refer to this person. Members and dependents share one set of ids."""
    name: str
    """Display name."""
    birth_year: Year
    """Year of birth."""
    birth_month: Month
    """1-12."""
    relationship: Literal["child", "other_relative"] = "child"
    """An other relative is a dependent while living with the household, and never gets the Child Tax Credit."""
    lives_with_household_until_age: int | None = Field(default=None, ge=0)
    """The last age at which they live with the household. Without it, the dependency age rules decide."""
    full_time_student_ages: tuple[int, int] | None = None
    """[first, last] ages as a full-time student (inclusive). Extends dependency to under 24 and decides the
    education credit."""
    disabled: bool = False
    """Removes the age limits on dependency, the care credit, and Social Security child benefits."""
    child_of: tuple[Identifier, ...] | None = None
    """Members whose Social Security records can pay child benefits. Default: every member (for a child)."""

    @model_validator(mode="after")
    def _check_student_ages(self) -> Dependent:
        if self.full_time_student_ages is not None:
            first, last = self.full_time_student_ages
            if not 0 <= first <= last:
                raise ValueError("full_time_student_ages must be [first, last] with 0 <= first <= last")
        return self


class HouseholdInfo(StrictModel):
    filing_status: FilingStatus
    """Two members file jointly or separately; one member files single, head of household, or as a qualifying
    surviving spouse. After a death the survivor's status changes automatically."""
    state: str = "none"
    """State of residence: a key in rules/state_tax.yaml (`none` for no state income tax)."""


class HouseholdDoc(Document):
    """Who is in the household: members, dependents, filing status, and state of residence."""

    household: HouseholdInfo
    """Filing status and state of residence."""
    members: tuple[Member, ...] = Field(min_length=1, max_length=2)
    """One or two adults."""
    dependents: tuple[Dependent, ...] = ()
    """Children or other relatives the household supports."""

    @model_validator(mode="after")
    def _check_consistency(self) -> HouseholdDoc:
        ids = [m.id for m in self.members] + [d.id for d in self.dependents]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"member and dependent ids must be unique; duplicated: {', '.join(duplicates)}")
        if JOINT_OWNER in ids:
            raise ValueError(f"'{JOINT_OWNER}' is reserved for jointly owned accounts and can't be used as an id")

        married = {FilingStatus.MARRIED_FILING_JOINTLY, FilingStatus.MARRIED_FILING_SEPARATELY}
        status = self.household.filing_status
        if len(self.members) == 2 and status not in married:
            raise ValueError(f"a two-member household must file jointly or separately, not {status.value}")
        if len(self.members) == 1 and status in married:
            raise ValueError(f"a one-member household can't use filing status {status.value}")

        member_ids = {m.id for m in self.members}
        for dependent in self.dependents:
            unknown = set(dependent.child_of or ()) - member_ids
            if unknown:
                raise ValueError(f"dependent '{dependent.id}' child_of references unknown member(s): {sorted(unknown)}")
        return self

    def member(self, member_id: str) -> Member | None:
        return next((m for m in self.members if m.id == member_id), None)

    def dependent(self, dependent_id: str) -> Dependent | None:
        return next((d for d in self.dependents if d.id == dependent_id), None)
