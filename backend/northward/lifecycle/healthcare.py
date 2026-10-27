"""Healthcare costs each year: employer coverage while anyone works, the unsubsidized individual market before
Medicare, Medicare Part B/D plus IRMAA (from MAGI two years earlier) and a supplement, out-of-pocket costs, and HSA
payment of qualified expenses. ACA premium subsidies aren't modeled (docs/modeling.md)."""

from __future__ import annotations

from northward.config.base import FilingStatus
from northward.config.rules.account_types import AccountFamily
from northward.config.rules.healthcare import HealthcareAssumptions
from northward.engine.context import SimContext
from northward.engine.results import YearFlows
from northward.engine.state import EngineState
from northward.engine.timeline import age_point
from northward.ledger.books import Books
from northward.ledger.transaction import CASH, TaxCategory


def _months_in(year: int, start: tuple[int, float] | None, end: tuple[int, float] | None) -> int:
    """Months of `year` from `start` (inclusive) to `end` (exclusive); None means unbounded."""
    first = 0 if start is None or start[0] < year else (12 if start[0] > year else round(start[1] * 12))
    last = 12 if end is None or end[0] > year else (0 if end[0] < year else round(end[1] * 12))
    return max(0, last - first)


def irmaa_monthly(ctx: SimContext, state: EngineState, year: int) -> tuple[float, float]:
    """Part B and Part D monthly surcharges per enrollee, in `year` dollars, from the return two years earlier."""
    irmaa = ctx.sim.rules.healthcare.irmaa
    lookback = year - irmaa.lookback_years
    if lookback not in state.magi_history:
        if not state.magi_history:
            return 0.0, 0.0
        lookback = min(state.magi_history)  # early years: the simulation's first return stands in
    magi, status = state.magi_history[lookback], state.filing_history[lookback]
    tiers = {
        FilingStatus.MARRIED_FILING_JOINTLY: irmaa.tiers.joint,
        FilingStatus.MARRIED_FILING_SEPARATELY: irmaa.tiers.separate,
    }.get(status, irmaa.tiers.single)
    base_year = ctx.sim.rules.healthcare.metadata.base_year
    for tier in tiers:
        bound = tier.up_to
        if irmaa.thresholds_indexed and bound != float("inf"):
            start = base_year if tier.indexed_from is None else tier.indexed_from - 1
            if year > start:
                bound = round(bound * ctx.prices.factor(start, year) / irmaa.rounding) * irmaa.rounding
        if magi <= bound:
            break
    health_level = ctx.prices.factor(base_year, year, "healthcare")
    return tier.part_b_adjustment * health_level, tier.part_d_adjustment * health_level


def pay_healthcare(ctx: SimContext, books: Books, state: EngineState, flows: YearFlows, year: int) -> None:
    assumptions: HealthcareAssumptions | None = ctx.sim.profile.health_costs
    if assumptions is None or ctx.sim.profile.spending.base.includes_healthcare:
        return  # base spending already covers healthcare
    rules = ctx.sim.rules.healthcare
    timeline = ctx.timeline
    health = ctx.prices.level(year, "healthcare")
    base_to_start = ctx.prices.factor(rules.metadata.base_year, timeline.start_year, "healthcare")

    # Employer coverage (for the whole family) lasts as long as the longest-working member's salary.
    salaried = [(ctx.timeline.salary_fraction(s, year), s.owner) for s in ctx.salaries]
    employer_share, employer_owner = max(salaried, default=(0.0, None))
    employer_months = round(employer_share * 12)
    if employer_months:
        premium = assumptions.employer_premium * health * employer_months / 12
        books.move(
            CASH,
            "healthcare:employer_premium",
            premium,
            "employer health premium (pre-tax payroll)",
            TaxCategory.CAFETERIA,
            premium,
            employer_owner,
        )
        flows.spending["healthcare_premiums"] += premium

    part_b_irmaa, part_d_irmaa = irmaa_monthly(ctx, state, year)
    premiums = out_of_pocket = irmaa_paid = qualified = 0.0
    for member in timeline.living_members(year):
        death = timeline.deaths.get(member.id)
        alive = _months_in(year, None, death)
        medicare = _months_in(year, age_point(member, rules.medicare.eligibility_age), death)
        individual = max(0, alive - medicare - employer_months)
        age = timeline.age(member, year)
        premiums += (
            assumptions.individual_premium_age_40
            * rules.age_factor(age)
            / rules.age_factor(40)
            * health
            * individual
            / 12
        )
        part_b = rules.medicare.part_b_monthly_premium * base_to_start * health * medicare
        part_d = assumptions.part_d_premium * health * medicare / 12
        supplement = assumptions.supplement_premium * health * medicare / 12
        surcharges = (part_b_irmaa + part_d_irmaa) * medicare
        oop_rate = (
            assumptions.out_of_pocket_65_plus
            if age >= rules.medicare.eligibility_age
            else assumptions.out_of_pocket_under_65
        )
        oop = oop_rate * health * alive / 12
        premiums += part_b + part_d + supplement
        irmaa_paid += surcharges
        out_of_pocket += oop
        qualified += part_b + part_d + surcharges + oop  # HSA-qualified (Medigap premiums aren't)

    for dependent in ctx.sim.profile.household.dependents:
        age = timeline.age(dependent, year)
        if age >= assumptions.dependent_coverage_until_age:
            continue
        individual = 12 - employer_months
        premiums += (
            assumptions.individual_premium_age_40
            * rules.age_factor(age)
            / rules.age_factor(40)
            * health
            * individual
            / 12
        )
        oop = assumptions.out_of_pocket_under_65 * health
        out_of_pocket += oop
        qualified += oop

    flows.after_tax_health_premiums += premiums + irmaa_paid
    for label, amount in (
        ("healthcare_premiums", premiums),
        ("medicare_irmaa", irmaa_paid),
        ("healthcare_out_of_pocket", out_of_pocket),
    ):
        if amount > 0.005:
            books.move(CASH, f"healthcare:{label}", amount, label.replace("_", " "))
            flows.spending[label] += amount
    paid = _pay_from_hsas(ctx, books, flows, year, qualified, assumptions)
    # HSA money goes to out-of-pocket costs first; any beyond that paid premiums, which then aren't after-tax.
    flows.after_tax_health_premiums -= min(max(0.0, paid - out_of_pocket), flows.after_tax_health_premiums)


def _pay_from_hsas(
    ctx: SimContext, books: Books, flows: YearFlows, year: int, qualified: float, assumptions: HealthcareAssumptions
) -> float:
    """HSA reimbursements of this year's qualified costs; returns the total paid."""
    paid = 0.0
    if assumptions.hsa_medical == "never" or qualified <= 0.005:
        return paid
    for account in books.accounts.values():
        if account.family is not AccountFamily.HSA or account.balance <= 0 or qualified <= 0.005:
            continue
        member = ctx.sim.profile.household.member(account.owner)
        if (
            assumptions.hsa_medical == "pay_when_retired"
            and member is not None
            and year
            < ctx.timeline.retirement[member.id].year + (1 if ctx.timeline.retirement[member.id].fraction > 0 else 0)
        ):
            continue
        amount = min(account.balance, qualified)
        books.move(
            account.id, CASH, amount, "HSA reimbursement of medical costs", TaxCategory.TAX_FREE, amount, account.owner
        )
        flows.hsa_medical += amount
        qualified -= amount
        paid += amount
    return paid
