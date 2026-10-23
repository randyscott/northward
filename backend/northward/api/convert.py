"""Turning stored objects into API responses, and request content into YAML text."""

from __future__ import annotations

import math
from typing import Any

import yaml
from sqlalchemy.orm import Session

from northward.api import schemas
from northward.config.loader import REQUIRED_PROFILE_DOCS
from northward.config.source import PROFILE_KIND_DESCRIPTIONS, PROFILE_KINDS, RULE_KINDS
from northward.config.yaml_edit import merge_into_yaml
from northward.persistence.models import Document, DocumentRevision, Profile, RuleSet, Scenario
from northward.persistence.repositories import (
    SCENARIO_PREFIX,
    Address,
    ProfileRepo,
    RuleRepo,
    ScenarioRepo,
    get_revision,
    latest_revision,
)
from northward.persistence.runs import RunInfo, as_utc


def json_safe(value: Any) -> Any:
    """`value` with NaN and infinities replaced by None (JSON has no NaN; e.g. bands after every path has ended)."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {k: json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    return value


def parse(text: str) -> dict[str, Any]:
    """A stored document's data (stored documents are valid, so always a mapping)."""
    data = yaml.safe_load(text)
    return data if isinstance(data, dict) else {}


def content_text(content: schemas.Content, current: str | None) -> str:
    """YAML text for new content: as given, or structured data merged into the current text."""
    if content.yaml_text is not None:
        return content.yaml_text
    assert content.data is not None
    return merge_into_yaml(current, content.data)


def revision_out(revision: DocumentRevision) -> schemas.RevisionOut:
    return schemas.RevisionOut(
        id=revision.id,
        document_id=revision.document_id,
        revision=revision.revision,
        created_at=as_utc(revision.created_at),
        note=revision.note,
        content_hash=revision.content_hash,
        schema_version=revision.schema_version,
    )


def revision_detail(revision: DocumentRevision) -> schemas.RevisionDetail:
    return schemas.RevisionDetail(
        **revision_out(revision).model_dump(), yaml_text=revision.yaml_text, data=parse(revision.yaml_text)
    )


def describe(document: Document) -> tuple[str, str, bool]:
    """(address, description, required) of a document."""
    if document.scenario is not None:
        return f"{SCENARIO_PREFIX}{document.scenario.name}", "a scenario: horizon, market, levers, overrides", True
    if document.rule_set is not None:
        return document.kind, f"rules: {document.kind.replace('_', ' ')}", True
    return document.kind, PROFILE_KIND_DESCRIPTIONS[document.kind], document.kind in REQUIRED_PROFILE_DOCS


def document_out(session: Session, document: Document) -> schemas.DocumentOut:
    address, description, required = describe(document)
    latest = latest_revision(session, document)
    return schemas.DocumentOut(
        address=address,
        kind=document.kind,
        id=document.id,
        required=required,
        description=description,
        latest=None if latest is None else revision_out(latest),
    )


def document_detail(session: Session, document: Document, revision: int | None = None) -> schemas.DocumentDetail:
    found = get_revision(session, document, revision)
    return schemas.DocumentDetail(
        **document_out(session, document).model_dump(), yaml_text=found.yaml_text, data=parse(found.yaml_text)
    )


def profile_documents(session: Session, profile: Profile) -> list[schemas.DocumentOut]:
    """Every kind a profile can have, in order, whether it has one yet or not."""
    stored = {d.kind: d for d in profile.documents}
    out = []
    for kind in PROFILE_KINDS:
        if kind in stored:
            out.append(document_out(session, stored[kind]))
        else:
            out.append(
                schemas.DocumentOut(
                    address=kind,
                    kind=kind,
                    id=None,
                    required=kind in REQUIRED_PROFILE_DOCS,
                    description=PROFILE_KIND_DESCRIPTIONS[kind],
                    latest=None,
                )
            )
    return out


def scenario_out(session: Session, profile: Profile, scenario: Scenario, detail: bool = False) -> Any:
    document = ProfileRepo(session).document(profile, Address("scenario", scenario.name), include_archived=True)
    latest = get_revision(session, document)
    data = parse(latest.yaml_text)
    description = data.get("description")
    fields: dict[str, Any] = dict(
        name=scenario.name,
        description=description if isinstance(description, str) else None,
        parent=scenario.parent.name if scenario.parent else None,
        document_id=document.id,
        latest=revision_out(latest),
        created_at=as_utc(scenario.created_at),
        updated_at=as_utc(scenario.updated_at),
        deleted_at=as_utc(scenario.archived_at) if scenario.archived_at else None,
    )
    if detail:
        return schemas.ScenarioDetail(**fields, yaml_text=latest.yaml_text, data=data)
    return schemas.ScenarioOut(**fields)


def profile_out(session: Session, profile: Profile, include_deleted: bool = False) -> schemas.ProfileOut:
    return schemas.ProfileOut(
        name=profile.name,
        created_at=as_utc(profile.created_at),
        updated_at=as_utc(profile.updated_at),
        deleted_at=as_utc(profile.archived_at) if profile.archived_at else None,
        scenarios=[s.name for s in ScenarioRepo(session).list(profile, include_archived=include_deleted)],
    )


def profile_detail(session: Session, profile: Profile, include_deleted: bool = False) -> schemas.ProfileDetail:
    scenarios = ScenarioRepo(session).list(profile, include_archived=include_deleted)
    return schemas.ProfileDetail(
        **profile_out(session, profile, include_deleted).model_dump(),
        documents=profile_documents(session, profile),
        scenario_details=[scenario_out(session, profile, s) for s in scenarios],
    )


def rule_set_out(session: Session, rule_set: RuleSet) -> schemas.RuleSetOut:
    rules = RuleRepo(session)
    latest = rules.find()
    return schemas.RuleSetOut(
        name=rule_set.name,
        tax_year=rule_set.tax_year,
        latest=latest is not None and latest.id == rule_set.id,
        source_hash=rule_set.source_hash,
        created_at=as_utc(rule_set.created_at),
        updated_at=as_utc(rule_set.updated_at),
        documents=[document_out(session, rules.document(rule_set, kind)) for kind in RULE_KINDS],
    )


def run_out(info: RunInfo, progress: tuple[int, int] | None = None) -> schemas.RunOut:
    return schemas.RunOut(
        id=info.id,
        kind=info.kind,  # type: ignore[arg-type]
        profile=info.profile,
        scenario=info.scenario,
        status=info.status,  # type: ignore[arg-type]
        seed=info.seed,
        n_sims=info.n_sims,
        engine_version=info.engine_version,
        input_hash=info.input_hash,
        created_at=info.created_at,
        finished_at=info.finished_at,
        elapsed_seconds=info.elapsed_seconds,
        error=info.error,
        summary=json_safe(info.summary),
        revisions=list(info.revisions),
        cached=info.cached,
        progress=None if progress is None else schemas.Progress(done=progress[0], total=progress[1]),
    )
