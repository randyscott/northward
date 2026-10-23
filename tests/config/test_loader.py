"""End-to-end loading through ConfigSource, including cross-document validation."""

import pytest
import yaml

from northward.config.base import ConfigError
from northward.config.loader import load_rules, load_simulation_input, validate_all
from northward.config.source import PROFILE_KIND_DESCRIPTIONS, PROFILE_KINDS, FileSource, MemorySource
from tests.conftest import DATA_DIR


@pytest.fixture
def source() -> MemorySource:
    return MemorySource.copy_of(FileSource(DATA_DIR))


def edit(source: MemorySource, kind: str, change, profile: str = "example") -> None:
    """Apply `change(data)` to a profile document (or a rules document when profile is None)."""
    docs = source.rules if profile is None else source.profile_docs[profile]
    data = yaml.safe_load(docs[kind])
    change(data)
    docs[kind] = yaml.safe_dump(data)


def edit_scenario(source: MemorySource, change, name: str = "base") -> None:
    data = yaml.safe_load(source.scenario_docs["example"][name])
    change(data)
    source.scenario_docs["example"][name] = yaml.safe_dump(data)


def issues(source, profile="example", scenario="base") -> list[str]:
    with pytest.raises(ConfigError) as info:
        load_simulation_input(source, profile, scenario)
    return [str(i) for i in info.value.issues]


def test_every_committed_profile_and_scenario_is_valid():
    assert validate_all(FileSource(DATA_DIR)) == []


def test_example_loads_completely(source):
    sim = load_simulation_input(source, "example", "base")
    assert sim.profile.household.dependent("riley") is not None
    assert {a.id for a in sim.profile.accounts} >= {"alex_401k", "sam_529", "joint_brokerage"}
    assert sim.market.id == "forward_conservative"
    assert sim.rules.federal_tax.metadata.base_year == 2026


def test_scenario_overrides_patch_profile_and_market(source):
    sim = load_simulation_input(source, "example", "early_retire_roth_fill")
    assert sim.profile.household.member("alex").target_retirement_age == 58
    assert sim.profile.spending.base.amount == 80000
    assert sim.market.factors["stocks"].mean == 0.065
    # the base scenario is unaffected
    assert load_simulation_input(source, "example", "base").profile.household.member("alex").target_retirement_age == 62


def test_unknown_account_owner(source):
    edit(source, "accounts", lambda d: d["accounts"][1].update(owner="casey"))
    assert issues(source) == ["profiles/example/accounts.yaml: accounts[alex_roth_ira].owner: unknown member 'casey'"]


def test_joint_ira_is_rejected(source):
    edit(source, "accounts", lambda d: d["accounts"][1].update(owner="joint"))
    assert issues(source) == [
        "profiles/example/accounts.yaml: accounts[alex_roth_ira].owner: roth_ira accounts must be owned by one member, not joint"
    ]


def test_allocation_weights_must_sum_to_one(source):
    edit(source, "accounts", lambda d: d["accounts"][5]["asset_strategy"].update(cash=0.2))
    assert issues(source) == [
        "profiles/example/accounts.yaml: accounts[joint_brokerage].asset_strategy: stocks + bonds + cash must equal 1 (got 1.15)"
    ]


def test_missing_bracket_table(source):
    edit(
        source,
        "federal_tax",
        lambda d: d["ordinary_income_brackets"]["schedules"].pop("head_of_household"),
        profile=None,
    )
    assert issues(source) == [
        "rules/federal_tax.yaml: ordinary_income_brackets.schedules.head_of_household: Field required"
    ]


def test_unknown_glide_path(source):
    edit(source, "accounts", lambda d: d["accounts"][0]["asset_strategy"].update(glide_path="aggressive"))
    assert issues(source) == [
        "profiles/example/accounts.yaml: accounts[alex_401k].asset_strategy.glide_path: unknown glide path 'aggressive'"
    ]


def test_unknown_529_beneficiary(source):
    edit(source, "accounts", lambda d: d["accounts"][8].update(beneficiary="pat"))
    assert issues(source) == [
        "profiles/example/accounts.yaml: accounts[sam_529].beneficiary: unknown dependent or member 'pat'"
    ]


def test_spending_anchor_references(source):
    def change(d):
        d["spending"]["categories"][0]["end"] = {"dependent": "alex", "age": 17}
        d["spending"]["base"]["phases"]["reference"] = "sam"

    edit(source, "spending", change)
    assert issues(source) == [
        "profiles/example/spending.yaml: spending.base.phases.reference: unknown member 'sam'",
        "profiles/example/spending.yaml: spending.categories[sam_household].end: unknown dependent 'alex'",
    ]


def test_spending_window_must_not_end_before_it_starts(source):
    edit(source, "spending", lambda d: d["spending"]["categories"][3].update(end={"dependent": "sam", "age": 16}))
    assert issues(source) == [
        "profiles/example/spending.yaml: spending.categories[sam_college]: ends (2028) before it starts (2030)"
    ]


def test_fsa_elections_over_the_limit(source):
    edit(source, "income", lambda d: d["income_streams"][0].update(elections={"dependent_care_fsa": {"annual": 5000}}))
    [message] = issues(source)
    assert "dependent-care FSA elections total 10,000, over the" in message


def salary_elections(source, name, change):
    def apply(d):
        stream = next(s for s in d["income_streams"] if s["id"] == name)
        change(stream["elections"])

    edit(source, "income", apply)


def test_payroll_elections_load(source):
    sim = load_simulation_input(source, "example", "base")
    jordan = next(s for s in sim.profile.income.income_streams if s.id == "jordan_salary")
    assert [d.account for d in jordan.elections.retirement_deferrals] == ["jordan_roth_401k", "jordan_401k"]
    assert jordan.elections.hsa.coverage == "family"


def test_deferral_into_another_members_account(source):
    salary_elections(source, "alex_salary", lambda e: e["retirement_deferrals"][0].update(account="jordan_401k"))
    assert issues(source) == [
        "profiles/example/income.yaml: income_streams[alex_salary].elections.retirement_deferrals[0].account: "
        "account 'jordan_401k' belongs to jordan, not alex"
    ]


def test_deferral_into_wrong_account_type(source):
    salary_elections(source, "alex_salary", lambda e: e["retirement_deferrals"][0].update(account="alex_roth_ira"))
    assert issues(source) == [
        "profiles/example/income.yaml: income_streams[alex_salary].elections.retirement_deferrals[0].account: "
        "roth_ira accounts can't receive elective deferral contributions"
    ]


def test_traditional_catch_up_requires_a_roth_catch_up_account(source):
    salary_elections(source, "alex_salary", lambda e: e["retirement_deferrals"][0].update(include_catch_up=True))
    [message] = issues(source)
    assert "need a roth_catch_up_account" in message


def test_roth_catch_up_account_must_be_roth(source):
    salary_elections(
        source,
        "jordan_salary",
        lambda e: e["retirement_deferrals"][1].update(include_catch_up=True, roth_catch_up_account="jordan_401k"),
    )
    [message] = issues(source)
    assert message.endswith("roth_catch_up_account: account 'jordan_401k' must be a roth account")


def test_hsa_election_must_target_an_hsa(source):
    salary_elections(source, "jordan_salary", lambda e: e["hsa"].update(account="jordan_401k"))
    [message] = issues(source)
    assert message.endswith("hsa.account: traditional_401k accounts can't receive hsa contributions")


def test_event_references(source):
    def change(d):
        d["events"][0].update(beneficiary="casey")
        d["events"][1].update(pay_off="boat_loan")

    edit(source, "events", change)
    assert issues(source) == [
        "profiles/example/events.yaml: events[parents_ira].beneficiary: unknown member 'casey'",
        "profiles/example/events.yaml: events[condo_sale].pay_off: unknown liability 'boat_loan'",
    ]


def test_inherited_account_id_must_be_new(source):
    edit(source, "events", lambda d: d["events"][0].update(account="alex_401k"))
    assert issues(source) == [
        "profiles/example/events.yaml: events[parents_ira].account: account id 'alex_401k' already exists"
    ]


def test_conversion_pairs_must_be_traditional_to_roth_of_one_owner(source):
    pairs = [{"source": "jordan_roth_401k", "target": "alex_roth_ira"}]
    edit_scenario(source, lambda d: d["levers"]["roth_conversions"].update(pairs=pairs), name="early_retire_roth_fill")
    messages = issues(source, scenario="early_retire_roth_fill")
    assert (
        "levers.roth_conversions.pairs[0].source: 'jordan_roth_401k' must be a deferred retirement account"
        in messages[0]
    )
    assert messages[1].endswith("belong to different members")


def test_payroll_accounts_cant_take_scenario_contributions(source):
    edit_scenario(source, lambda d: d["levers"]["contributions"][0].update(account="jordan_hsa"))
    [message] = issues(source)
    assert message.endswith("hsa contributions are payroll elections on a salary")


def test_mortality_relocation_and_residence_references(source):
    def change(d):
        d["levers"]["mortality"] = {"kind": "fixed", "death_ages": {"casey": 80}}
        d["levers"]["relocations"] = [{"when": {"year": 2030}, "state": "XX"}]

    edit_scenario(source, change)
    assert issues(source) == [
        "profiles/example/scenarios/base.yaml: levers.mortality.death_ages.casey: unknown member 'casey'",
        "profiles/example/scenarios/base.yaml: levers.relocations[0].state: no state tax rules for 'XX'",
    ]
    edit(source, "household", lambda d: d["household"].update(state="ZZ"))
    edit_scenario(source, lambda d: d["levers"].pop("relocations"))
    messages = issues(source)
    assert any("the household's state 'ZZ' has no rules" in m for m in messages)


def test_health_costs_override_the_rule_defaults(source):
    source.profile_docs["example"]["health_costs"] = "schema_version: 1\nsupplement_premium: 3000\n"
    costs = load_simulation_input(source, "example", "base").profile.health_costs
    assert costs.supplement_premium == 3000
    assert costs.part_d_premium == 420  # still the rules' default


def test_scenario_references(source):
    def change(d):
        d["levers"]["ss_claim_ages"]["casey"] = 67
        d["levers"]["contributions"][0]["account"] = "nope"

    edit_scenario(source, change)
    assert issues(source) == [
        "profiles/example/scenarios/base.yaml: levers.ss_claim_ages.casey: unknown member 'casey'",
        "profiles/example/scenarios/base.yaml: levers.contributions[0].account: unknown account 'nope'",
    ]


def test_bad_override_path(source):
    edit_scenario(source, lambda d: d.update(overrides={"household": {"members.casey.target_retirement_age": 60}}))
    assert issues(source) == [
        "profiles/example/household.yaml: override 'members.casey.target_retirement_age': no item 'casey' in members "
        "(from scenario overrides)"
    ]


def test_override_producing_invalid_value_is_reported_against_the_profile_document(source):
    edit_scenario(source, lambda d: d.update(overrides={"accounts": {"accounts.joint_savings.balance": -5}}))
    assert issues(source) == [
        "profiles/example/accounts.yaml: accounts[joint_savings].balance: Input should be greater than or equal to 0"
    ]


def test_unknown_market_preset(source):
    edit_scenario(source, lambda d: d["market"].update(preset="rosy"))
    [message] = issues(source)
    assert message.startswith("profiles/example/scenarios/base.yaml: market.preset: unknown preset 'rosy'")


def test_invalid_market_override(source):
    edit_scenario(source, lambda d: d["market"].update(overrides={"factors.stocks.std_dev": -1}))
    [message] = issues(source)
    assert "market.overrides (applied).factors.stocks.std_dev" in message


def test_multiple_problems_are_reported_together(source):
    edit(source, "accounts", lambda d: d["accounts"][0].update(owner="casey", balance=-1))
    edit(source, "household", lambda d: d["members"][1].update(birth_month=13))
    messages = issues(source)
    assert len(messages) == 2
    assert any("birth_month" in m for m in messages) and any("balance" in m for m in messages)


def test_invalid_yaml_is_reported(source):
    source.profile_docs["example"]["income"] = "income_streams: [unclosed"
    [message] = issues(source)
    assert message.startswith("profiles/example/income.yaml: invalid YAML")


def test_missing_required_document(source):
    del source.profile_docs["example"]["spending"]
    assert issues(source) == ["profiles/example/spending.yaml: required profile document is missing"]


def test_optional_documents_default_to_empty(source):
    del source.profile_docs["example"]["liabilities"]
    assert load_simulation_input(source, "example", "base").profile.liabilities.liabilities == ()


def test_unknown_scenario(source):
    with pytest.raises(ConfigError, match="scenario not found"):
        load_simulation_input(source, "example", "nope")


def test_file_source_holds_one_rule_set_named_for_its_tax_year():
    assert load_rules(FileSource(DATA_DIR), "2026") == load_rules(FileSource(DATA_DIR))
    with pytest.raises(ConfigError, match="unknown rule set '2025' \\(data/rules holds '2026'\\)") as info:
        load_rules(FileSource(DATA_DIR), "2025")
    assert len(info.value.issues) == 1


def test_every_profile_kind_has_a_description():
    assert list(PROFILE_KIND_DESCRIPTIONS) == list(PROFILE_KINDS)
