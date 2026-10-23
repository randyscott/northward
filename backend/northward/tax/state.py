"""State income tax for one year, starting from the federal return (AGI and its components)."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field

from northward.config.base import FilingStatus
from northward.config.rules.state_tax import FlatStateTax, NoStateTax, StateRules, _StateTaxBase
from northward.tax.indexing import PriceIndex
from northward.tax.inputs import TaxInputs


@dataclass(frozen=True)
class StateReturn:
    state: str
    income: float  # federal AGI after the state's additions and subtractions
    deduction: float
    exemptions: float
    taxable_income: float
    tax_before_credits: float
    credits: float
    tax: float  # including the state's share of federal additional taxes
    retirement_subtraction: float = 0.0
    credits_forgone: bool = False  # a credit-barring retirement subtraction was claimed
    plan_529_carryforward: dict[str, float] = field(default_factory=dict)  # unused contributions, by beneficiary


NO_STATE_TAX = StateReturn("none", 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)


@dataclass(frozen=True)
class FederalFigures:
    """What the state calculation needs from the federal return."""

    agi: float
    taxable_social_security: float
    capital_gains: float  # net, after the federal loss limit
    additional_taxes: float  # federal early-withdrawal and HSA additional taxes


def compute_state_tax(
    code: str,
    rules: StateRules,
    prices: PriceIndex,
    base_year: int,
    inputs: TaxInputs,
    federal: FederalFigures,
    bracket_tax: Callable[..., float],
) -> StateReturn:
    system = rules.tax
    if isinstance(system, NoStateTax):
        return StateReturn(code, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    with_all = _compute(code, system, prices, base_year, inputs, federal, bracket_tax, skip_barring=False)
    if not with_all.credits_forgone:
        return with_all
    without = _compute(code, system, prices, base_year, inputs, federal, bracket_tax, skip_barring=True)
    return with_all if with_all.tax <= without.tax else without


def _compute(
    code: str,
    system: _StateTaxBase,
    prices: PriceIndex,
    base_year: int,
    inputs: TaxInputs,
    federal: FederalFigures,
    bracket_tax: Callable[..., float],
    skip_barring: bool,
) -> StateReturn:
    year, status = inputs.year, inputs.filing_status
    scale = prices.factor(base_year, year) if system.indexed else 1.0

    income = federal.agi
    if system.exempt_social_security:
        income -= federal.taxable_social_security
    gains = federal.capital_gains
    if gains > 0:
        income -= system.capital_gains_exclusion * gains
    elif gains < 0 and system.capital_loss_limit is not None:
        income += -gains - min(-gains, system.capital_loss_limit)  # a smaller loss allowance than federal
    if system.subtract_health_premiums:
        income -= inputs.health_premiums_after_tax

    retirement, credits_forgone = _retirement_subtraction(system, inputs, federal.agi, skip_barring)
    income -= retirement

    carryforward: dict[str, float] = {}
    plan_529 = system.plan_529_deduction
    if plan_529 is not None:
        cap = plan_529.married_filing_separately_cap if status is FilingStatus.MARRIED_FILING_SEPARATELY else None
        cap = plan_529.cap if cap is None else cap
        if plan_529.indexed:
            cap = prices.indexed(cap, base_year, year, plan_529.rounding)
        beneficiaries = set(inputs.plan_529_contributions) | set(inputs.plan_529_carryforward)
        for beneficiary in sorted(beneficiaries):
            available = inputs.plan_529_contributions.get(beneficiary, 0.0)
            if plan_529.carryforward:
                available += inputs.plan_529_carryforward.get(beneficiary, 0.0)
            used = min(available, cap)
            income -= used
            if plan_529.carryforward and available - used > 0.005:
                carryforward[beneficiary] = available - used
    income = max(0.0, income)

    deduction = _standard_deduction(system, status, income, scale)
    exemptions = 0.0
    if system.personal_exemptions is not None:
        ex = system.personal_exemptions
        dependents = sum(1 for d in inputs.dependents if d.is_dependent)
        seniors = sum(1 for p in inputs.people if p.age >= 65)
        exemptions = ex.per_person * len(inputs.people) + ex.per_dependent * dependents + ex.additional_age_65 * seniors
        if ex.indexed:
            exemptions *= prices.factor(base_year, year)

    taxable = max(0.0, max(0.0, income - deduction) - exemptions)
    if isinstance(system, FlatStateTax):
        tax = system.rate * taxable
    else:
        tax = bracket_tax(system.brackets.for_status(status), 0.0, taxable, scale)

    credits = 0.0 if credits_forgone else _credits(system, inputs, federal.agi)
    credits = min(credits, tax)
    final = tax - credits + system.additional_tax_share * federal.additional_taxes
    return StateReturn(
        code, income, deduction, exemptions, taxable, tax, credits, final, retirement, credits_forgone, carryforward
    )


def _retirement_subtraction(
    system: _StateTaxBase, inputs: TaxInputs, agi: float, skip_barring: bool
) -> tuple[float, bool]:
    """Apply each retirement exclusion in turn to the retirement income left; report if a credit-barring one applied."""
    remaining = {p.member: p.retirement_income for p in inputs.people}
    total, barred = 0.0, False
    joint = inputs.filing_status is FilingStatus.MARRIED_FILING_JOINTLY
    for exclusion in system.retirement_income_exclusions:
        if skip_barring and exclusion.bars_credits:
            continue
        if exclusion.agi_limit is not None:
            limit = exclusion.agi_limit.for_status(inputs.filing_status)
            if limit is not None and agi >= limit:
                continue
        eligible = [p.member for p in inputs.people if p.age >= exclusion.min_age]
        if not eligible:
            continue
        if joint and exclusion.pooled_for_joint and len(eligible) == len(inputs.people) == 2:
            amount = min(sum(remaining.values()), 2 * exclusion.amount)
            share = amount / sum(remaining.values()) if amount > 0 else 0.0
            for member in remaining:
                remaining[member] -= remaining[member] * share
        else:
            amount = 0.0
            for member in eligible:
                used = min(remaining[member], exclusion.amount)
                remaining[member] -= used
                amount += used
        if amount > 0:
            total += amount
            barred = barred or exclusion.bars_credits
    return total, barred


def _standard_deduction(system: _StateTaxBase, status: FilingStatus, income: float, scale: float) -> float:
    sliding = system.sliding_standard_deduction
    if sliding is None:
        return 0.0 if system.standard_deduction is None else system.standard_deduction.for_status(status) * scale

    def schedule(s: FilingStatus) -> float:
        maximum = sliding.maximum.for_status(s) * scale
        start = sliding.phase_out_start.for_status(s) * scale
        return max(0.0, maximum - sliding.phase_out_rate.for_status(s) * max(0.0, income - start))

    amount = schedule(status)
    if status is FilingStatus.HEAD_OF_HOUSEHOLD and sliding.head_of_household_floor == "single":
        amount = max(amount, schedule(FilingStatus.SINGLE))
    return amount


def _credits(system: _StateTaxBase, inputs: TaxInputs, agi: float) -> float:
    credits = 0.0
    couple = system.married_couple_credit
    if couple is not None and inputs.filing_status is FilingStatus.MARRIED_FILING_JOINTLY and len(inputs.people) == 2:
        credits += couple.rate * min(max(0.0, min(p.wages for p in inputs.people)), couple.earned_income_cap)
    care = system.dependent_care_credit
    qualifying = sum(1 for d in inputs.dependents if d.care)
    if care is not None and qualifying and inputs.filing_status is not FilingStatus.MARRIED_FILING_SEPARATELY:
        cap = care.expense_cap_one if qualifying == 1 else care.expense_cap_two_or_more
        base = min(
            max(0.0, cap - inputs.dependent_care_exclusion), inputs.care_expenses, min(p.wages for p in inputs.people)
        )
        steps = math.ceil(max(0.0, agi - care.agi_threshold) / care.step - 1e-9) if agi > care.agi_threshold else 0
        credits += max(0.0, base) * max(care.floor_rate, care.max_rate - 0.01 * steps)
    return credits
