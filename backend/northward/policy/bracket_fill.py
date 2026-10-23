"""How much more ordinary income fits under the top of a tax bracket this year (Roth conversions, inherited IRAs)."""

from __future__ import annotations

from collections.abc import Callable

from northward.engine.context import SimContext
from northward.engine.results import YearFlows
from northward.engine.state import EngineState
from northward.engine.taxes import build_tax_inputs
from northward.ledger.books import Books
from northward.tax.federal import TaxReturn
from northward.tax.inputs import TaxInputs

MAX_STEPS = 30


def _ordinary_taxable(result: TaxReturn) -> float:
    return max(0.0, result.ordinary_income - result.deduction)


def bracket_top(ctx: SimContext, inputs: TaxInputs, rate: float) -> float:
    """Indexed upper bound of the ordinary bracket taxed at `rate` for this year's filing status."""
    brackets = ctx.sim.rules.federal_tax.ordinary_income_brackets
    schedule = brackets.schedules.for_status(inputs.filing_status)
    cap = next((cap for cap, r in schedule if abs(r - rate) < 1e-9), None)
    if cap is None:
        raise ValueError(f"no {rate:.0%} ordinary bracket")
    scale = ctx.tax.prices.factor(ctx.tax.base_year, inputs.year) if brackets.indexed else 1.0
    return cap * scale


def phase_out_magi_cap(ctx: SimContext, inputs: TaxInputs, result: TaxReturn) -> float:
    """Lowest MAGI at which a benefit the household currently gets starts phasing out (inf if none)."""
    rules = ctx.sim.rules.federal_tax
    status = inputs.filing_status
    scale = ctx.tax.prices.factor(ctx.tax.base_year, inputs.year)
    caps = [float("inf")]
    if any(d.ctc or d.other_dependent for d in inputs.dependents):
        caps.append(rules.credits.child_tax_credit.phase_out_threshold.for_status(status))
    education = rules.credits.education.phase_out.for_status(status)
    if education is not None and inputs.education_expenses and any(inputs.education_expenses.values()):
        caps.append(education.start)
    senior = rules.senior_deduction
    if result.senior_deduction > 0 and senior.magi_threshold.for_status(status) is not None:
        caps.append(senior.magi_threshold.for_status(status) * (scale if senior.indexed else 1.0))
    return min(caps)


def _largest_below(evaluate: Callable[[float], float], target: float, guess: float) -> float:
    """Largest x >= 0 with evaluate(x) <= target (to within $1), for a nondecreasing `evaluate`.

    Secant steps from the last point known to be under the target; `evaluate` may have kinks (deductions running
    out, Social Security becoming taxable), so each step re-measures the slope."""
    low, low_value = 0.0, evaluate(0.0)
    if low_value > target:
        return 0.0
    x = max(guess, 0.0)
    for _ in range(MAX_STEPS):
        value = evaluate(x)
        if target - 1.0 <= value <= target:
            return x
        slope = (value - low_value) / (x - low) if x > low else 1.0
        if value < target:
            low, low_value = x, value
        x = max(0.0, x + (target - 0.5 - value) / max(slope, 1e-6))
    return low


def room_under_bracket(
    ctx: SimContext,
    books: Books,
    state: EngineState,
    flows: YearFlows,
    year: int,
    rate: float,
    respect_phase_outs: bool = False,
) -> float:
    """Extra ordinary income that keeps ordinary taxable income at or below the bracket top (within $1), and
    optionally MAGI below the next phase-out threshold.

    Solved numerically because extra income can also raise taxable Social Security and shrink deductions."""
    inputs = build_tax_inputs(ctx, books, state, flows, year)
    tax = ctx.tax
    base = tax.compute(inputs)
    top = bracket_top(ctx, inputs, rate)
    room = _largest_below(
        lambda x: _ordinary_taxable(tax.compute(inputs, extra_ordinary=x)), top, top - _ordinary_taxable(base)
    )
    if respect_phase_outs:
        cap = phase_out_magi_cap(ctx, inputs, base)
        if cap < float("inf"):
            room = min(room, _largest_below(lambda x: tax.compute(inputs, extra_ordinary=x).agi, cap, cap - base.agi))
    return room
