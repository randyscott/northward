"""Write simulation results as CSV or JSON: one row per year, and the transaction ledger."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, Literal

from northward.engine.results import SimulationResult, YearState

_BUCKETS = ("taxable", "deferred", "roth", "hsa")


def year_row(state: YearState) -> dict[str, Any]:
    f = state.flows
    row: dict[str, Any] = {"year": state.year, "residence": state.residence}
    row.update({f"age_{member}": age for member, age in state.ages.items()})
    row.update(
        price_level=state.price_level,
        gross_wages=f.gross_wages,
        traditional_deferrals=f.traditional_deferrals,
        roth_deferrals=f.roth_deferrals,
        employer_contributions=f.employer_contributions,
        hsa_contributions=f.hsa_contributions,
        fsa_elections=f.fsa_elections,
        fsa_forfeited=f.fsa_forfeited,
        pension_income=f.pension_income,
        social_security=f.social_security,
        child_benefits=f.child_benefits,
        rmds=f.rmds,
        inherited_distributions=f.inherited_distributions,
        roth_conversions=f.roth_conversions,
        plan_529_qualified=sum(f.plan_529_qualified.values()),
        plan_529_other=f.plan_529_other,
        event_inflows=f.event_inflows,
        hsa_medical=f.hsa_medical,
        other_income=f.other_income,
        investment_income=f.investment_income,
        spending=f.total_spending,
        debt_payments=f.debt_payments,
        contributions=f.contributions,
        **{f"withdrawals_{b}": f.withdrawals.get(b, 0.0) for b in _BUCKETS},
        realized_gains=f.realized_gains,
        **_tax_columns(state),
        total_taxes=f.total_taxes,
        swept=f.swept,
        reserve_drawn=f.reserve_drawn,
        reserve_topped_up=f.reserve_topped_up,
        shortfall=f.shortfall,
        growth=f.growth,
        total_assets=state.total_assets,
        total_liabilities=state.total_liabilities,
        net_worth=state.net_worth,
        net_worth_today=state.net_worth / state.price_level,
    )
    row.update({f"balance_{k}": v for k, v in state.balances.items()})
    row.update({f"loan_{k}": v for k, v in state.liabilities.items()})
    return row


def _tax_columns(state: YearState) -> dict[str, Any]:
    t = state.flows.taxes
    if t is None:
        return {}
    return {
        "filing_status": t.filing_status.value,
        "agi": t.agi,
        "taxable_social_security": t.taxable_social_security,
        "capital_gains": t.capital_gains,
        "capital_loss_carryforward": t.capital_loss_carryforward,
        "standard_deduction": t.standard_deduction,
        "senior_deduction": t.senior_deduction,
        "taxable_income": t.taxable_income,
        "ordinary_tax": t.ordinary_tax,
        "capital_gains_tax": t.capital_gains_tax,
        "nonrefundable_credits": t.credits.nonrefundable,
        "refundable_credits": t.credits.refundable,
        "income_tax": t.income_tax,
        "net_investment_income_tax": t.net_investment_income_tax,
        "social_security_tax": t.social_security_tax,
        "medicare_tax": t.medicare_tax,
        "additional_taxes": t.additional_taxes,
        "state_income": t.state.income,
        "state_retirement_subtraction": t.state.retirement_subtraction,
        "state_tax": t.state.tax,
        "marginal_rate": t.marginal_rate,
        "effective_rate": t.effective_rate,
        **{f"credits_{dependent}": amount for dependent, amount in t.credits.by_dependent.items()},
    }


def year_rows(result: SimulationResult) -> list[dict[str, Any]]:
    rows = [year_row(state) for state in result.years]
    # Spending categories and credited dependents vary by year; give every row the same columns.
    categories = sorted({c for s in result.years for c in s.flows.spending})
    columns = list(dict.fromkeys(key for row in rows for key in row))
    for row, state in zip(rows, result.years, strict=True):
        row.update({f"spending_{c}": state.flows.spending.get(c, 0.0) for c in categories})
    # Missing values (e.g. a deceased member's age) are left blank.
    return [{key: row.get(key) for key in [*columns, *(f"spending_{c}" for c in categories)]} for row in rows]


def ledger_rows(result: SimulationResult) -> list[dict[str, Any]]:
    return [{**asdict(t), "tax_category": t.tax_category.value} for t in result.transactions]


def write_result(result: SimulationResult, out_dir: Path, fmt: Literal["csv", "json"] = "csv") -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    tables = {"years": year_rows(result)}
    if result.transactions:
        tables["ledger"] = ledger_rows(result)
    written = []
    for name, rows in tables.items():
        path = out_dir / f"{name}.{fmt}"
        if fmt == "json":
            path.write_text(json.dumps(rows, indent=1))
        else:
            with path.open("w", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else [])
                writer.writeheader()
                writer.writerows(rows)
        written.append(path)
    if result.warnings:
        path = out_dir / "warnings.txt"
        path.write_text("\n".join(result.warnings) + "\n")
        written.append(path)
    return written
