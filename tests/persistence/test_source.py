import numpy as np
import pytest
from sqlalchemy import select

from northward.config.base import ConfigError
from northward.config.loader import load_simulation_input
from northward.config.source import FileSource
from northward.engine.simulate import simulate
from northward.montecarlo.runner import run_monte_carlo
from northward.persistence.models import DocumentRevision
from northward.persistence.repositories import Address, ProfileRepo, get_revision
from northward.persistence.source import DbSource

SCENARIOS = ["base", "early_retire_roth_fill", "historical_lifespans", "survivor"]


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_file_and_database_sources_give_identical_results(db, example_data, scenario):
    from_files = load_simulation_input(FileSource(example_data), "example", scenario)
    with db.session() as session:
        from_db = load_simulation_input(DbSource(session), "example", scenario)
    assert from_db == from_files
    assert from_db.snapshot.content_hash() == from_files.snapshot.content_hash()
    files_run, db_run = simulate(from_files, record=True), simulate(from_db, record=True)
    assert db_run.years == files_run.years and db_run.transactions == files_run.transactions
    assert db_run.warnings == files_run.warnings


def test_monte_carlo_runs_match_across_sources(db, example_data):
    from_files = load_simulation_input(FileSource(example_data), "example", "historical_lifespans")
    with db.session() as session:
        from_db = load_simulation_input(DbSource(session), "example", "historical_lifespans")
    one, other = run_monte_carlo(from_files, 8, 3, workers=1), run_monte_carlo(from_db, 8, 3, workers=2)
    assert np.array_equal(one.telemetry, other.telemetry, equal_nan=True)


def test_a_source_lists_what_the_database_holds(db):
    with db.session() as session:
        source = DbSource(session)
        assert source.profiles() == ["example"]
        assert source.scenarios("example") == SCENARIOS
        assert source.profile_document("example", "health_costs") is None  # optional, not in the example
        assert source.profile_document("nobody", "household") is None
        doc = source.profile_document("example", "accounts")
        assert doc.origin == "profiles/example/accounts.yaml" and doc.revision_id is not None


def test_loads_record_the_revisions_they_read(db):
    with db.session() as session:
        sim = load_simulation_input(DbSource(session), "example", "base")
        repo = ProfileRepo(session)
        accounts = get_revision(session, repo.document(repo.get("example"), Address.parse("accounts")))
    assert accounts.id in sim.snapshot.revision_ids()
    assert len(sim.snapshot.revision_ids()) == 11 + 7 + 1  # rules, the profile's documents, the scenario


def test_a_pinned_source_still_reads_the_old_revisions_after_an_edit(db):
    with db.session() as session:
        pinned = load_simulation_input(DbSource(session), "example", "base").snapshot.revision_ids()
        original = DbSource(session).profile_document("example", "accounts").text
        ProfileRepo(session).save("example", {"accounts": original.replace("balance: 150000", "balance: 1")})
    with db.session() as session:
        assert "balance: 1\n" in DbSource(session).profile_document("example", "accounts").text
        revisions = session.scalars(select(DocumentRevision).where(DocumentRevision.id.in_(pinned))).all()
        source = DbSource(session, pinned=revisions)
        assert source.profile_document("example", "accounts").text == original
        assert source.profiles() == ["example"] and source.scenarios("example") == ["base"]
        assert source.rules_document("rmd", "any name: a run pins one rule set") is not None


def test_an_overlay_stands_in_for_stored_documents(db):
    with db.session() as session:
        source = DbSource(session, overlay={("scenario", "example", "draft"): "schema_version: 1\n"})
        assert "draft" in source.scenarios("example")
        assert source.scenario_document("example", "draft").text == "schema_version: 1\n"
        assert source.scenario_document("example", "draft").revision_id is None


def test_unknown_rule_sets_are_load_errors(db):
    with db.session() as session:
        with pytest.raises(ConfigError, match=r"unknown rule set '1999' \(the database has 2026\)"):
            load_simulation_input(
                DbSource(
                    session,
                    overlay={
                        (
                            "scenario",
                            "example",
                            "old",
                        ): "schema_version: 1\nrule_set: 1999\nhorizon: {start_year: 2026, end_age: 95}\n"
                    },
                ),
                "example",
                "old",
            )


def test_the_input_hash_ignores_names(db, example_data):
    with db.session() as session:
        text = DbSource(session).scenario_document("example", "base").text
        renamed = load_simulation_input(
            DbSource(session, overlay={("scenario", "example", "copy"): text}), "example", "copy"
        )
        base = load_simulation_input(DbSource(session), "example", "base")
        survivor = load_simulation_input(DbSource(session), "example", "survivor")
    assert renamed.snapshot.content_hash() == base.snapshot.content_hash()
    assert survivor.snapshot.content_hash() != base.snapshot.content_hash()
