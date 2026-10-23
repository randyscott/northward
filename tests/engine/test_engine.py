"""End-to-end simulation tests."""

import math

import pytest

from northward.config.loader import iter_all, load_simulation_input
from northward.config.source import FileSource
from northward.engine.simulate import simulate
from northward.engine.timeline import age_point
from northward.ledger.transaction import CASH
from tests.conftest import DATA_DIR
from tests.engine.helpers import FLAT_PRESET, STOCKS, member, moves, run

CENT = 0.005


def test_hand_computed_three_years():
    """Single filer, $100k salary with a 10% traditional 401(k) deferral, a 2% savings account, $50k spending,
    stocks at 5%, zero inflation. Every figure below is computed by hand from the 2026 federal rules."""
    result = run(
        members=[member()],
        accounts=[
            {"id": "savings", "owner": "pat", "type": "savings", "balance": 10000, "interest_rate": 0.02},
            {"id": "k401", "owner": "pat", "type": "traditional_401k", "balance": 50000, "asset_strategy": STOCKS},
        ],
        income=[
            {
                "id": "job",
                "owner": "pat",
                "type": "salary",
                "amount": 100000,
                "elections": {"retirement_deferrals": [{"account": "k401", "percent": 0.10}]},
            }
        ],
        spending=50000,
    )

    savings, k401 = 10000.0, 50000.0
    for state in result.years:
        interest = savings * 0.02
        ordinary_taxable = (100000 - 10000) + interest - 16100  # single standard deduction
        income_tax = 12400 * 0.10 + (50400 - 12400) * 0.12 + (ordinary_taxable - 50400) * 0.22
        fica = 100000 * 0.062 + 100000 * 0.0145
        surplus = 100000 - 10000 - 50000 - income_tax - fica
        savings += interest + surplus  # the only cash account receives the sweep
        k401 = (k401 + 10000) * 1.05

        flows = state.flows
        assert flows.taxes.income_tax == pytest.approx(income_tax, abs=CENT)
        assert flows.taxes.social_security_tax + flows.taxes.medicare_tax == pytest.approx(fica, abs=CENT)
        assert flows.swept == pytest.approx(surplus, abs=CENT)
        assert state.balances["savings"] == pytest.approx(savings, abs=CENT)
        assert state.balances["k401"] == pytest.approx(k401, abs=CENT)
        assert state.cash == pytest.approx(0, abs=CENT)
    assert result.years[0].flows.taxes.income_tax == pytest.approx(11014.00, abs=CENT)
    assert result.years[-1].balances["savings"] == pytest.approx(75621.13, abs=CENT)


def two_earner_couple(**overrides):
    """Both max their 401(k)s and HSAs; member a (born July 1976) also maxes catch-ups, which must be Roth because
    prior-year wages exceed $150,000."""
    salaries = [
        {
            "id": "a_job",
            "owner": "a",
            "type": "salary",
            "amount": 160000,
            "elections": {
                "retirement_deferrals": [
                    {"account": "a_401k", "max": True, "include_catch_up": True, "roth_catch_up_account": "a_roth"}
                ],
                "employer_match": {"account": "a_401k", "tiers": [{"match": 1.0, "up_to": 0.06}]},
                "hsa": {"account": "a_hsa", "coverage": "self_only", "max": True, "employer": 500},
            },
        },
        {
            "id": "b_job",
            "owner": "b",
            "type": "salary",
            "amount": 120000,
            "elections": {
                "retirement_deferrals": [{"account": "b_roth", "max": True}],
                "employer_match": {"account": "b_401k", "tiers": [{"match": 1.0, "up_to": 0.06}]},
                "hsa": {"account": "b_hsa", "coverage": "self_only", "max": True},
            },
        },
    ]
    accounts = [
        {"id": f"{p}_{kind}", "owner": p, "type": t, "balance": 1000, "asset_strategy": STOCKS}
        for p in "ab"
        for kind, t in (("401k", "traditional_401k"), ("roth", "roth_401k"), ("hsa", "hsa"))
    ] + [
        {
            "id": "brokerage",
            "owner": "joint",
            "type": "brokerage",
            "balance": 1000,
            "cost_basis": 1000,
            "asset_strategy": STOCKS,
        }
    ]
    args = dict(
        members=[member("a", 1976, 7, 65), member("b", 1983, 9, 65)],
        accounts=accounts,
        income=salaries,
        spending=100000,
        horizon={"start_year": 2026, "end_year": 2042},
        market={"preset": "flat"},
        preset={
            "factors": {**FLAT_PRESET["factors"], "inflation": {"mean": 0.025, "std_dev": 0, "distribution": "normal"}}
        },
    )
    args.update(overrides)
    return run(**args)


def test_2026_contributions_hit_the_published_limits():
    result = two_earner_couple()
    assert moves(result, 2026, CASH, "a_401k") == 24500  # traditional deferral
    assert moves(result, 2026, CASH, "a_roth") == 8000  # catch-up, Roth by rule
    assert moves(result, 2026, CASH, "b_roth") == 24500
    assert moves(result, 2026, CASH, "a_hsa") + moves(result, 2026, "employer", "a_hsa") == 4400
    assert moves(result, 2026, "employer", "a_hsa") == 500
    assert moves(result, 2026, CASH, "b_hsa") == 4400
    assert moves(result, 2026, "employer", "a_401k") == pytest.approx(0.06 * 160000)
    assert moves(result, 2026, "employer", "b_401k") == pytest.approx(0.06 * 120000)


def test_catch_up_is_larger_in_the_years_a_member_turns_60_to_63():
    result = two_earner_couple()

    def indexed(amount, year):
        return math.floor(amount * 1.025 ** (year - 2026) / 500) * 500

    assert moves(result, 2035, CASH, "a_roth") == indexed(8000, 2035)  # turns 59
    for year in range(2036, 2040):  # turns 60-63
        assert moves(result, year, CASH, "a_roth") == indexed(11250, year)
    assert moves(result, 2040, CASH, "a_roth") == indexed(8000, 2040)  # turns 64


def test_retirement_year_is_prorated_by_birth_month():
    result = two_earner_couple()
    # Member a (born July) retires at 65 in 2041: paid January-June.
    salary_2040 = 160000 * 1.025**14
    assert moves(result, 2041, "salary:a_job", CASH) == pytest.approx(160000 * 1.025**15 * 6 / 12)
    assert moves(result, 2040, "salary:a_job", CASH) == pytest.approx(salary_2040)
    assert moves(result, 2042, "salary:a_job", CASH) == 0
    limit_2041 = math.floor(24500 * 1.025**15 / 500) * 500
    assert moves(result, 2041, CASH, "a_401k") == pytest.approx(limit_2041 * 6 / 12)


def test_catch_up_stays_traditional_below_the_roth_wage_threshold():
    result = two_earner_couple()
    low = two_earner_couple(
        income=[
            {
                "id": "a_job",
                "owner": "a",
                "type": "salary",
                "amount": 120000,
                "elections": {
                    "retirement_deferrals": [
                        {"account": "a_401k", "max": True, "include_catch_up": True, "roth_catch_up_account": "a_roth"}
                    ]
                },
            }
        ]
    )
    assert moves(result, 2026, CASH, "a_roth") == 8000
    assert moves(low, 2026, CASH, "a_roth") == 0
    assert moves(low, 2026, CASH, "a_401k") == 24500 + 8000


def committed_runs():
    source = FileSource(DATA_DIR)
    return [(p, s, simulate(load_simulation_input(source, p, s))) for p, s in iter_all(source)]


@pytest.mark.parametrize(
    ("profile", "scenario", "result"), committed_runs(), ids=lambda v: v if isinstance(v, str) else ""
)
def test_committed_scenarios_run_to_the_horizon(profile, scenario, result):
    sim = load_simulation_input(FileSource(DATA_DIR), profile, scenario)
    assert result.years[0].year == sim.scenario.horizon.start_year
    members = sim.profile.household.members
    if len(result.death_ages) == len(members):  # everyone dies: the run ends with the last death
        last = max(age_point(m, result.death_ages[m.id]).year for m in members)
        assert result.years[-1].year == last
    else:
        assert min(result.years[-1].ages.values()) == sim.scenario.horizon.end_age  # the youngest member reaches it
    for state in result.years:
        assert all(balance >= -CENT for balance in state.balances.values()), state.year
        assert state.cash >= -CENT


@pytest.mark.parametrize(
    ("profile", "scenario", "result"), committed_runs(), ids=lambda v: v if isinstance(v, str) else ""
)
def test_value_is_conserved(profile, scenario, result):
    """Each year, the change in total assets equals external inflows minus external outflows."""
    internal = {CASH, *result.starting_balances, *result.years[-1].balances}  # incl. accounts opened later
    previous = sum(result.starting_balances.values())
    for state in result.years:
        net = 0.0
        for t in result.transactions:
            if t.year != state.year:
                continue
            if t.source not in internal and t.dest in internal:
                net += t.amount
            elif t.source in internal and t.dest not in internal:
                net -= t.amount
        assert state.total_assets - previous == pytest.approx(net, abs=0.01), state.year
        previous = state.total_assets


def retiree(**overrides):
    args = dict(
        members=[member(birth_year=1955, retire=60)],
        accounts=[
            {"id": "ira", "owner": "pat", "type": "traditional_ira", "balance": 500000, "asset_strategy": STOCKS}
        ],
        spending=60000,
    )
    args.update(overrides)
    return run(**args)


def test_withdrawals_to_pay_tax_are_taxed_too():
    """Spending from a traditional IRA alone: the withdrawal must cover spending plus the tax on the withdrawal."""
    result = retiree()
    year = result.years[0]
    withdrawn = year.flows.withdrawals["deferred"]
    assert withdrawn == pytest.approx(60000 + year.flows.total_taxes, abs=0.01)
    assert year.flows.taxes.ordinary_income == pytest.approx(withdrawn, abs=0.01)
    assert year.flows.shortfall == 0 and year.cash == pytest.approx(0, abs=CENT)
    assert result.warnings == ()


def test_early_withdrawals_pay_the_additional_tax_or_are_blocked():
    young = [member(birth_year=1980, retire=40)]
    accounts = [
        {"id": "ira", "owner": "pat", "type": "traditional_ira", "balance": 200000, "asset_strategy": STOCKS},
        {"id": "roth", "owner": "pat", "type": "roth_ira", "balance": 200000, "asset_strategy": STOCKS},
    ]
    penalized = run(members=young, accounts=accounts, spending=30000)
    flows = penalized.years[0].flows
    assert flows.taxes.additional_taxes == pytest.approx(0.10 * flows.withdrawals["deferred"], abs=0.01)

    blocked = run(members=young, accounts=accounts, spending=30000, levers={"early_withdrawals": "block"})
    flows = blocked.years[0].flows
    assert flows.withdrawals.get("deferred", 0) == 0
    assert flows.withdrawals["roth"] == pytest.approx(30000)
    assert flows.total_taxes == 0


def test_taxable_accounts_spend_cash_before_selling_and_realize_gains_at_average_cost():
    result = retiree(
        accounts=[
            {
                "id": "brokerage",
                "owner": "pat",
                "type": "brokerage",
                "balance": 100000,
                "cost_basis": 40000,
                "asset_strategy": STOCKS,
            },
            {"id": "checking", "owner": "pat", "type": "checking", "balance": 10000},
        ],
        spending=30000,
        horizon={"start_year": 2026, "end_year": 2026},
    )
    assert moves(result, 2026, "checking", CASH) == pytest.approx(10000 + 10000 * 0.02)  # its interest too
    sold = moves(result, 2026, "brokerage", CASH)
    assert result.years[0].flows.realized_gains == pytest.approx(sold * 0.60)  # 40% basis


def test_shortfall_when_accounts_run_out():
    result = retiree(
        accounts=[{"id": "checking", "owner": "pat", "type": "checking", "balance": 50000}],
        spending=40000,
    )
    shortfalls = [y.flows.shortfall for y in result.years]
    assert shortfalls[0] == 0 and shortfalls[1] > 0
    assert any("couldn't be funded" in w for w in result.warnings)


def test_surplus_fills_a_reserve_before_the_brokerage():
    result = run(
        members=[member()],
        accounts=[
            {"id": "reserve", "owner": "pat", "type": "savings", "balance": 5000, "interest_rate": 0.0},
            {
                "id": "brokerage",
                "owner": "pat",
                "type": "brokerage",
                "balance": 0,
                "cost_basis": 0,
                "asset_strategy": STOCKS,
            },
        ],
        income=[{"id": "job", "owner": "pat", "type": "salary", "amount": 100000}],
        spending=40000,
        levers={"surplus_sweep": [{"account": "reserve", "up_to_balance": 20000}, {"account": "brokerage"}]},
    )
    assert moves(result, 2026, CASH, "reserve") == pytest.approx(15000)
    assert moves(result, 2027, CASH, "reserve") == 0
    assert result.years[0].balances["reserve"] == pytest.approx(20000)


def test_dependent_care_fsa_is_reimbursed_or_forfeited():
    kid = {"id": "kid", "name": "Kid", "birth_year": 2018, "birth_month": 6}
    common = dict(
        members=[member()],
        dependents=[kid],
        accounts=[{"id": "checking", "owner": "pat", "type": "checking", "balance": 10000}],
        income=[
            {
                "id": "job",
                "owner": "pat",
                "type": "salary",
                "amount": 100000,
                "elections": {"dependent_care_fsa": {"annual": 5000}},
            }
        ],
    )
    care = {"base": {"amount": 40000}, "categories": [{"id": "care", "amount": 3000, "tags": ["dependent_care"]}]}
    result = run(**common, spending=care)
    flows = result.years[0].flows
    assert (flows.fsa_reimbursed, flows.fsa_forfeited) == (3000, 2000)
    assert result.years[0].flows.taxes.ordinary_income == pytest.approx(100000 - 5000 + 10000 * 0.02, abs=0.01)
    assert any("FSA" in w for w in result.warnings)
    # Riley-style age cutoff: no election once the child is 13 (2031 for a 2018 birth).
    later = run(**common, spending=care, horizon={"start_year": 2030, "end_year": 2031})
    assert [y.flows.fsa_elections for y in later.years] == [5000, 0]
