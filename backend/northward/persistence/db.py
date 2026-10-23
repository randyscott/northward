"""Connecting to the database and keeping its schema current with Alembic.

The URL comes from `--db`, else `NORTHWARD_DATABASE_URL`, else SQLite at `var/northward.db`. Moving to Postgres or MySQL
should only need a new URL (D13).
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, create_engine, event, make_url
from sqlalchemy.orm import Session, sessionmaker

DEFAULT_URL = "sqlite:///var/northward.db"
URL_ENV = "NORTHWARD_DATABASE_URL"
MIGRATIONS = Path(__file__).parent / "migrations"


class DatabaseError(RuntimeError):
    """The database is missing, not initialized, or at a schema this version of northward doesn't expect."""


def database_url(explicit: str | None = None) -> str:
    return explicit or os.environ.get(URL_ENV) or DEFAULT_URL


def _enable_sqlite_foreign_keys(dbapi_connection: Any, _record: Any) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


class Database:
    def __init__(self, url: str | None = None):
        self.url = make_url(database_url(url))
        self.engine: Engine = create_engine(self.url)
        if self.is_sqlite:
            event.listen(self.engine, "connect", _enable_sqlite_foreign_keys)
        self._sessions = sessionmaker(self.engine, expire_on_commit=False)

    @property
    def is_sqlite(self) -> bool:
        return self.url.get_backend_name() == "sqlite"

    @property
    def sqlite_path(self) -> Path | None:
        """The SQLite database file (None for other databases and in-memory SQLite)."""
        database = self.url.database
        return Path(database) if self.is_sqlite and database and database != ":memory:" else None

    @contextmanager
    def session(self) -> Iterator[Session]:
        """A session that commits when the block succeeds and rolls back when it raises."""
        with self._sessions() as session, session.begin():
            yield session

    # --- schema -------------------------------------------------------------------------------------------------

    def _alembic_config(self) -> Config:
        config = Config()
        config.set_main_option("script_location", str(MIGRATIONS))
        config.set_main_option("sqlalchemy.url", self.url.render_as_string(hide_password=False))
        return config

    def current_revision(self) -> str | None:
        if self.sqlite_path is not None and not self.sqlite_path.exists():
            return None
        with self.engine.connect() as connection:
            return MigrationContext.configure(connection).get_current_revision()

    def head_revision(self) -> str | None:
        return ScriptDirectory.from_config(self._alembic_config()).get_current_head()

    def migrate(self) -> tuple[str | None, str | None]:
        """Create or upgrade the schema to the latest migration. Returns (revision before, revision after)."""
        if self.sqlite_path is not None:
            self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        before = self.current_revision()
        config = self._alembic_config()
        with self.engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        return before, self.current_revision()

    def check_schema(self) -> None:
        """Raise DatabaseError unless the schema is at the latest migration."""
        current = self.current_revision()
        if current is None:
            where = self.sqlite_path or self.url.render_as_string()
            raise DatabaseError(
                f"no northward database at {where}; run `northward db init` and `northward db seed`, or pass --data-dir"
            )
        if current != self.head_revision():
            raise DatabaseError("the database schema is out of date; run `northward db migrate`")


def make_migration(message: str) -> None:
    """Development: write a new migration from the difference between the models and an empty database at head."""
    with tempfile.TemporaryDirectory() as tmp:
        db = Database(f"sqlite:///{tmp}/schema.db")
        config = db._alembic_config()
        config.set_main_option("file_template", "%%(rev)s_%%(slug)s")
        next_id = f"{len(list((MIGRATIONS / 'versions').glob('[0-9][0-9][0-9][0-9]_*.py'))) + 1:04d}"
        with db.engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
            command.revision(config, message=message, autogenerate=True, rev_id=next_id)
        db.engine.dispose()
