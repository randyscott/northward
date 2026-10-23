"""Alembic environment. `Database.migrate` passes its connection in `config.attributes["connection"]`."""

from alembic import context
from sqlalchemy import Connection, create_engine

from northward.persistence.models import Base

config = context.config


def _run(connection: Connection) -> None:
    # Batch mode rebuilds tables for ALTERs that SQLite can't do in place.
    context.configure(connection=connection, target_metadata=Base.metadata, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


connection = config.attributes.get("connection")
if connection is not None:
    _run(connection)
else:
    with create_engine(config.get_main_option("sqlalchemy.url")).begin() as connection:
        _run(connection)
