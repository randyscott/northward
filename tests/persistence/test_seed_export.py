import shutil
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
import yaml
from sqlalchemy import func, select

from northward.config.base import ConfigError
from northward.config.loader import load_simulation_input
from northward.config.source import RULE_KINDS
from northward.persistence.models import DocumentRevision
from northward.persistence.repositories import Address, ProfileRepo, RuleRepo, get_revision, history
from northward.persistence.seed import backup, export, seed
from northward.persistence.source import DbSource


def files(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*.yaml"))}


def revision_count(db) -> int:
    with db.session() as session:
        return session.scalar(select(func.count()).select_from(DocumentRevision))


def copy_tree(example_data: Path, tmp_path: Path) -> Path:
    root = tmp_path / "data"
    shutil.copytree(example_data, root)
    return root


def test_seed_then_export_reproduces_the_data_tree(db, example_data, tmp_path):
    written = export(db, tmp_path / "out")
    assert files(tmp_path / "out") == files(example_data)  # byte for byte, comments and key order included
    assert len(written) == len(files(example_data))
    for relative, text in files(tmp_path / "out").items():
        assert yaml.safe_load(text) == yaml.safe_load((example_data / relative).read_text())


def test_seeding_again_changes_nothing(db, example_data):
    before = revision_count(db)
    report = seed(db, example_data)
    assert not report.rule_set_created and report.rules_updated == ()
    assert report.profiles_added == [] and report.scenarios_added == []
    assert "example" in report.skipped and "example/base" in report.skipped
    assert revision_count(db) == before


def test_changed_rules_get_a_new_revision(db, example_data, tmp_path):
    root = copy_tree(example_data, tmp_path)
    rmd = root / "rules" / "rmd.yaml"
    rmd.write_text(rmd.read_text() + "\n# a reviewed correction\n")
    with db.session() as session:
        old_hash = RuleRepo(session).get("2026").source_hash
    report = seed(db, root)
    assert report.rule_set == "2026" and report.rules_updated == ("rmd",) and report.problems == []
    with db.session() as session:
        rules = RuleRepo(session)
        assert rules.get("2026").source_hash != old_hash
        assert [r.revision for r in history(session, rules.document(rules.get("2026"), "rmd"))] == [1, 2]
        assert len(history(session, rules.document(rules.get("2026"), "federal_tax"))) == 1


def test_a_new_tax_year_is_a_new_rule_set_and_older_scenarios_can_pin_the_old_one(db, example_data, tmp_path):
    root = copy_tree(example_data, tmp_path)
    federal = root / "rules" / "federal_tax.yaml"
    federal.write_text(federal.read_text().replace("base_year: 2026", "base_year: 2027", 1))
    report = seed(db, root)
    assert report.rule_set_created and report.rule_set == "2027"
    with db.session() as session:
        assert [r.name for r in RuleRepo(session).list()] == ["2026", "2027"]
        assert RuleRepo(session).get().name == "2027"  # latest
        scenario = get_revision(
            session, ProfileRepo(session).document(ProfileRepo(session).get("example"), Address.parse("scenarios/base"))
        )
        pinned = scenario.yaml_text.replace("schema_version: 1\n", "schema_version: 1\nrule_set: 2026\n", 1)
        ProfileRepo(session).save("example", {"scenarios/base": pinned})
    with db.session() as session:
        sim = load_simulation_input(DbSource(session), "example", "base")
        assert sim.rules.federal_tax.metadata.base_year == 2026
        latest = load_simulation_input(DbSource(session), "example", "survivor")
        assert latest.rules.federal_tax.metadata.base_year == 2027


def test_profiles_are_imported_once_but_new_scenario_files_are_added(db, example_data, tmp_path):
    root = copy_tree(example_data, tmp_path)
    accounts = root / "profiles" / "example" / "accounts.yaml"
    accounts.write_text(accounts.read_text() + "\n# edited after seeding: the database is the master copy now\n")
    shutil.copy(
        root / "profiles" / "example" / "scenarios" / "base.yaml",
        root / "profiles" / "example" / "scenarios" / "copy.yaml",
    )
    report = seed(db, root)
    assert report.scenarios_added == ["example/copy"] and report.profiles_added == []
    with db.session() as session:
        repo = ProfileRepo(session)
        stored = get_revision(session, repo.document(repo.get("example"), Address.parse("accounts"))).yaml_text
        assert "master copy" not in stored


def test_an_invalid_profile_is_reported_and_not_imported(db, example_data, tmp_path):
    root = copy_tree(example_data, tmp_path)
    shutil.copytree(root / "profiles" / "example", root / "profiles" / "broken")
    household = root / "profiles" / "broken" / "household.yaml"
    household.write_text(household.read_text().replace("birth_month: 9", "birth_month: 13"))
    report = seed(db, root)
    assert "broken" in report.rejected and "broken" not in report.profiles_added
    assert any("birth_month" in str(issue) for issue in report.rejected["broken"])
    with db.session() as session:
        assert ProfileRepo(session).find("broken") is None


def test_invalid_rules_stop_the_seed(db, example_data, tmp_path):
    root = copy_tree(example_data, tmp_path)
    (root / "rules" / "rmd.yaml").write_text("schema_version: 1\nnot_a_field: 1\n")
    with pytest.raises(ConfigError, match="rules/rmd.yaml"):
        seed(db, root)


def test_export_can_select_profiles_and_rule_sets(db, tmp_path):
    written = export(db, tmp_path / "out", profiles=["example"], rule_set="2026")
    assert {p.relative_to(tmp_path / "out").parts[0] for p in written} == {"rules", "profiles"}
    assert len([p for p in written if p.parts[-2] == "rules"]) == len(RULE_KINDS)


def test_backup_holds_an_export_and_a_copy_of_the_database(db, example_data, tmp_path):
    backup(db, tmp_path / "backup")
    assert files(tmp_path / "backup" / "data") == files(example_data)
    with closing(sqlite3.connect(tmp_path / "backup" / "northward.db")) as copy:
        assert copy.execute("SELECT count(*) FROM document_revisions").fetchone()[0] == revision_count(db)


def test_a_deleted_profile_is_not_reimported(db, example_data):
    with db.session() as session:
        ProfileRepo(session).archive("example")
    report = seed(db, example_data)
    assert report.skipped == ["example (deleted)"] and report.profiles_added == []
