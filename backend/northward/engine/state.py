"""Mutable state carried from one simulated year to the next (beyond account balances)."""

from __future__ import annotations

from dataclasses import dataclass, field

from northward.config.base import FilingStatus


@dataclass
class EngineState:
    prior_year_fica_wages: dict[str, float]  # per salary stream, for the Roth catch-up rule
    fsa_pool: float = 0.0  # this year's dependent-care FSA money awaiting reimbursement
    fsa_forfeits: list[tuple[int, float]] = field(default_factory=list)
    shortfalls: list[tuple[int, float]] = field(default_factory=list)
    unconverged_tax_years: list[int] = field(default_factory=list)
    capital_loss_carryforward: float = 0.0
    tax_iterations: list[int] = field(default_factory=list)  # settlement rounds per year (diagnostics)
    start_balances: dict[str, float] = field(default_factory=dict)  # prior year-end balances (for RMDs)
    ss_withheld_months: dict[str, float] = field(default_factory=dict)  # earnings-test months, credited at FRA
    plan_529_rollovers: dict[str, float] = field(default_factory=dict)  # lifetime 529->Roth per beneficiary
    notes: set[str] = field(default_factory=set)  # one-line warnings, reported once
    residence: str = "none"  # current state (rules/state_tax.yaml key)
    state_529_carryforward: dict[str, float] = field(default_factory=dict)  # state 529 deduction carryover
    magi_history: dict[int, float] = field(default_factory=dict)  # for IRMAA's two-year lookback
    filing_history: dict[int, FilingStatus] = field(default_factory=dict)
    # (year, configured status, status used) when HoH/QSS had no qualifying dependent
    status_fallbacks: list[tuple[int, FilingStatus, FilingStatus]] = field(default_factory=list)
