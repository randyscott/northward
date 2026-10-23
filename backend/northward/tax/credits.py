"""Federal credits for dependents and education, applied in IRS order against income tax."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from northward.config.base import FilingStatus
from northward.config.rules.federal_tax import Credits as CreditRules
from northward.tax.indexing import PriceIndex
from northward.tax.inputs import TaxInputs


@dataclass(frozen=True)
class CreditResult:
    dependent_care: float = 0.0
    american_opportunity: float = 0.0  # nonrefundable part used
    lifetime_learning: float = 0.0
    child_tax_credit: float = 0.0  # nonrefundable part used, including the Credit for Other Dependents
    additional_child_tax_credit: float = 0.0  # refundable
    american_opportunity_refundable: float = 0.0
    # Credits attributed to each dependent after phase-outs (CTC/ODC and AOTC), before tax-liability limits.
    by_dependent: dict[str, float] = field(default_factory=dict)

    @property
    def nonrefundable(self) -> float:
        return self.dependent_care + self.american_opportunity + self.lifetime_learning + self.child_tax_credit

    @property
    def refundable(self) -> float:
        return self.additional_child_tax_credit + self.american_opportunity_refundable


def _steps(amount: float, step: float) -> int:
    """How many `step`s (or fractions of one) `amount` spans: the statutes' "each $X or fraction thereof"."""
    return math.ceil(amount / step - 1e-9) if amount > 0 else 0


def care_credit_rate(rules: CreditRules, status: FilingStatus, agi: float) -> float | None:
    """Child and Dependent Care Credit rate for this AGI; None if the filing status is ineligible."""
    care = rules.child_dependent_care
    rate = care.max_rate
    for stage in care.stages:
        threshold, step = stage.agi_threshold.for_status(status), stage.step.for_status(status)
        if threshold is None or step is None:
            return None
        rate = max(stage.floor_rate, rate - 0.01 * _steps(agi - threshold, step))
    return rate


def compute_credits(
    rules: CreditRules, prices: PriceIndex, base_year: int, inputs: TaxInputs, agi: float, liability: float
) -> CreditResult:
    status, magi = inputs.filing_status, agi
    remaining = liability
    by_dependent: dict[str, float] = {}

    # 1. Child and Dependent Care Credit (nonrefundable). The expense cap is reduced by FSA-excluded benefits,
    #    and expenses are limited to the lower earner's earned income.
    dependent_care = 0.0
    qualifying = sum(1 for d in inputs.dependents if d.care)
    rate = care_credit_rate(rules, status, agi)
    if qualifying and rate is not None:
        care = rules.child_dependent_care
        cap = care.expense_cap_one if qualifying == 1 else care.expense_cap_two_or_more
        base = min(max(0.0, cap - inputs.dependent_care_exclusion), inputs.care_expenses)
        base = min(base, min(p.wages for p in inputs.people))
        dependent_care = min(max(0.0, base) * rate, remaining)
        remaining -= dependent_care

    # 2. Education credits. AOTC per student (40% refundable); LLC per return. Both share a MAGI phase-out.
    american_opportunity = aotc_refundable = lifetime_learning = 0.0
    education = rules.education
    phase_out = education.phase_out.for_status(status)
    if phase_out is not None and inputs.education_expenses:
        # Share of the credits that survives the linear MAGI phase-out.
        span = phase_out.end - phase_out.start
        phased = (magi - phase_out.start) / span if span > 0 else float(magi >= phase_out.start)
        allowed = 1.0 - min(1.0, max(0.0, phased))
        aotc = education.american_opportunity
        statuses = {d.id: d for d in inputs.dependents}
        member_ids = {p.member for p in inputs.people}
        llc_expenses, aotc_total = 0.0, 0.0
        for beneficiary, expenses in inputs.education_expenses.items():
            dependent = statuses.get(beneficiary)
            if dependent is not None and dependent.education_credit == "american_opportunity":
                credit = min(expenses, aotc.tier1_expenses) * aotc.tier1_rate
                credit += min(max(0.0, expenses - aotc.tier1_expenses), aotc.tier2_expenses) * aotc.tier2_rate
                credit *= allowed
                aotc_total += credit
                by_dependent[beneficiary] = by_dependent.get(beneficiary, 0.0) + credit
            elif (dependent is not None and dependent.education_credit) or beneficiary in member_ids:
                llc_expenses += expenses
        aotc_refundable = aotc_total * aotc.refundable_fraction
        american_opportunity = min(aotc_total - aotc_refundable, remaining)
        remaining -= american_opportunity
        llc = education.lifetime_learning
        lifetime_learning = min(min(llc_expenses, llc.expense_cap_per_return) * llc.rate * allowed, remaining)
        remaining -= lifetime_learning

    # 3. Child Tax Credit and Credit for Other Dependents, phased out together; the unused CTC may be refundable.
    ctc_rules = rules.child_tax_credit
    ctc_kids = [d.id for d in inputs.dependents if d.ctc]
    others = [d.id for d in inputs.dependents if d.other_dependent]
    child_tax_credit = additional = 0.0
    if ctc_kids or others:
        per_child = ctc_rules.amount_per_child
        if ctc_rules.amount_indexed:
            per_child = prices.indexed(per_child, base_year, inputs.year, ctc_rules.amount_rounding)
        per_other = rules.other_dependent_credit.amount
        tentative = per_child * len(ctc_kids) + per_other * len(others)
        threshold = ctc_rules.phase_out_threshold.for_status(status)
        reduction = ctc_rules.phase_out_per_1000 * _steps(magi - threshold, 1000)
        allowed_total = max(0.0, tentative - reduction)
        share = allowed_total / tentative
        for kid in ctc_kids:
            by_dependent[kid] = by_dependent.get(kid, 0.0) + per_child * share
        for other in others:
            by_dependent[other] = by_dependent.get(other, 0.0) + per_other * share
        child_tax_credit = min(allowed_total, remaining)
        remaining -= child_tax_credit
        if ctc_kids:
            refundable_max = ctc_rules.refundable_max_per_child
            if ctc_rules.refundable_indexed:
                refundable_max = prices.indexed(refundable_max, base_year, inputs.year, ctc_rules.refundable_rounding)
            earned = sum(p.wages for p in inputs.people)
            additional = min(
                allowed_total - child_tax_credit,
                refundable_max * len(ctc_kids),
                ctc_rules.refundable_rate * max(0.0, earned - ctc_rules.refundable_earned_income_threshold),
            )
            additional = max(0.0, additional)

    return CreditResult(
        dependent_care=dependent_care,
        american_opportunity=american_opportunity,
        lifetime_learning=lifetime_learning,
        child_tax_credit=child_tax_credit,
        additional_child_tax_credit=additional,
        american_opportunity_refundable=aotc_refundable,
        by_dependent=by_dependent,
    )
