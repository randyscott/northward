import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from northward.persistence.db import Database, DatabaseError
from northward.persistence.models import Base, Document, Profile, RuleSet


def test_migrations_run_cleanly_from_an_empty_database(empty_db):
    assert not empty_db.sqlite_path.exists()
    before, after = empty_db.migrate()
    assert before is None and after == empty_db.head_revision()
    tables = set(inspect(empty_db.engine).get_table_names())
    assert {"profiles", "scenarios", "rule_sets", "documents", "document_revisions", "runs", "run_revisions"} <= tables
    assert empty_db.migrate() == (after, after)  # re-running is a no-op
    empty_db.check_schema()


def test_the_migrations_match_the_models(empty_db):
    empty_db.migrate()
    with empty_db.engine.connect() as connection:
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []


def test_migrations_downgrade_and_upgrade_again(empty_db):
    empty_db.migrate()
    config = empty_db._alembic_config()
    with empty_db.engine.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, "base")
    assert empty_db.current_revision() is None
    assert set(inspect(empty_db.engine).get_table_names()) == {"alembic_version"}
    empty_db.migrate()
    empty_db.check_schema()


def test_check_schema_explains_a_missing_or_stale_database(empty_db):
    with pytest.raises(DatabaseError, match="run `northward db init` and `northward db seed`, or pass --data-dir"):
        empty_db.check_schema()
    empty_db.migrate()
    with empty_db.engine.begin() as connection:
        connection.exec_driver_sql("UPDATE alembic_version SET version_num = 'older'")
    with pytest.raises(DatabaseError, match="run `northward db migrate`"):
        empty_db.check_schema()


def test_a_document_has_exactly_one_owner(db):
    with pytest.raises(IntegrityError, match="ck_documents_one_owner"), db.session() as session:
        profile = session.query(Profile).filter_by(name="example").one()
        rule_set = session.query(RuleSet).one()
        session.add(Document(kind="household", profile=profile, rule_set=rule_set))
        session.flush()


def test_foreign_keys_are_enforced_on_sqlite(db):
    with pytest.raises(IntegrityError), db.engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO documents (kind, profile_id, created_at) VALUES ('x', 999, '2026-01-01')"
        )


def test_database_url_comes_from_the_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("NORTHWARD_DATABASE_URL", f"sqlite:///{tmp_path / 'env.db'}")
    assert Database().sqlite_path == tmp_path / "env.db"
    assert Database(f"sqlite:///{tmp_path / 'flag.db'}").sqlite_path == tmp_path / "flag.db"
