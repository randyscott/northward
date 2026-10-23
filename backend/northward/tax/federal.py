"""Federal income tax, NIIT, FICA, and additional taxes for one year: a full `TaxReturn` from `TaxInputs`."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass

from northward.config.base import FilingStatus
from northward.config.rules.federal_tax import BracketSchedule, FederalTaxDoc, SsTaxThresholds
from northward.config.rules.state_tax import StateTaxDoc
from northward.tax.credits import CreditResult, compute_credits
from northward.tax.indexing import PriceIndex
from northward.tax.inputs import TaxInputs
from northward.tax.state import NO_STATE_TAX, FederalFigures, StateReturn, compute_state_tax

_MARRIED = {
    FilingStatus.MARRIED_FILING_JOINTLY,
    FilingStatus.MARRIED_FILING_SEPARATELY,
    FilingStatus.QUALIFYING_SURVIVING_SPOUSE,
}
MARGINAL_PROBE = 100.0  # extra ordinary income used to measure the marginal rate


@dataclass(frozen=True)
class TaxReturn:
    year: int
    filing_status: FilingStatus
    # Income
    wages: float
    interest: float
    ordinary_dividends: float
    qualified_dividends: float
    capital_gains: float  # net after the loss limit (negative: the deductible loss)
    capital_loss_carryforward: float  # unused losses carried to next year
    taxable_social_security: float
    other_ordinary: float
    agi: float
    ordinary_income: float  # AGI minus qualified dividends and net gains
    preferential_income: float  # qualified dividends and net long-term gains
    # Deductions and taxable income
    standard_deduction: float
    senior_deduction: float
    taxable_income: float
    # Tax
    ordinary_tax: float
    capital_gains_tax: float
    credits: CreditResult
    income_tax: float  # after nonrefundable credits
    net_investment_income_tax: float
    social_security_tax: float
    medicare_tax: float  # including the Additional Medicare Tax
    additional_taxes: float  # early-withdrawal and HSA additional taxes
    state: StateReturn = NO_STATE_TAX
    marginal_rate: float | None = None  # federal + state, on the next dollar of ordinary (non-wage) income

    @property
    def magi(self) -> float:
        return self.agi  # no foreign-income or tax-exempt adjustments are modeled

    @property
    def deduction(self) -> float:
        return self.standard_deduction + self.senior_deduction

    @property
    def income_tax_before_credits(self) -> float:
        return self.ordinary_tax + self.capital_gains_tax

    @property
    def total(self) -> float:
        """Everything owed for the year: federal and state income tax, NIIT, FICA, additional taxes, less
        refundable credits."""
        return (
            self.state.tax
            + self.income_tax
            + self.net_investment_income_tax
            + self.social_security_tax
            + self.medicare_tax
            + self.additional_taxes
            - self.credits.refundable
        )

    @property
    def effective_rate(self) -> float:
        """Federal income tax (after all credits) plus NIIT, as a share of AGI."""
        if self.agi <= 0:
            return 0.0
        return (self.income_tax + self.net_investment_income_tax - self.credits.refundable) / self.agi


def bracket_tax(schedule: BracketSchedule, low: float, high: float, scale: float = 1.0) -> float:
    """Tax on the slice [low, high) of taxable income; bracket bounds are multiplied by `scale` (indexing)."""
    tax, floor = 0.0, 0.0
    for cap, rate in schedule:
        cap *= scale
        segment = min(high, cap) - max(low, floor)
        if segment > 0:
            tax += segment * rate
        floor = cap
        if floor >= high:
            break
    return tax


def taxable_social_security(
    benefits: float, other_income: float, thresholds: SsTaxThresholds, r1: float, r2: float
) -> float:
    """IRS Pub. 915 worksheet: provisional income = other income + half of benefits."""
    if benefits <= 0:
        return 0.0
    provisional = other_income + 0.5 * benefits
    if provisional <= thresholds.base:
        return 0.0
    tier1 = min(r1 * benefits, r1 * (provisional - thresholds.base))
    if provisional <= thresholds.adjusted_base:
        return tier1
    capped_tier1 = min(r1 * benefits, r1 * (thresholds.adjusted_base - thresholds.base))
    return min(r2 * benefits, r2 * (provisional - thresholds.adjusted_base) + capped_tier1)


def _income_taxes(result: TaxReturn) -> float:
    return result.income_tax + result.net_investment_income_tax - result.credits.refundable + result.state.tax


class FederalTax:
    def __init__(
        self, rules: FederalTaxDoc, prices: PriceIndex, real_wage_growth: float, states: StateTaxDoc | None = None
    ):
        self.rules = rules
        self.states = states
        self.prices = prices
        self.base_year = rules.metadata.base_year
        self.real_wage_growth = real_wage_growth

    def _scale(self, indexed: bool, year: int) -> float:
        return self.prices.factor(self.base_year, year) if indexed else 1.0

    def compute(self, inputs: TaxInputs, extra_ordinary: float = 0.0) -> TaxReturn:
        r, year, status = self.rules, inputs.year, inputs.filing_status
        wages = sum(p.wages for p in inputs.people)
        other_ordinary = inputs.other_ordinary + extra_ordinary

        # Capital gains net of carried-forward losses; up to the annual limit of a net loss offsets ordinary income.
        net_gain = inputs.capital_gains - inputs.capital_loss_carryforward
        loss_limit = (
            r.capital_loss.married_filing_separately_limit
            if status is FilingStatus.MARRIED_FILING_SEPARATELY
            else r.capital_loss.annual_limit
        )
        capital_gains = net_gain if net_gain >= 0 else -min(-net_gain, loss_limit)
        carryforward = max(0.0, -net_gain - loss_limit)

        income_before_ss = (
            wages
            - inputs.ira_deduction
            + other_ordinary
            + inputs.interest
            + inputs.ordinary_dividends
            + inputs.qualified_dividends
            + capital_gains
        )
        ss = r.social_security_taxability
        taxable_ss = taxable_social_security(
            inputs.social_security, income_before_ss, ss.thresholds.for_status(status), ss.tier1_rate, ss.tier2_rate
        )
        agi = income_before_ss + taxable_ss
        preferential = inputs.qualified_dividends + max(0.0, capital_gains)
        ordinary_income = agi - preferential

        sd = r.standard_deduction
        seniors = sum(1 for p in inputs.people if p.age >= 65)
        extra = sd.additional_65_or_blind.married if status in _MARRIED else sd.additional_65_or_blind.unmarried
        standard = (sd.amounts.for_status(status) + extra * seniors) * self._scale(sd.indexed, year)
        senior = self._senior_deduction(inputs, agi)
        deduction = standard + senior

        ordinary_taxable = max(0.0, ordinary_income - deduction)
        taxable = max(0.0, agi - deduction)
        brackets, gains = r.ordinary_income_brackets, r.capital_gains_brackets
        ordinary_tax = bracket_tax(
            brackets.schedules.for_status(status), 0.0, ordinary_taxable, self._scale(brackets.indexed, year)
        )
        capital_gains_tax = bracket_tax(
            gains.schedules.for_status(status), ordinary_taxable, taxable, self._scale(gains.indexed, year)
        )
        liability = ordinary_tax + capital_gains_tax
        credits = compute_credits(r.credits, self.prices, self.base_year, inputs, agi, liability)

        niit = r.net_investment_income_tax
        investment_income = (
            inputs.interest + inputs.ordinary_dividends + inputs.qualified_dividends + max(0.0, capital_gains)
        )
        niit_threshold = niit.magi_threshold.for_status(status) * self._scale(niit.indexed, year)
        net_investment_income_tax = niit.rate * min(investment_income, max(0.0, agi - niit_threshold))

        social_security_tax, medicare_tax = self._fica(inputs)
        p = r.penalties
        additional = (
            p.early_withdrawal_rate * inputs.early_distribution_base
            + p.hsa_non_medical_rate * inputs.hsa_non_medical_base
            + p.plan_529_non_qualified_earnings_rate * inputs.plan_529_non_qualified_base
        )

        state = NO_STATE_TAX
        if self.states is not None and inputs.state in self.states.states:
            state = compute_state_tax(
                inputs.state,
                self.states.states[inputs.state],
                self.prices,
                self.states.base_year,
                inputs,
                FederalFigures(agi, taxable_ss, capital_gains, additional),
                bracket_tax,
            )
        return TaxReturn(
            year=year,
            filing_status=status,
            wages=wages,
            interest=inputs.interest,
            ordinary_dividends=inputs.ordinary_dividends,
            qualified_dividends=inputs.qualified_dividends,
            capital_gains=capital_gains,
            capital_loss_carryforward=carryforward,
            taxable_social_security=taxable_ss,
            other_ordinary=other_ordinary,
            agi=agi,
            ordinary_income=ordinary_income,
            preferential_income=preferential,
            standard_deduction=standard,
            senior_deduction=senior,
            taxable_income=taxable,
            ordinary_tax=ordinary_tax,
            capital_gains_tax=capital_gains_tax,
            credits=credits,
            income_tax=liability - credits.nonrefundable,
            net_investment_income_tax=net_investment_income_tax,
            social_security_tax=social_security_tax,
            medicare_tax=medicare_tax,
            additional_taxes=additional,
            state=state,
        )

    def with_marginal_rate(self, inputs: TaxInputs, result: TaxReturn) -> TaxReturn:
        """Attach the marginal rate on ordinary income, including phase-out effects (senior deduction, credits,
        SS taxability, NIIT)."""
        probe = self.compute(inputs, extra_ordinary=MARGINAL_PROBE)
        rate = (_income_taxes(probe) - _income_taxes(result)) / MARGINAL_PROBE
        return dataclasses.replace(result, marginal_rate=rate)

    def _senior_deduction(self, inputs: TaxInputs, magi: float) -> float:
        senior = self.rules.senior_deduction
        threshold = senior.magi_threshold.for_status(inputs.filing_status)
        if threshold is None or not senior.first_year <= inputs.year <= senior.last_year:
            return 0.0
        scale = self._scale(senior.indexed, inputs.year)
        per_person = max(
            0.0, senior.amount_per_person * scale - senior.phase_out_rate * max(0.0, magi - threshold * scale)
        )
        return per_person * sum(1 for p in inputs.people if p.age >= senior.min_age)

    def _fica(self, inputs: TaxInputs) -> tuple[float, float]:
        fica, year = self.rules.fica, inputs.year
        wage_base = fica.social_security_wage_base
        if fica.wage_base_indexed:
            wage_base *= self.prices.factor(self.base_year, year) * (1 + self.real_wage_growth) ** (
                year - self.base_year
            )
        social_security = sum(fica.social_security_rate * min(p.fica_wages, wage_base) for p in inputs.people)
        total_wages = sum(p.fica_wages for p in inputs.people)
        threshold = fica.additional_medicare_threshold.for_status(inputs.filing_status) * self._scale(
            fica.additional_medicare_indexed, year
        )
        medicare = fica.medicare_rate * total_wages + fica.additional_medicare_rate * max(0.0, total_wages - threshold)
        return social_security, medicare
