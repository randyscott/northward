"""Build small in-memory profiles on top of the real rules, with an optional zero-volatility market preset."""

from __future__ import annotations

import copy
from typing import Any

import yaml

from northward.config.loader import SimulationInput, load_simulation_input
from northward.config.source import FileSource, MemorySource
from northward.engine.results import SimulationResult
from northward.engine.simulate import simulate
from tests.conftest import DATA_DIR

FLAT_PRESET: dict[str, Any] = {
    "id": "flat",
    "description": "Zero-volatility test market.",
    "factors": {
        "stocks": {"mean": 0.05, "std_dev": 0.0},
        "bonds": {"mean": 0.0, "std_dev": 0.0},
        "cash": {"mean": 0.02, "std_dev": 0.0},
        "inflation": {"mean": 0.0, "std_dev": 0.0, "distribution": "normal"},
    },
    "taxable_income": {"stocks": {"dividend_yield": 0.0, "qualified_fraction": 1.0}, "bonds": {"interest_yield": 0.0}},
}

STOCKS = {"kind": "static_allocation", "stocks": 1.0, "bonds": 0.0}


def member(id="pat", birth_year=1970, birth_month=1, retire=90):
    return {
        "id": id,
        "name": id.title(),
        "birth_year": birth_year,
        "birth_month": birth_month,
        "target_retirement_age": retire,
    }


def build(
    *,
    members: list[dict],
    accounts: list[dict],
    income: list[dict] = (),
    spending: dict | float = 0.0,
    liabilities: list[dict] = (),
    dependents: list[dict] = (),
    filing_status: str | None = None,
    horizon: dict | None = None,
    levers: dict | None = None,
    market: dict | None = None,
    macro: dict | None = None,
    preset: dict | None = None,
    events: list[dict] = (),
    health_costs: dict | None = None,
    states: dict | None = None,
    state: str = "none",
) -> SimulationInput:
    """Synthetic profiles have no separate healthcare costs (their base spending "includes" it) unless
    `health_costs` is given."""
    source = MemorySource.copy_of(FileSource(DATA_DIR))
    presets = yaml.safe_load(source.rules["market_assumptions"])
    extra = copy.deepcopy(FLAT_PRESET)
    if preset:
        extra.update(preset)
    presets["presets"].append(extra)
    source.rules["market_assumptions"] = yaml.safe_dump(presets)
    if states:
        state_rules = yaml.safe_load(source.rules["state_tax"])
        state_rules["states"].update(states)
        source.rules["state_tax"] = yaml.safe_dump(state_rules)

    status = filing_status or ("married_filing_jointly" if len(members) == 2 else "single")
    if not isinstance(spending, dict):
        spending = {"base": {"amount": spending}}
    if health_costs is None:
        spending = {**spending, "base": {"includes_healthcare": True, **spending["base"]}}
    docs = {
        "household": {
            "household": {"filing_status": status, "state": state},
            "members": members,
            "dependents": list(dependents),
        },
        "accounts": {"accounts": accounts},
        "income": {"income_streams": list(income)},
        "liabilities": {"liabilities": list(liabilities)},
        "spending": {"spending": spending},
        "events": {"events": list(events)},
        "health_costs": health_costs or {},
    }
    source.profile_docs["test"] = {k: yaml.safe_dump({"schema_version": 1, **v}) for k, v in docs.items()}
    scenario = {
        "schema_version": 1,
        "horizon": horizon or {"start_year": 2026, "end_year": 2028},
        "market": market or {"preset": "flat"},
        "macro": macro or {"salary_growth": {"real_growth_rate": 0.0}},
        "levers": levers or {},
    }
    source.scenario_docs["test"] = {"s": yaml.safe_dump(scenario)}
    return load_simulation_input(source, "test", "s")


def run(**kwargs) -> SimulationResult:
    return simulate(build(**kwargs))


def moves(result: SimulationResult, year: int, source: str | None = None, dest: str | None = None) -> float:
    """Total amount moved in `year` matching the given endpoints (prefix match on `spending:` etc. via startswith)."""
    return sum(
        t.amount
        for t in result.transactions
        if t.year == year
        and (source is None or t.source == source or (source.endswith(":") and t.source.startswith(source)))
        and (dest is None or t.dest == dest or (dest.endswith(":") and t.dest.startswith(dest)))
    )
