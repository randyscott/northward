"""Database tables (docs/decisions.md D13–D17). Documents are YAML text in append-only revisions; Pydantic stays the only schema.

Change these models only together with a new Alembic migration (`make migration m="..."`).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# Named constraints, so Alembic's batch mode can alter them on SQLite.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = {dict[str, Any]: JSON, datetime: DateTime(timezone=True)}


class Profile(Base):
    __tablename__ = "profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    owner_user_id: Mapped[int | None] = mapped_column(Integer)  # unused until multi-user support (D17)
    created_at: Mapped[datetime] = mapped_column(default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(default=utc_now, onupdate=utc_now)
    archived_at: Mapped[datetime | None]  # soft delete (Q10): hidden from listings until restored or purged

    scenarios: Mapped[list[Scenario]] = relationship(
        back_populates="profile", cascade="all, delete-orphan", order_by="Scenario.name"
    )
    documents: Mapped[list[Document]] = relationship(back_populates="profile", cascade="all, delete-orphan")


class Scenario(Base):
    __tablename__ = "scenarios"
    __table_args__ = (UniqueConstraint("profile_id", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(100))
    parent_scenario_id: Mapped[int | None] = mapped_column(ForeignKey("scenarios.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(default=utc_now, onupdate=utc_now)
    archived_at: Mapped[datetime | None]

    profile: Mapped[Profile] = relationship(back_populates="scenarios")
    parent: Mapped[Scenario | None] = relationship(remote_side=[id])
    documents: Mapped[list[Document]] = relationship(back_populates="scenario", cascade="all, delete-orphan")
    runs: Mapped[list[Run]] = relationship(back_populates="scenario", cascade="all, delete-orphan")


class RuleSet(Base):
    """One tax year's rules, shared by every profile. Seeded from `data/rules/`, the master copy (D14)."""

    __tablename__ = "rule_sets"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    tax_year: Mapped[int]
    source_hash: Mapped[str] = mapped_column(String(64))  # of the documents' latest revisions
    created_at: Mapped[datetime] = mapped_column(default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(default=utc_now, onupdate=utc_now)

    documents: Mapped[list[Document]] = relationship(back_populates="rule_set", cascade="all, delete-orphan")


class Document(Base):
    """A configuration document owned by exactly one profile, scenario, or rule set."""

    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint(
            "(CASE WHEN profile_id IS NULL THEN 0 ELSE 1 END) + (CASE WHEN scenario_id IS NULL THEN 0 ELSE 1 END)"
            " + (CASE WHEN rule_set_id IS NULL THEN 0 ELSE 1 END) = 1",
            name="one_owner",
        ),
        # NULLs are distinct in unique constraints, so each applies only to documents of that owner.
        UniqueConstraint("profile_id", "kind"),
        UniqueConstraint("scenario_id", "kind"),
        UniqueConstraint("rule_set_id", "kind"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(40))  # a profile kind, "scenario", or a rule kind
    profile_id: Mapped[int | None] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"))
    scenario_id: Mapped[int | None] = mapped_column(ForeignKey("scenarios.id", ondelete="CASCADE"))
    rule_set_id: Mapped[int | None] = mapped_column(ForeignKey("rule_sets.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(default=utc_now)

    profile: Mapped[Profile | None] = relationship(back_populates="documents")
    scenario: Mapped[Scenario | None] = relationship(back_populates="documents")
    rule_set: Mapped[RuleSet | None] = relationship(back_populates="documents")
    revisions: Mapped[list[DocumentRevision]] = relationship(
        back_populates="document", cascade="all, delete-orphan", order_by="DocumentRevision.revision"
    )


class DocumentRevision(Base):
    """One saved version of a document. Append-only (D15): edits add revision N+1 and never change old ones."""

    __tablename__ = "document_revisions"
    __table_args__ = (UniqueConstraint("document_id", "revision"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    revision: Mapped[int]  # 1, 2, ... within the document
    yaml_text: Mapped[str] = mapped_column(Text)
    schema_version: Mapped[int]
    content_hash: Mapped[str] = mapped_column(String(64))  # SHA-256 of yaml_text
    created_at: Mapped[datetime] = mapped_column(default=utc_now)
    note: Mapped[str | None] = mapped_column(Text)

    document: Mapped[Document] = relationship(back_populates="revisions")


run_revisions = Table(
    "run_revisions",
    Base.metadata,
    Column("run_id", ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True),
    Column("revision_id", ForeignKey("document_revisions.id", ondelete="CASCADE"), primary_key=True),
)


class Run(Base):
    """A deterministic or Monte Carlo run, pinned to the exact revisions it read."""

    __tablename__ = "runs"
    __table_args__ = (Index("ix_runs_cache_key", "scenario_id", "kind", "input_hash", "seed", "n_sims"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    scenario_id: Mapped[int] = mapped_column(ForeignKey("scenarios.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(20))  # deterministic | monte_carlo
    seed: Mapped[int | None]
    n_sims: Mapped[int | None]
    engine_version: Mapped[str] = mapped_column(String(64))
    input_hash: Mapped[str] = mapped_column(String(64))  # SnapshotSource.content_hash() of the inputs
    status: Mapped[str] = mapped_column(String(20))  # queued | running | complete | failed
    pid: Mapped[int | None]  # the process running it, so a restarted server can tell abandoned runs from live ones
    summary: Mapped[dict[str, Any] | None]
    output_dir: Mapped[str | None] = mapped_column(Text)  # telemetry.npz etc. (Monte Carlo) or years.csv
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utc_now)
    finished_at: Mapped[datetime | None]
    elapsed_seconds: Mapped[float | None] = mapped_column(Float)

    scenario: Mapped[Scenario] = relationship(back_populates="runs")
    revisions: Mapped[list[DocumentRevision]] = relationship(secondary=run_revisions)
