import pytest
import yaml

from northward.config.base import ConfigError
from northward.config.loader import load_simulation_input
from northward.config.source import FileSource, MemorySource
from northward.engine.simulate import simulate
from northward.ledger.transaction import CASH
from northward.montecarlo.runner import run_monte_carlo
from northward.montecarlo.stats import evaluate_success
from tests.conftest import DATA_DIR
from tests.engine.helpers import FLAT_PRESET, STOCKS, build, member, moves, run

RETIREE = member(birth_year=1960, retire=60)  # 66 in 2026: retired, past every early-withdrawal penalty age
ORDER = ["taxable", "roth", "deferred", "hsa"]


def accounts(savings: float, brokerage: float, roth: float = 0.0) -> list[dict]:
    found = [
        {"id": "savings", "owner": "pat", "type": "savings", "balance": savings, "interest_rate": 0.0},
        {
            "id": "brokerage",
            "owner": "pat",
            "type": "brokerage",
            "balance": brokerage,
            "cost_basis": brokerage,
            "asset_strategy": STOCKS,
        },
    ]
    if roth:
        found.append({"id": "roth", "owner": "pat", "type": "roth_ira", "balance": roth, "asset_strategy": STOCKS})
    return found


def reserve(amount: float = 50000) -> dict:
    return {"withdrawal_order": ORDER, "cash_reserve": {"account": "savings", "amount": amount}}


def test_the_reserve_stays_while_other_accounts_pay():
    kept = run(members=[RETIREE], accounts=accounts(50000, 40000, 100000), spending=30000, levers=reserve())
    assert [y.balances["savings"] for y in kept.years] == pytest.approx([50000, 50000, 50000])
    assert moves(kept, 2026, "brokerage", CASH) == pytest.approx(30000)
    assert moves(kept, 2027, "roth", CASH) > 0  # the Roth is used before the reserve
    assert all(y.flows.reserve_drawn == 0 for y in kept.years)

    # Without the reserve, cash is spent before anything else in the taxable bucket.
    spent = run(
        members=[RETIREE], accounts=accounts(50000, 40000, 100000), spending=30000, levers={"withdrawal_order": ORDER}
    )
    assert spent.years[0].balances["savings"] == pytest.approx(20000)


def test_the_reserve_is_the_last_resort():
    result = run(
        members=[RETIREE],
        accounts=accounts(50000, 10000),
        spending=30000,
        levers=reserve(),
        horizon={"start_year": 2026, "end_year": 2027},
    )
    first, second = result.years
    assert moves(result, 2026, "brokerage", CASH) == pytest.approx(10000)
    assert first.flows.reserve_drawn == pytest.approx(20000) and first.balances["savings"] == pytest.approx(30000)
    assert second.flows.reserve_drawn == pytest.approx(30000) and second.balances["savings"] == pytest.approx(0)
    assert first.flows.shortfall == second.flows.shortfall == 0
    assert any("cash reserve in savings was drawn on in 2 year(s) from 2026" in w for w in result.warnings)


def test_surplus_refills_the_reserve_first():
    rent = {"id": "rent", "owner": "pat", "type": "other", "description": "rent", "amount": 60000}
    result = run(
        members=[RETIREE],
        accounts=accounts(20000, 0),
        income=[rent],
        spending=10000,
        levers=reserve(),
        horizon={"start_year": 2026, "end_year": 2026},
    )
    assert moves(result, 2026, CASH, "savings") == pytest.approx(30000)
    assert result.years[0].balances["savings"] == pytest.approx(50000)
    assert moves(result, 2026, CASH, "brokerage") > 0  # the rest goes to the usual sweep target


def test_the_reserve_is_in_todays_dollars():
    inflating = {**FLAT_PRESET["factors"], "inflation": {"mean": 0.03, "std_dev": 0.0, "distribution": "normal"}}
    result = run(
        members=[RETIREE],
        accounts=accounts(51000, 0, 200000),
        spending=30000,
        levers=reserve(),
        preset={"factors": inflating},
        horizon={"start_year": 2026, "end_year": 2027},
    )
    assert moves(result, 2026, "savings", CASH) == pytest.approx(1000)  # only what's above 50,000
    assert moves(result, 2027, "savings", CASH) == 0  # the reserve is now 51,500...
    assert result.years[1].flows.reserve_topped_up == pytest.approx(1500)  # ...so it's topped up from the Roth
    assert result.years[1].balances["savings"] == pytest.approx(51500)


@pytest.mark.parametrize(
    ("account", "message"),
    [
        ("nope", "unknown account 'nope'"),
        ("roth", "the cash reserve must be a cash or brokerage account, not roth_ira"),
    ],
)
def test_the_reserve_account_is_checked(account, message):
    with pytest.raises(ConfigError, match=message):
        build(
            members=[RETIREE],
            accounts=accounts(1000, 1000, 1000),
            levers={"cash_reserve": {"account": account, "amount": 1}},
        )


def test_no_reserve_means_no_change():
    sim = build(
        members=[RETIREE], accounts=accounts(50000, 40000, 100000), spending=30000, levers={"withdrawal_order": ORDER}
    )
    assert sim.scenario.levers.cash_reserve is None
    assert all(y.flows.reserve_drawn == 0 for y in simulate(sim).years)


def test_a_short_reserve_is_topped_up_from_the_other_accounts():
    result = run(
        members=[RETIREE],
        accounts=accounts(20000, 100000),
        spending=30000,
        levers=reserve(),
        horizon={"start_year": 2026, "end_year": 2026},
    )
    assert result.years[0].flows.reserve_topped_up == pytest.approx(30000)
    assert result.years[0].balances["savings"] == pytest.approx(50000)
    assert moves(result, 2026, "brokerage", CASH) == pytest.approx(60000)  # the year's spending, then the top-up


def test_spending_comes_before_topping_up():
    result = run(
        members=[RETIREE],
        accounts=accounts(40000, 15000),
        spending=30000,
        levers=reserve(),
        horizon={"start_year": 2026, "end_year": 2026},
    )
    year = result.years[0]
    assert year.flows.shortfall == 0 and year.flows.reserve_drawn == pytest.approx(15000)
    assert year.flows.reserve_topped_up == 0 and year.balances["savings"] == pytest.approx(25000)


def test_the_example_keeps_its_floor_with_a_reserve():
    """The example's early-retirement scenario spends taxable money first and pays its conversions' tax from it: without
    the reserve, nearly every path ends years below the $50k liquidity floor while the Roth is full."""
    source = MemorySource.copy_of(FileSource(DATA_DIR))
    doc = yaml.safe_load(source.scenario_docs["example"]["early_retire_roth_fill"])
    doc["levers"].pop("cash_reserve")
    source.scenario_docs["example"]["without"] = yaml.safe_dump(doc)
    success = {}
    for name in ("early_retire_roth_fill", "without"):
        sim = load_simulation_input(source, "example", name)
        success[name] = evaluate_success(run_monte_carlo(sim, 60, 1, workers=1), sim, sim.profile.goals).success.mean()
    assert success["early_retire_roth_fill"] > 0.9 > 0.5 > success["without"]
