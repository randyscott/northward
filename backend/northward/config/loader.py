"""Compose rules, a profile, and a scenario into one validated, immutable `SimulationInput`.

Every problem found (YAML syntax, schema, cross-references) is collected and raised together as a `ConfigError`.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Any, TypeVar

import yaml
from pydantic import BaseModel, ValidationError

from northward.config.accounts import Account, AccountsDoc, Plan529Account, TargetDateStrategy, parse_accounts
from northward.config.anchors import Anchor, DependentAgeAnchor, EventAnchor, YearAnchor, year_person_reaches_age
from northward.config.base import JOINT_OWNER, ConfigError, ConfigIssue, FilingStatus, issues_from_validation_error
from northward.config.events import Event, EventsDoc, HomeSaleEvent, WindfallEvent
from northward.config.goals import GoalsDoc
from northward.config.household import HouseholdDoc
from northward.config.income import IncomeDoc, OtherIncomeStream, PensionStream, SalaryStream
from northward.config.liabilities import InterestOnlyLoan, LiabilitiesDoc
from northward.config.overrides import OverrideError, apply_overrides
from northward.config.rules.account_types import (
    AccountFamily,
    AccountType,
    AccountTypesDoc,
    OwnershipConstraint,
    TaxWrapper,
)
from northward.config.rules.contribution_limits import ContributionLimitsDoc
from northward.config.rules.federal_tax import FederalTaxDoc
from northward.config.rules.glide_paths import GlidePathsDoc
from northward.config.rules.healthcare import HealthcareAssumptions, HealthcareDoc, HealthcareProfileDoc
from northward.config.rules.historical_returns import HistoricalReturnsDoc
from northward.config.rules.market import MarketAssumptionsDoc, MarketPreset, from_history
from northward.config.rules.mortality import MortalityDoc
from northward.config.rules.rmd import RmdDoc
from northward.config.rules.social_security import SocialSecurityDoc
from northward.config.rules.state_tax import StateTaxDoc
from northward.config.scenario import ScenarioDoc
from northward.config.source import (
    LATEST_RULE_SET,
    SCENARIO_KIND,
    ConfigSource,
    RawDocument,
    RecordingSource,
    SnapshotSource,
)
from northward.config.spending import Spending, SpendingDoc
from northward.config.versioning import upgrade_document

M = TypeVar("M", bound=BaseModel)


@dataclass(frozen=True)
class RuleSet:
    account_types: AccountTypesDoc
    federal_tax: FederalTaxDoc
    rmd: RmdDoc
    contribution_limits: ContributionLimitsDoc
    social_security: SocialSecurityDoc
    glide_paths: GlidePathsDoc
    market_assumptions: MarketAssumptionsDoc
    state_tax: StateTaxDoc
    healthcare: HealthcareDoc
    mortality: MortalityDoc
    historical_returns: HistoricalReturnsDoc


@dataclass(frozen=True)
class Profile:
    name: str
    household: HouseholdDoc
    accounts: tuple[Account, ...]
    income: IncomeDoc
    liabilities: LiabilitiesDoc
    spending: Spending
    events: tuple[Event, ...] = ()
    health_costs: HealthcareAssumptions | None = None  # the rules' defaults with the profile's overrides
    goals: GoalsDoc = GoalsDoc(schema_version=1)


@dataclass(frozen=True)
class SimulationInput:
    profile_name: str
    scenario_name: str
    rules: RuleSet
    profile: Profile
    scenario: ScenarioDoc
    market: MarketPreset  # the scenario's preset with its overrides applied
    # The documents this input was loaded from. Pickling reloads from them (the parsed models don't pickle).
    snapshot: SnapshotSource | None = dataclasses.field(default=None, compare=False, repr=False)

    def __reduce__(self) -> tuple[object, tuple[object, ...]]:
        if self.snapshot is None:
            raise TypeError("only a SimulationInput built by load_simulation_input can be pickled")
        return load_simulation_input, (self.snapshot, self.profile_name, self.scenario_name)

    @property
    def events(self) -> tuple[Event, ...]:
        """The profile's expected events plus the scenario's what-if events."""
        return self.profile.events + self.scenario.events


_RULE_MODELS: dict[str, type[BaseModel]] = {
    "account_types": AccountTypesDoc,
    "federal_tax": FederalTaxDoc,
    "rmd": RmdDoc,
    "contribution_limits": ContributionLimitsDoc,
    "social_security": SocialSecurityDoc,
    "glide_paths": GlidePathsDoc,
    "market_assumptions": MarketAssumptionsDoc,
    "state_tax": StateTaxDoc,
    "healthcare": HealthcareDoc,
    "mortality": MortalityDoc,
    "historical_returns": HistoricalReturnsDoc,
}
_PROFILE_MODELS: dict[str, type[BaseModel]] = {
    "household": HouseholdDoc,
    "accounts": AccountsDoc,
    "income": IncomeDoc,
    "liabilities": LiabilitiesDoc,
    "spending": SpendingDoc,
    "events": EventsDoc,
    "health_costs": HealthcareProfileDoc,
    "goals": GoalsDoc,
}
# Profile documents that may be omitted; they default to an empty document.
_OPTIONAL_PROFILE_DOCS = {"income", "liabilities", "events", "health_costs", "goals"}
REQUIRED_PROFILE_DOCS = tuple(kind for kind in _PROFILE_MODELS if kind not in _OPTIONAL_PROFILE_DOCS)


class _Collector:
    """Accumulates issues while loading so every problem is reported at once."""

    def __init__(self) -> None:
        self.issues: list[ConfigIssue] = []

    def add(self, origin: str, location: str, message: str) -> None:
        self.issues.append(ConfigIssue(origin, location, message))

    def parse(self, raw: RawDocument, kind: str, overrides: dict[str, Any] | None = None) -> Any | None:
        """YAML text -> upgraded, overridden plain data (or None, with issues recorded)."""
        try:
            data = yaml.safe_load(raw.text)
        except yaml.YAMLError as error:
            self.add(raw.origin, "", f"invalid YAML: {error}")
            return None
        if not isinstance(data, dict):
            self.add(raw.origin, "", "document must be a mapping at the top level")
            return None
        try:
            data = upgrade_document(kind, data)
        except ValueError as error:
            self.add(raw.origin, "schema_version", str(error))
            return None
        if overrides:
            try:
                data = apply_overrides(data, overrides)
            except OverrideError as error:
                self.add(raw.origin, "", f"{error} (from scenario overrides)")
                return None
        return data

    def validate(self, model: type[M], data: Any, origin: str) -> M | None:
        try:
            return model.model_validate(data)
        except ValidationError as error:
            self.issues.extend(issues_from_validation_error(error, origin, data))
            return None

    def raise_if_any(self) -> None:
        if self.issues:
            raise ConfigError(self.issues)


def document_model(kind: str) -> type[BaseModel] | None:
    """The Pydantic model of a document kind (a profile kind, "scenario", or a rule kind)."""
    return _RULE_MODELS.get(kind) or _PROFILE_MODELS.get(kind) or (ScenarioDoc if kind == SCENARIO_KIND else None)


def validate_document(kind: str, raw: RawDocument) -> list[ConfigIssue]:
    """Check one document on its own: YAML syntax, schema version, and its Pydantic model. Cross-references to
    other documents are checked by loading (`load_simulation_input`, `check_profile`)."""
    model = document_model(kind)
    if model is None:
        return [ConfigIssue(raw.origin, "", f"unknown document kind '{kind}'")]
    collector = _Collector()
    data = collector.parse(raw, kind)
    if data is not None:
        collector.validate(model, data, raw.origin)
    return collector.issues


def check_profile(source: ConfigSource, profile: str, rule_set: str = LATEST_RULE_SET) -> list[ConfigIssue]:
    """Every problem in a profile's own documents and their cross-references, without any scenario."""
    collector = _Collector()
    rules = _load_rules(source, rule_set, collector)
    _load_profile(source, profile, rules, {}, collector)
    return collector.issues


def load_rules(source: ConfigSource, rule_set: str = LATEST_RULE_SET) -> RuleSet:
    collector = _Collector()
    rules = _load_rules(source, rule_set, collector)
    collector.raise_if_any()
    assert rules is not None
    return rules


def load_simulation_input(source: ConfigSource, profile: str, scenario: str) -> SimulationInput:
    """Load and cross-validate everything a simulation of `profile` under `scenario` needs."""
    collector = _Collector()
    source = RecordingSource(source)

    scenario_raw = source.scenario_document(profile, scenario)
    if scenario_raw is None:
        raise ConfigError([ConfigIssue(f"profiles/{profile}/scenarios", scenario, "scenario not found")])
    scenario_data = collector.parse(scenario_raw, SCENARIO_KIND)
    scenario_doc = (
        None if scenario_data is None else collector.validate(ScenarioDoc, scenario_data, scenario_raw.origin)
    )
    collector.raise_if_any()
    assert scenario_doc is not None

    rules = _load_rules(source, scenario_doc.rule_set, collector)
    loaded_profile = _load_profile(source, profile, rules, scenario_doc.overrides, collector)
    collector.raise_if_any()
    assert rules is not None and loaded_profile is not None

    market = _resolve_market(rules, scenario_doc, scenario_raw.origin, collector)
    _check_scenario(scenario_doc, scenario_raw.origin, loaded_profile, rules, collector)
    _check_sweep(scenario_doc, scenario_raw.origin, loaded_profile, rules, collector)
    _check_conversions(scenario_doc, scenario_raw.origin, loaded_profile, rules, collector)
    _check_events(scenario_doc.events, loaded_profile, rules, scenario_raw.origin, "events", collector)
    collector.raise_if_any()
    assert market is not None

    return SimulationInput(profile, scenario, rules, loaded_profile, scenario_doc, market, source.snapshot())


def _load_rules(source: ConfigSource, rule_set: str, collector: _Collector) -> RuleSet | None:
    docs: dict[str, BaseModel] = {}
    for kind, model in _RULE_MODELS.items():
        try:
            raw = source.rules_document(kind, rule_set)
        except ValueError as error:  # the source doesn't hold this rule set at all
            collector.add("rules", "", str(error))
            return None
        if raw is None:
            collector.add(f"rules/{kind}.yaml", "", "required rules document is missing")
            continue
        data = collector.parse(raw, kind)
        doc = None if data is None else collector.validate(model, data, raw.origin)
        if doc is not None:
            docs[kind] = doc
    return RuleSet(**docs) if len(docs) == len(_RULE_MODELS) else None  # type: ignore[arg-type]


def _load_profile(
    source: ConfigSource,
    profile: str,
    rules: RuleSet | None,
    overrides: dict[str, dict[str, Any]],
    collector: _Collector,
) -> Profile | None:
    def load(kind: str, model: type[M]) -> tuple[M | None, str]:
        raw = source.profile_document(profile, kind)
        origin = f"profiles/{profile}/{kind}.yaml"
        if raw is None:
            if kind not in _OPTIONAL_PROFILE_DOCS:
                collector.add(origin, "", "required profile document is missing")
                return None, origin
            if kind in overrides:
                collector.add(origin, "", "scenario overrides a profile document that doesn't exist")
            return model.model_validate({"schema_version": 1}), origin
        data = collector.parse(raw, kind, overrides.get(kind))
        return (None if data is None else collector.validate(model, data, raw.origin)), raw.origin

    household, _ = load("household", HouseholdDoc)
    accounts_doc, accounts_origin = load("accounts", AccountsDoc)
    income, income_origin = load("income", IncomeDoc)
    liabilities, liabilities_origin = load("liabilities", LiabilitiesDoc)
    spending_doc, spending_origin = load("spending", SpendingDoc)
    events_doc, events_origin = load("events", EventsDoc)
    health_doc, _ = load("health_costs", HealthcareProfileDoc)
    goals, goals_origin = load("goals", GoalsDoc)

    accounts: tuple[Account, ...] | None = None
    if accounts_doc is not None and rules is not None:
        accounts, account_issues = parse_accounts(accounts_doc, rules.account_types, accounts_origin)
        collector.issues.extend(account_issues)
        if account_issues:
            accounts = None

    docs = (household, accounts, income, liabilities, spending_doc, events_doc, health_doc, goals)
    if None in docs or rules is None:
        return None
    assert household and accounts is not None and income and liabilities and spending_doc and events_doc and health_doc
    assert goals is not None
    overrides = health_doc.model_dump(exclude={"schema_version"}, exclude_none=True)
    health = rules.healthcare.default_assumptions.model_copy(update=overrides)
    loaded = Profile(
        profile, household, accounts, income, liabilities, spending_doc.spending, events_doc.events, health, goals
    )

    _check_accounts(loaded, rules, accounts_origin, collector)
    _check_income(loaded, rules, income_origin, collector)
    _check_liabilities(loaded, liabilities_origin, collector)
    _check_spending(loaded, spending_origin, collector)
    _check_events(loaded.events, loaded, rules, events_origin, "events", collector)
    floor = goals.success.liquidity_floor
    if floor is not None:
        _check_anchor(floor.start, household, goals_origin, "success.liquidity_floor.start", collector)
    return loaded


# --- cross-reference checks -----------------------------------------------------------------------------------


def _check_anchor(anchor: Anchor | None, household: HouseholdDoc, origin: str, location: str, c: _Collector) -> None:
    if anchor is None or isinstance(anchor, YearAnchor):
        return
    if isinstance(anchor, DependentAgeAnchor):
        if household.dependent(anchor.dependent) is None:
            c.add(origin, location, f"unknown dependent '{anchor.dependent}'")
    elif household.member(anchor.member) is None:
        c.add(origin, location, f"unknown member '{anchor.member}'")


def _static_year(anchor: Anchor | None, household: HouseholdDoc) -> int | None:
    """Calendar year for anchors that don't depend on simulated events (None for events or unknown people)."""
    if anchor is None or isinstance(anchor, EventAnchor):
        return None
    if isinstance(anchor, YearAnchor):
        return anchor.year
    if isinstance(anchor, DependentAgeAnchor):
        person = household.dependent(anchor.dependent)
    else:
        person = household.member(anchor.member)
    return None if person is None else year_person_reaches_age(person, anchor.age)


def _check_window(
    start: Anchor | None, end: Anchor | None, household: HouseholdDoc, origin: str, where: str, c: _Collector
) -> None:
    start_year, end_year = _static_year(start, household), _static_year(end, household)
    if start_year is not None and end_year is not None and end_year < start_year:
        c.add(origin, where, f"ends ({end_year}) before it starts ({start_year})")


def _check_accounts(profile: Profile, rules: RuleSet, origin: str, c: _Collector) -> None:
    household = profile.household
    for account in profile.accounts:
        where = f"accounts[{account.id}]"
        account_type = rules.account_types.get(account.type)
        assert account_type is not None  # parse_accounts already checked
        if account.owner == JOINT_OWNER:
            if account_type.ownership_constraint is OwnershipConstraint.INDIVIDUAL_ONLY:
                c.add(origin, f"{where}.owner", f"{account.type} accounts must be owned by one member, not joint")
        elif household.member(account.owner) is None:
            c.add(origin, f"{where}.owner", f"unknown member '{account.owner}'")
        strategy = getattr(account, "asset_strategy", None)
        if isinstance(strategy, TargetDateStrategy) and rules.glide_paths.get(strategy.glide_path) is None:
            c.add(origin, f"{where}.asset_strategy.glide_path", f"unknown glide path '{strategy.glide_path}'")
        if isinstance(account, Plan529Account):
            if household.dependent(account.beneficiary) is None and household.member(account.beneficiary) is None:
                c.add(origin, f"{where}.beneficiary", f"unknown dependent or member '{account.beneficiary}'")


def _check_income(profile: Profile, rules: RuleSet, origin: str, c: _Collector) -> None:
    household = profile.household
    fsa_total = 0.0
    max_deferral_owners: set[str] = set()  # the elective-deferral limit is per person across all employers
    for stream in profile.income.income_streams:
        where = f"income_streams[{stream.id}]"
        joint_ok = isinstance(stream, OtherIncomeStream)
        if not (household.member(stream.owner) or (joint_ok and stream.owner == JOINT_OWNER)):
            c.add(origin, f"{where}.owner", f"unknown member '{stream.owner}'")
        if isinstance(stream, SalaryStream):
            _check_anchor(stream.end, household, origin, f"{where}.end", c)
            _check_payroll_accounts(stream, profile, rules, origin, f"{where}.elections", c)
            if any(d.max for d in stream.elections.retirement_deferrals):
                if stream.owner in max_deferral_owners:
                    c.add(
                        origin,
                        f"{where}.elections",
                        f"{stream.owner} already has a max: true deferral on another salary",
                    )
                max_deferral_owners.add(stream.owner)
            fsa = stream.elections.dependent_care_fsa
            if fsa is not None:
                fsa_total += fsa.annual
                _check_anchor(fsa.until, household, origin, f"{where}.elections.dependent_care_fsa.until", c)
                if not household.dependents:
                    c.add(origin, f"{where}.elections.dependent_care_fsa", "the household has no dependents")
        elif isinstance(stream, PensionStream):
            _check_anchor(stream.start, household, origin, f"{where}.start", c)
        else:
            _check_anchor(stream.start, household, origin, f"{where}.start", c)
            _check_anchor(stream.end, household, origin, f"{where}.end", c)
            _check_window(stream.start, stream.end, household, origin, where, c)
    fsa_rules = rules.contribution_limits.dependent_care_fsa
    separate = household.household.filing_status is FilingStatus.MARRIED_FILING_SEPARATELY
    limit = fsa_rules.married_filing_separately_limit if separate else fsa_rules.household_limit
    if fsa_total > limit:
        c.add(
            origin,
            "income_streams",
            f"dependent-care FSA elections total {fsa_total:,.0f}, over the {limit:,.0f} limit",
        )


def _check_payroll_accounts(
    stream: SalaryStream, profile: Profile, rules: RuleSet, origin: str, where: str, c: _Collector
) -> None:
    """Each election's account must exist, belong to the salary's owner, and be the right kind of account."""
    accounts = {a.id: a for a in profile.accounts}

    def check(account_id: str, location: str, limit: str, wrapper: TaxWrapper | None = None) -> AccountType | None:
        account = accounts.get(account_id)
        if account is None:
            c.add(origin, location, f"unknown account '{account_id}'")
            return None
        if account.owner != stream.owner:
            c.add(origin, location, f"account '{account_id}' belongs to {account.owner}, not {stream.owner}")
        account_type = rules.account_types.get(account.type)
        if account_type is None:
            return None
        if account_type.contribution_limit != limit:
            c.add(origin, location, f"{account.type} accounts can't receive {limit.replace('_', ' ')} contributions")
        elif wrapper is not None and account_type.tax_wrapper is not wrapper:
            c.add(origin, location, f"account '{account_id}' must be a {wrapper.value} account")
        return account_type

    elections = stream.elections
    for index, deferral in enumerate(elections.retirement_deferrals):
        here = f"{where}.retirement_deferrals[{index}]"
        account_type = check(deferral.account, f"{here}.account", "elective_deferral")
        if deferral.roth_catch_up_account is not None:
            check(deferral.roth_catch_up_account, f"{here}.roth_catch_up_account", "elective_deferral", TaxWrapper.ROTH)
        elif deferral.include_catch_up and account_type is not None and account_type.tax_wrapper is TaxWrapper.DEFERRED:
            c.add(
                origin,
                here,
                "catch-ups into a traditional account need a roth_catch_up_account: from 2026, catch-ups must be Roth "
                "when prior-year wages exceed the SECURE 2.0 threshold",
            )
    if elections.employer_match is not None:
        check(elections.employer_match.account, f"{where}.employer_match.account", "elective_deferral")
    if elections.hsa is not None:
        check(elections.hsa.account, f"{where}.hsa.account", "hsa")


def _check_liabilities(profile: Profile, origin: str, c: _Collector) -> None:
    for liability in profile.liabilities.liabilities:
        if isinstance(liability, InterestOnlyLoan):
            _check_anchor(liability.payoff, profile.household, origin, f"liabilities[{liability.id}].payoff", c)


def _check_spending(profile: Profile, origin: str, c: _Collector) -> None:
    household, spending = profile.household, profile.spending
    if spending.base.phases is not None and household.member(spending.base.phases.reference) is None:
        c.add(origin, "spending.base.phases.reference", f"unknown member '{spending.base.phases.reference}'")
    for category in spending.categories:
        where = f"spending.categories[{category.id}]"
        for field in ("start", "end", "once"):
            _check_anchor(getattr(category, field), household, origin, f"{where}.{field}", c)
        _check_window(category.start, category.end, household, origin, where, c)
        if category.beneficiary is not None and not (
            household.dependent(category.beneficiary) or household.member(category.beneficiary)
        ):
            c.add(origin, f"{where}.beneficiary", f"unknown dependent or member '{category.beneficiary}'")


def _check_scenario(scenario: ScenarioDoc, origin: str, profile: Profile, rules: RuleSet, c: _Collector) -> None:
    household = profile.household
    for member_id in scenario.levers.ss_claim_ages:
        if household.member(member_id) is None:
            c.add(origin, f"levers.ss_claim_ages.{member_id}", f"unknown member '{member_id}'")
    for member_id in getattr(scenario.levers.mortality, "death_ages", {}):
        if household.member(member_id) is None:
            c.add(origin, f"levers.mortality.death_ages.{member_id}", f"unknown member '{member_id}'")
    for index, move in enumerate(scenario.levers.relocations):
        _check_anchor(move.when, household, origin, f"levers.relocations[{index}].when", c)
        if move.state not in rules.state_tax.states:
            c.add(origin, f"levers.relocations[{index}].state", f"no state tax rules for '{move.state}'")
    if household.household.state not in rules.state_tax.states:
        c.add(origin, "", f"the household's state '{household.household.state}' has no rules in rules/state_tax.yaml")
    accounts = {a.id: a for a in profile.accounts}
    for index, contribution in enumerate(scenario.levers.contributions):
        where = f"levers.contributions[{index}]"
        account = accounts.get(contribution.account)
        if account is None:
            c.add(origin, f"{where}.account", f"unknown account '{contribution.account}'")
        else:
            account_type = rules.account_types.get(account.type)
            if account_type is not None and not account_type.allows_contributions:
                c.add(origin, f"{where}.account", f"{account.type} accounts don't accept contributions")
            elif account_type is not None and account_type.contribution_limit in ("elective_deferral", "hsa"):
                c.add(origin, f"{where}.account", f"{account.type} contributions are payroll elections on a salary")
        _check_anchor(contribution.start, household, origin, f"{where}.start", c)
        _check_anchor(contribution.end, household, origin, f"{where}.end", c)
        _check_window(contribution.start, contribution.end, household, origin, where, c)


def _check_conversions(scenario: ScenarioDoc, origin: str, profile: Profile, rules: RuleSet, c: _Collector) -> None:
    pairs = getattr(scenario.levers.roth_conversions, "pairs", ())
    accounts = {a.id: a for a in profile.accounts}
    for index, pair in enumerate(pairs):
        where = f"levers.roth_conversions.pairs[{index}]"
        source, target = accounts.get(pair.source), accounts.get(pair.target)
        for field, account, wrapper in (("source", source, TaxWrapper.DEFERRED), ("target", target, TaxWrapper.ROTH)):
            name = getattr(pair, field)
            if account is None:
                c.add(origin, f"{where}.{field}", f"unknown account '{name}'")
                continue
            account_type = rules.account_types.get(account.type)
            if (
                account_type is None
                or account_type.family is not AccountFamily.RETIREMENT
                or account_type.tax_wrapper is not wrapper
            ):
                c.add(origin, f"{where}.{field}", f"'{name}' must be a {wrapper.value} retirement account")
        if source is not None and target is not None and source.owner != target.owner:
            c.add(origin, where, f"'{pair.source}' and '{pair.target}' belong to different members")


def _check_events(
    events: tuple[Event, ...], profile: Profile, rules: RuleSet, origin: str, prefix: str, c: _Collector
) -> None:
    household = profile.household
    accounts = {a.id: a for a in profile.accounts}
    liabilities = {liability.id for liability in profile.liabilities.liabilities}
    for event in events:
        where = f"{prefix}[{event.id}]"
        _check_anchor(event.when, household, origin, f"{where}.when", c)
        if isinstance(event, WindfallEvent):
            if event.owner is not None and household.member(event.owner) is None:
                c.add(origin, f"{where}.owner", f"unknown member '{event.owner}'")
            if event.deposit_to is not None and event.deposit_to not in accounts:
                c.add(origin, f"{where}.deposit_to", f"unknown account '{event.deposit_to}'")
        elif isinstance(event, HomeSaleEvent):
            if event.pay_off is not None and event.pay_off not in liabilities:
                c.add(origin, f"{where}.pay_off", f"unknown liability '{event.pay_off}'")
        else:
            if household.member(event.beneficiary) is None:
                c.add(origin, f"{where}.beneficiary", f"unknown member '{event.beneficiary}'")
            if event.asset == "brokerage":
                account = accounts.get(event.account or "")
                account_type = None if account is None else rules.account_types.get(account.type)
                if account_type is None or account_type.family is not AccountFamily.BROKERAGE:
                    c.add(origin, f"{where}.account", f"'{event.account}' must be an existing brokerage account")
            elif event.asset == "inherited_ira" and event.account in accounts:
                c.add(origin, f"{where}.account", f"account id '{event.account}' already exists")


def _check_sweep(scenario: ScenarioDoc, origin: str, profile: Profile, rules: RuleSet, c: _Collector) -> None:
    accounts = {a.id: a for a in profile.accounts}
    reserve = scenario.levers.cash_reserve
    if reserve is not None:
        account = accounts.get(reserve.account)
        account_type = None if account is None else rules.account_types.get(account.type)
        where = "levers.cash_reserve.account"
        if account is None:
            c.add(origin, where, f"unknown account '{reserve.account}'")
        elif account_type is not None and (
            account_type.family not in (AccountFamily.BROKERAGE, AccountFamily.CASH)
            or not account_type.allows_contributions
        ):
            c.add(origin, where, f"the cash reserve must be a cash or brokerage account, not {account.type}")
    for index, target in enumerate(scenario.levers.surplus_sweep):
        where = f"levers.surplus_sweep[{index}].account"
        account = accounts.get(target.account)
        if account is None:
            c.add(origin, where, f"unknown account '{target.account}'")
            continue
        account_type = rules.account_types.get(account.type)
        if account_type is None:
            continue
        if account_type.family not in (AccountFamily.BROKERAGE, AccountFamily.CASH):
            c.add(origin, where, f"surplus can only be swept into brokerage or cash accounts, not {account.type}")
        elif not account_type.allows_contributions:
            c.add(origin, where, f"{account.type} accounts don't accept contributions")


def _resolve_market(rules: RuleSet, scenario: ScenarioDoc, origin: str, c: _Collector) -> MarketPreset | None:
    preset = rules.market_assumptions.get(scenario.market.preset)
    if preset is None:
        available = ", ".join(p.id for p in rules.market_assumptions.presets)
        c.add(origin, "market.preset", f"unknown preset '{scenario.market.preset}' (available: {available})")
        return None
    if preset.kind == "bootstrap":
        fixed = [key for key in scenario.market.overrides if key.split(".")[0] in ("factors", "correlations")]
        if fixed:
            c.add(
                origin, "market.overrides", f"bootstrap presets use the historical returns; can't override {fixed[0]}"
            )
            return None
        preset = from_history(preset, rules.historical_returns.matrix())
    if not scenario.market.overrides:
        return preset
    try:
        data = apply_overrides(preset.model_dump(), scenario.market.overrides)
    except OverrideError as error:
        c.add(origin, "market.overrides", str(error))
        return None
    try:
        return MarketPreset.model_validate(data)
    except ValidationError as error:
        c.issues.extend(issues_from_validation_error(error, origin, data, prefix="market.overrides (applied)"))
        return None


def iter_all(source: ConfigSource) -> Iterator[tuple[str, str]]:
    """Every (profile, scenario) pair the source holds."""
    for profile in source.profiles():
        for scenario in source.scenarios(profile):
            yield profile, scenario


def validate_all(source: ConfigSource, pairs: Iterable[tuple[str, str]] | None = None) -> list[ConfigIssue]:
    """Load every (profile, scenario) pair and return all issues found (empty if everything is valid)."""
    issues: list[ConfigIssue] = []
    for profile, scenario in pairs if pairs is not None else iter_all(source):
        try:
            load_simulation_input(source, profile, scenario)
        except ConfigError as error:
            issues.extend(i for i in error.issues if i not in issues)
    return issues
