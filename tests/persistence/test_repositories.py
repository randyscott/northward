import pytest
from sqlalchemy import func, select

from northward.config.base import ConfigError
from northward.persistence.models import Document, Profile, Scenario
from northward.persistence.repositories import (
    Address,
    Conflict,
    NotFound,
    ProfileRepo,
    ScenarioRepo,
    _append,
    content_hash,
    get_revision,
    history,
)
from northward.persistence.source import DbSource

NEW_ACCOUNT = """
  - id: joint_cd
    owner: joint
    type: savings
    balance: 10000
"""


def text(db, profile: str, address: str, revision: int | None = None) -> str:
    with db.session() as session:
        repo = ProfileRepo(session)
        return get_revision(session, repo.document(repo.get(profile), Address.parse(address)), revision).yaml_text


def revisions(db, profile: str, address: str) -> list[int]:
    with db.session() as session:
        repo = ProfileRepo(session)
        return [r.revision for r in history(session, repo.document(repo.get(profile), Address.parse(address)))]


def save(db, changes: dict[str, str], note: str | None = None, profile: str = "example", create: bool = False):
    with db.session() as session:
        return [(str(a), r.revision) for a, r in ProfileRepo(session).save(profile, changes, note, create=create)]


def test_editing_a_document_appends_revision_n_plus_1(db):
    original = text(db, "example", "accounts")
    edited = original.replace("balance: 150000", "balance: 160000")
    assert save(db, {"accounts": edited}, "brokerage statement") == [("accounts", 2)]
    assert revisions(db, "example", "accounts") == [1, 2]
    assert text(db, "example", "accounts") == edited
    assert text(db, "example", "accounts", 1) == original  # old revisions never change
    with db.session() as session:
        repo = ProfileRepo(session)
        latest = get_revision(session, repo.document(repo.get("example"), Address.parse("accounts")))
        assert latest.note == "brokerage statement" and latest.content_hash == content_hash(edited)
        assert latest.schema_version == 1


def test_saving_identical_text_adds_no_revision(db):
    assert save(db, {"accounts": text(db, "example", "accounts")}) == []
    assert revisions(db, "example", "accounts") == [1]


def test_an_invalid_write_is_rejected_with_the_pydantic_error(db):
    broken = text(db, "example", "household").replace("birth_month: 9", "birth_month: 13")
    with pytest.raises(ConfigError) as info:
        save(db, {"household": broken})
    assert [str(i) for i in info.value.issues] == [
        "profiles/example/household.yaml: members[alex].birth_month: Input should be less than or equal to 12"
    ]
    assert revisions(db, "example", "household") == [1]


def test_yaml_errors_and_unknown_fields_are_rejected(db):
    with pytest.raises(ConfigError, match="invalid YAML"):
        save(db, {"spending": "schema_version: 1\nspending: [unclosed\n"})
    with pytest.raises(ConfigError, match="Extra inputs are not permitted"):
        save(db, {"goals": "schema_version: 1\nsurprise: true\n"})


def test_a_write_that_breaks_a_cross_reference_is_rejected(db):
    accounts = text(db, "example", "accounts").replace("id: riley_529", "id: riley_college")
    with pytest.raises(ConfigError) as info:
        save(db, {"accounts": accounts})
    assert any("unknown account 'riley_529'" in str(issue) for issue in info.value.issues)
    assert revisions(db, "example", "accounts") == [1]


def test_documents_saved_together_are_validated_together(db):
    scenario = text(db, "example", "scenarios/base").replace(
        "levers:\n", "levers:\n  surplus_sweep:\n    - account: joint_cd\n", 1
    )
    with pytest.raises(ConfigError, match="unknown account 'joint_cd'"):
        save(db, {"scenarios/base": scenario})
    accounts = text(db, "example", "accounts").rstrip("\n") + "\n" + NEW_ACCOUNT
    assert save(db, {"accounts": accounts, "scenarios/base": scenario}) == [("accounts", 2), ("scenarios/base", 2)]


def test_existing_problems_dont_block_unrelated_edits(db):
    # Store a broken scenario directly, as if new rules had broken it after it was saved.
    broken = text(db, "example", "scenarios/survivor").replace(
        "levers:\n", "levers:\n  relocations:\n    - {when: {year: 2030}, state: ZZ}\n", 1
    )
    with db.session() as session:
        repo = ProfileRepo(session)
        _append(session, repo.document(repo.get("example"), Address.parse("scenarios/survivor")), broken, None)
    edited = text(db, "example", "accounts").replace("balance: 150000", "balance: 160000")
    assert save(db, {"accounts": edited}) == [("accounts", 2)]
    # A change that adds a problem is still rejected, and only the new problem is reported.
    with pytest.raises(ConfigError) as info:
        save(db, {"accounts": edited.replace("id: riley_529", "id: riley_college")})
    assert not any("ZZ" in str(issue) for issue in info.value.issues)


def test_a_new_scenario_is_created_by_saving_it(db):
    base = text(db, "example", "scenarios/base")
    assert save(db, {"scenarios/retire_at_60": base}) == [("scenarios/retire_at_60", 1)]
    with db.session() as session:
        assert "retire_at_60" in DbSource(session).scenarios("example")


def test_a_new_profile_needs_create_and_its_required_documents(db):
    docs = {kind: text(db, "example", kind) for kind in ("household", "accounts", "spending")}
    with pytest.raises(NotFound, match="create it with --create"):
        save(db, docs, profile="copy")
    with pytest.raises(ConfigError, match="profiles/copy/spending.yaml: required profile document is missing"):
        save(db, {"household": docs["household"], "accounts": docs["accounts"]}, profile="copy", create=True)
    assert len(save(db, docs, profile="copy", create=True)) == 3
    with db.session() as session:
        assert ProfileRepo(session).get("copy").owner_user_id is None


@pytest.mark.parametrize("address", ["nonsense", "scenarios/Bad-Name", "rmd"])
def test_addresses_are_checked(address):
    with pytest.raises(ValueError):
        Address.parse(address)


def test_addresses_mirror_the_data_layout():
    assert Address.parse("accounts.yaml") == Address("accounts")
    assert Address.parse("scenarios/base") == Address("scenario", "base")
    assert str(Address("scenario", "base")) == "scenarios/base"


def test_deleting_a_profile_hides_it_until_restored(db):
    with db.session() as session:
        ProfileRepo(session).archive("example")
    with db.session() as session:
        repo = ProfileRepo(session)
        assert repo.list() == [] and [p.name for p in repo.list(include_archived=True)] == ["example"]
        assert DbSource(session).profiles() == []
        with pytest.raises(NotFound, match="is deleted"):
            repo.get("example")
    with pytest.raises(Conflict, match="restore it before editing"):
        save(db, {"accounts": "schema_version: 1\naccounts: []\n"})
    with db.session() as session:
        ProfileRepo(session).restore("example")
    with db.session() as session:
        assert DbSource(session).profiles() == ["example"]


def test_purging_needs_a_deleted_profile_and_removes_everything(db):
    with db.session() as session, pytest.raises(Conflict, match="must be deleted"):
        ProfileRepo(session).purge("example")
    with db.session() as session:
        ProfileRepo(session).archive("example")
    with db.session() as session:
        assert ProfileRepo(session).purge("example") == []
    with db.session() as session:
        assert ProfileRepo(session).find("example", include_archived=True) is None
        assert session.scalar(select(func.count()).select_from(Scenario)) == 0
        assert session.scalar(select(func.count()).where(Document.rule_set_id.is_(None))) == 0


def test_scenarios_are_deleted_restored_and_purged(db):
    with db.session() as session:
        scenarios = ScenarioRepo(session)
        profile = ProfileRepo(session).get("example")
        scenarios.archive(profile, "survivor")
        assert "survivor" not in [s.name for s in scenarios.list(profile)]
        with pytest.raises(Conflict, match="isn't deleted"):
            scenarios.restore(profile, "base")
    with pytest.raises(Conflict, match="restore it before editing"):
        save(db, {"scenarios/survivor": text(db, "example", "scenarios/base")})
    with db.session() as session:
        profile = ProfileRepo(session).get("example")
        ScenarioRepo(session).purge(profile, "survivor")
    with db.session() as session:
        assert DbSource(session).scenarios("example") == ["base", "early_retire_roth_fill", "historical_lifespans"]


def test_cloning_a_scenario_remembers_its_parent(db):
    with db.session() as session:
        profile = ProfileRepo(session).get("example")
        clone = ScenarioRepo(session).clone(profile, "base", "what_if")
        assert clone.parent.name == "base"
        with pytest.raises(Conflict, match="already has a scenario"):
            ScenarioRepo(session).clone(profile, "base", "what_if")
    assert text(db, "example", "scenarios/what_if") == text(db, "example", "scenarios/base")
    with db.session() as session:
        repo = ProfileRepo(session)
        note = get_revision(session, repo.document(repo.get("example"), Address.parse("scenarios/what_if"))).note
        assert note == "cloned from base"


def test_profiles_can_be_scoped_to_an_owner(db):
    with db.session() as session:
        session.add(Profile(name="someone_elses", owner_user_id=7))
    with db.session() as session:
        assert [p.name for p in ProfileRepo(session).list()] == ["example", "someone_elses"]  # single-user mode
        assert [p.name for p in ProfileRepo(session, owner_user_id=7).list()] == ["someone_elses"]
        assert ProfileRepo(session, owner_user_id=7).find("example") is None
        assert DbSource(session, owner_user_id=7).profiles() == ["someone_elses"]
