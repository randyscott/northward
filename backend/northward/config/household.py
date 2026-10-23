"""Household document: filing status, adult members, and dependents."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from northward.config.base import JOINT_OWNER, Age, Document, FilingStatus, Identifier, Money, Month, StrictModel, Year


class SocialSecurityRecord(StrictModel):
    """A member's own Social Security record (PLAN.md D6)."""

    # Monthly Primary Insurance Amount at full retirement age, in today's dollars (as on the SSA statement).
    pia_at_fra: Money


class Member(StrictModel):
    """An adult in the household who can own accounts, earn income, and claim Social Security."""

    id: Identifier
    name: str
    birth_year: Year
    birth_month: Month
    target_retirement_age: Age
    # None: no benefit on the member's own record (spousal and survivor benefits may still apply).
    social_security: SocialSecurityRecord | None = None
    # Used only to pick the life table when mortality is sampled (Phase 6); None uses the average of both tables.
    sex: Literal["male", "female"] | None = None


class Dependent(StrictModel):
    """A child or other relative the household supports and may claim for tax purposes (PLAN.md §4.4)."""

    id: Identifier
    name: str
    birth_year: Year
    birth_month: Month
    relationship: Literal["child", "other_relative"] = "child"
    # Age after which the dependent no longer lives with the household. None: until dependency rules end it.
    lives_with_household_until_age: int | None = Field(default=None, ge=0)
    # Inclusive [first, last] ages as a full-time student; extends dependency to under 24 and drives AOTC/LLC.
    full_time_student_ages: tuple[int, int] | None = None
    disabled: bool = False
    # Members whose Social Security records can pay child benefits. None: every member (for a child).
    child_of: tuple[Identifier, ...] | None = None

    @model_validator(mode="after")
    def _check_student_ages(self) -> Dependent:
        if self.full_time_student_ages is not None:
            first, last = self.full_time_student_ages
            if not 0 <= first <= last:
                raise ValueError("full_time_student_ages must be [first, last] with 0 <= first <= last")
        return self


class HouseholdInfo(StrictModel):
    filing_status: FilingStatus
    state: str = "none"  # state of residence: a key in rules/state_tax.yaml


class HouseholdDoc(Document):
    household: HouseholdInfo
    members: tuple[Member, ...] = Field(min_length=1, max_length=2)
    dependents: tuple[Dependent, ...] = ()

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
