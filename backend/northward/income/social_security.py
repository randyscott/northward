"""Social Security benefits (docs/decisions.md D6): own, spousal, child, child-in-care, and survivor benefits.

Benefits are worked out month by month (claim dates, deaths, children aging out, survivors reaching 60) in
start-year dollars from each member's PIA, then inflated by CPI (the COLA) for the year.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from northward.config.household import Dependent, Member
from northward.config.rules.social_security import ReductionSchedule, SocialSecurityDoc
from northward.engine.context import SimContext
from northward.engine.results import YearFlows
from northward.engine.state import EngineState
from northward.engine.timeline import Point, age_point
from northward.ledger.books import Books
from northward.ledger.transaction import CASH, TaxCategory


def months_of(point: Point) -> int:
    """Absolute month number (year * 12 + month index)."""
    return point.year * 12 + round(point.fraction * 12)


def months_paid(start: Point, year: int) -> int:
    """Benefit months in `year` for a benefit starting at `start` (kept for callers outside the monthly loop)."""
    if year < start.year:
        return 0
    return 12 - round(start.fraction * 12) if year == start.year else 12


def early_reduction(schedule: ReductionSchedule, months_early: int) -> float:
    first = min(months_early, schedule.first_months)
    return first * schedule.first_rate_per_month + max(0, months_early - first) * schedule.additional_rate_per_month


def own_benefit_factor(rules: SocialSecurityDoc, claim_months: int, fra_months: int) -> float:
    """Share of PIA paid for claiming at `claim_months` of age: reduced before FRA, delayed credits after (to 70)."""
    if claim_months < fra_months:
        return 1 - early_reduction(rules.early_reduction, fra_months - claim_months)
    credit_months = min(claim_months, round(rules.latest_credit_age * 12)) - fra_months
    return 1 + rules.delayed_credit_per_year / 12 * credit_months


def spousal_factor(rules: SocialSecurityDoc, start_months: int, fra_months: int) -> float:
    """Share of the spousal amount paid when it starts at `start_months` of age; no delayed credits."""
    if start_months >= fra_months:
        return 1.0
    return 1 - early_reduction(rules.spousal.early_reduction, fra_months - start_months)


def survivor_factor(rules: SocialSecurityDoc, start_months: int, survivor_fra_months: int) -> float:
    """Share of the survivor amount paid when it starts at `start_months` of age (71.5% at 60, 100% at FRA)."""
    if start_months >= survivor_fra_months:
        return 1.0
    earliest = round(rules.survivor.earliest_age * 12)
    span = survivor_fra_months - earliest
    return 1 - rules.survivor.max_reduction * (survivor_fra_months - start_months) / span


def family_maximum(rules: SocialSecurityDoc, pia: float, bend_scale: float = 1.0) -> float:
    """Maximum monthly benefits payable on one worker's record (PIA and bend points in the same dollars)."""
    rates = rules.family_maximum.rates
    bends = [b * bend_scale for b in rules.family_maximum.bend_points]
    total, floor = 0.0, 0.0
    for rate, cap in zip(rates, [*bends, math.inf], strict=True):
        total += rate * max(0.0, min(pia, cap) - floor)
        floor = cap
    return math.floor(total * 10 + 1e-9) / 10  # rounded down to the dime


@dataclass(frozen=True)
class ClaimPlan:
    member: Member
    pia: float  # monthly, start-year dollars (0 without an own record)
    fra: Point
    claim: Point  # when the member files (for their own and any spousal benefit)
    death: Point | None
    survivor_fra_months: int
    # Absolute month numbers (see months_of) and ages in months, derived once since benefits are worked out monthly.
    birth_months: int = field(init=False)
    fra_month: int = field(init=False)
    claim_month: int = field(init=False)
    death_month: int | None = field(init=False)
    fra_months: int = field(init=False)  # age in months at FRA
    claim_months: int = field(init=False)  # age in months at filing

    def __post_init__(self) -> None:
        birth = self.member.birth_year * 12 + self.member.birth_month - 1
        derived = {
            "birth_months": birth,
            "fra_month": months_of(self.fra),
            "claim_month": months_of(self.claim),
            "death_month": None if self.death is None else months_of(self.death),
            "fra_months": months_of(self.fra) - birth,
            "claim_months": months_of(self.claim) - birth,
        }
        for name, value in derived.items():
            object.__setattr__(self, name, value)

    def age_months(self, month: int) -> int:
        return month - self.birth_months

    def alive(self, month: int) -> bool:
        """Benefits are paid through the month before death."""
        return self.death_month is None or month < self.death_month

    def claimed(self, month: int) -> bool:
        return month >= self.claim_month


def claim_plans(ctx: SimContext) -> dict[str, ClaimPlan]:
    rules = ctx.sim.rules.social_security
    levers = ctx.sim.scenario.levers.ss_claim_ages
    plans = {}
    for member in ctx.sim.profile.household.members:
        years, months = rules.full_retirement_age_for(member.birth_year)
        fra = age_point(member, years + months / 12)
        claim_age = levers.get(member.id)
        claim = age_point(member, claim_age.years + claim_age.months / 12) if claim_age else fra
        pia = member.social_security.pia_at_fra if member.social_security else 0.0
        survivor_years, survivor_months = rules.survivor_full_retirement_age_for(member.birth_year)
        death = ctx.timeline.deaths.get(member.id)
        plans[member.id] = ClaimPlan(member, pia, fra, claim, death, survivor_years * 12 + survivor_months)
    return plans


def _survivor_base(rules: SocialSecurityDoc, deceased: ClaimPlan) -> float:
    """Monthly amount a widow(er) at full survivor FRA would get on the deceased's record."""
    death = deceased.death_month
    assert death is not None
    if deceased.claimed(death - 1):
        factor = own_benefit_factor(rules, deceased.claim_months, deceased.fra_months)
        benefit = deceased.pia * factor
        if factor < 1:  # widow(er)'s limit: the larger of the reduced benefit and 82.5% of PIA
            return max(benefit, rules.survivor.widow_limit_floor_fraction * deceased.pia)
        return benefit
    age_at_death = deceased.age_months(death)
    if age_at_death > deceased.fra_months:  # delayed credits earned up to death
        return deceased.pia * own_benefit_factor(rules, age_at_death, deceased.fra_months)
    return deceased.pia


class _Record:
    """Auxiliary benefits requested on one worker's record in a month, before the family maximum."""

    def __init__(self, cap: float):
        self.cap = cap
        self.entries: list[tuple[str, float, float]] = []  # (recipient, amount, factor applied after the cap)

    def add(self, recipient: str, amount: float, factor: float = 1.0) -> None:
        if amount > 0:
            self.entries.append((recipient, amount, factor))

    def paid(self) -> list[tuple[str, float]]:
        requested = sum(amount for _, amount, _ in self.entries)
        scale = min(1.0, self.cap / requested) if requested > 0 else 1.0
        return [(recipient, amount * scale * factor) for recipient, amount, factor in self.entries]


def _eligible_children(
    ctx: SimContext, worker_id: str, year: int, dependents: tuple[Dependent, ...], under_age: int
) -> list[Dependent]:
    members = tuple(m.id for m in ctx.sim.profile.household.members)
    return [
        d
        for d in dependents
        if d.relationship == "child"
        and worker_id in (d.child_of or members)
        and (d.disabled or ctx.timeline.age(d, year) < under_age)
    ]


def pay_social_security(ctx: SimContext, books: Books, state: EngineState, flows: YearFlows, year: int) -> None:
    rules = ctx.sim.rules.social_security
    plans = claim_plans(ctx)
    if not any(p.pia > 0 for p in plans.values()):
        return
    december = year * 12 + 11
    if all(p.pia <= 0 or (p.alive(december) and not p.claimed(december)) for p in plans.values()):
        return  # no one has filed and no worker has died: nothing is payable on any record this year
    bend_scale = ctx.prices.factor(rules.metadata.base_year, ctx.timeline.start_year)
    dependents = ctx.sim.profile.household.dependents
    children = {w: _eligible_children(ctx, w, year, dependents, rules.child.under_age) for w in plans}
    in_care = {w: _eligible_children(ctx, w, year, dependents, rules.child_in_care.child_under_age) for w in plans}
    family_max = {w: family_maximum(rules, plan.pia, bend_scale) for w, plan in plans.items()}

    monthly_totals: dict[str, float] = {}
    own_months: dict[str, tuple[int, float]] = {}  # member -> (months of own benefit, latest monthly own benefit)
    child_total = 0.0
    for month in range(year * 12, year * 12 + 12):
        own: dict[str, float] = {}
        for plan in plans.values():
            if plan.pia <= 0 or not plan.alive(month) or not plan.claimed(month):
                continue
            claim_months = plan.claim_months
            if month >= plan.fra_month:  # withheld months are credited back once FRA is reached
                withheld = round(state.ss_withheld_months.get(plan.member.id, 0.0))
                claim_months = min(
                    max(claim_months + withheld, plan.claim_months), max(plan.fra_months, plan.claim_months)
                )
            own[plan.member.id] = plan.pia * own_benefit_factor(rules, claim_months, plan.fra_months)

        survivor_candidates: dict[str, float] = {}
        for worker in plans.values():
            if worker.pia <= 0:
                continue
            if worker.alive(month):
                if not worker.claimed(month):
                    continue
                record = _Record(family_max[worker.member.id] - worker.pia)
                for child in children[worker.member.id]:
                    record.add(f"child:{child.id}", rules.child.living_worker_fraction * worker.pia)
                for spouse in plans.values():
                    if spouse is worker or not spouse.alive(month):
                        continue
                    # Dual entitlement: a spouse already drawing their own benefit gets only the excess over it.
                    own_pia = spouse.pia if spouse.claimed(month) else 0.0
                    if in_care[worker.member.id]:  # child-in-care spouse: any age, unreduced
                        record.add(spouse.member.id, rules.child_in_care.spouse_fraction * worker.pia - own_pia)
                    elif spouse.claimed(month):
                        start = max(spouse.claim_month, worker.claim_month)
                        factor = spousal_factor(rules, spouse.age_months(start), spouse.fra_months)
                        record.add(spouse.member.id, rules.spousal.fraction_of_pia * worker.pia - own_pia, factor)
            else:
                # Survivors share the deceased's family maximum (the deceased receives nothing).
                record = _Record(family_max[worker.member.id])
                for child in children[worker.member.id]:
                    record.add(f"child:{child.id}", rules.child.survivor_fraction * worker.pia)
                for spouse in plans.values():
                    if spouse is worker or not spouse.alive(month):
                        continue
                    candidates = []
                    if in_care[worker.member.id]:  # mother's/father's benefit: unreduced, any age
                        candidates.append((rules.child_in_care.survivor_parent_fraction * worker.pia, 1.0))
                    assert worker.death_month is not None
                    start = max(worker.death_month + 1, spouse.birth_months + round(rules.survivor.earliest_age * 12))
                    if month >= start:
                        factor = survivor_factor(rules, spouse.age_months(start), spouse.survivor_fra_months)
                        candidates.append(
                            (_survivor_base(rules, worker) * rules.survivor.fraction_of_deceased_benefit, factor)
                        )
                    if candidates:
                        amount, factor = max(candidates, key=lambda c: c[0] * c[1])
                        record.add(f"survivor:{spouse.member.id}", amount, factor)
            for recipient, amount in record.paid():
                if recipient.startswith("child:"):
                    child_total += amount
                elif recipient.startswith("survivor:"):
                    member_id = recipient.split(":", 1)[1]
                    survivor_candidates[member_id] = max(survivor_candidates.get(member_id, 0.0), amount)
                else:
                    own[recipient] = own.get(recipient, 0.0) + amount  # spousal / child-in-care on top of own

        # Insertion order, not a set: the posting order must not depend on the process's string hash seed.
        for member_id in dict.fromkeys((*own, *survivor_candidates)):
            own_amount = own.get(member_id, 0.0)
            if member_id in plans and plans[member_id].claimed(month) and plans[member_id].pia > 0:
                months, _ = own_months.get(member_id, (0, 0.0))
                own_months[member_id] = (months + 1, own_amount)
            # A survivor gets the larger of their own (plus spousal) benefit and the survivor benefit.
            monthly_totals[member_id] = monthly_totals.get(member_id, 0.0) + max(
                own_amount, survivor_candidates.get(member_id, 0.0)
            )

    level = ctx.prices.cola_level(year)  # COLAs are never negative
    totals = {m: amount * level for m, amount in monthly_totals.items()}
    _apply_earnings_test(ctx, books, state, plans, totals, own_months, level, year)

    for member_id, amount in totals.items():
        if amount > 0.005:
            books.move(
                "ssa", CASH, amount, f"Social Security ({member_id})", TaxCategory.SOCIAL_SECURITY, amount, member_id
            )
            flows.social_security += amount
    child_total *= level
    if child_total > 0.005:
        books.move("ssa", CASH, child_total, "Social Security child benefits (the children's income)")
        flows.child_benefits += child_total


def _apply_earnings_test(
    ctx: SimContext,
    books: Books,
    state: EngineState,
    plans: dict[str, ClaimPlan],
    totals: dict[str, float],
    own_months: dict[str, tuple[int, float]],
    level: float,
    year: int,
) -> None:
    """Withhold benefits of members still earning before FRA; the withheld months are credited back at FRA."""
    rules = ctx.sim.rules.social_security
    test = rules.earnings_test
    for member_id, plan in plans.items():
        benefit = totals.get(member_id, 0.0)
        if benefit <= 0 or year > plan.fra.year:
            continue
        wages = books.tax_total(TaxCategory.WAGES, member_id)
        if year == plan.fra.year:
            wages *= plan.fra.fraction  # only earnings before the FRA month count
            exempt, rate = test.fra_year_exempt, test.fra_year_withholding_rate
        else:
            exempt, rate = test.under_fra_exempt, test.under_fra_withholding_rate
        if test.indexed:
            exempt *= ctx.prices.factor(rules.metadata.base_year, year)
        withheld = min(benefit, rate * max(0.0, wages - exempt))
        if withheld <= 0:
            continue
        totals[member_id] = benefit - withheld
        monthly = own_months.get(member_id, (0, 0.0))[1] * level
        if monthly > 0:
            state.ss_withheld_months[member_id] = state.ss_withheld_months.get(member_id, 0.0) + withheld / monthly
