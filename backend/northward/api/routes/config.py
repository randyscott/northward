"""Profiles, their documents and scenarios, revisions, rule sets, schemas, and validation.

Documents are addressed as in the data/ layout and the CLI: `accounts`, `scenarios/base`. Rule sets are read-only:
data/rules is their master copy (D14). Deleting is a soft delete; `?purge=true` on a deleted item removes it (D39).
"""

from __future__ import annotations

import difflib
from collections.abc import Mapping
from typing import Any

from fastapi import APIRouter, Response

from northward.api import convert, schemas
from northward.api.deps import RunsDirDep, SessionDep
from northward.config.loader import document_model, validate_document
from northward.config.source import RawDocument
from northward.persistence.models import DocumentRevision, Profile
from northward.persistence.repositories import (
    SCENARIO_PREFIX,
    Address,
    Conflict,
    NotFound,
    ProfileRepo,
    RuleRepo,
    ScenarioRepo,
    address_of,
    get_document,
    get_revision,
    history,
)
from northward.persistence.runs import remove_outputs

router = APIRouter(prefix="/api")


# --- helpers -----------------------------------------------------------------------------------------------------


def _current(session: SessionDep, profile: Profile | None, address: Address) -> DocumentRevision | None:
    if profile is None:
        return None
    try:
        return get_revision(session, ProfileRepo(session).document(profile, address))
    except NotFound:
        return None


def _texts(
    session: SessionDep, name: str, changes: Mapping[str, schemas.Content], create: bool = False
) -> dict[str, str]:
    """{address: YAML text} for a set of changes, after checking any `base_revision` against the latest one."""
    profile = ProfileRepo(session).find(name)
    if profile is None and not create:
        ProfileRepo(session).get(name)  # raises the right NotFound
    texts = {}
    for raw_address, content in changes.items():
        address = Address.parse(raw_address)
        current = _current(session, profile, address)
        base = getattr(content, "base_revision", None)
        if base is not None and (current is None or current.revision != base):
            latest = "no revision" if current is None else f"revision {current.revision}"
            raise Conflict(f"{address} has changed since revision {base} (it's at {latest}); reload and retry")
        texts[str(address)] = convert.content_text(content, None if current is None else current.yaml_text)
    return texts


def _save(session: SessionDep, name: str, texts: dict[str, str], note: str | None) -> schemas.SaveResult:
    saved = ProfileRepo(session).save(name, texts, note)
    return schemas.SaveResult(saved=[convert.revision_out(revision) for _, revision in saved])


# --- profiles ----------------------------------------------------------------------------------------------------


@router.get("/profiles", response_model=list[schemas.ProfileOut], tags=["profiles"])
def list_profiles(session: SessionDep, deleted: bool = False) -> list[schemas.ProfileOut]:
    return [convert.profile_out(session, p, deleted) for p in ProfileRepo(session).list(include_archived=deleted)]


@router.post("/profiles", response_model=schemas.ProfileDetail, status_code=201, tags=["profiles"])
def create_profile(session: SessionDep, body: schemas.ProfileCreate) -> schemas.ProfileDetail:
    repo = ProfileRepo(session)
    if repo.find(body.name, include_archived=True) is not None:
        raise Conflict(f"a profile named '{body.name}' already exists")
    if body.copy_from is not None:
        if body.documents:
            raise ValueError("give either documents or copy_from, not both")
        profile = repo.copy(body.copy_from, body.name, body.note)
    else:
        repo.save(body.name, _texts(session, body.name, body.documents, create=True), body.note, create=True)
        profile = repo.get(body.name)
    return convert.profile_detail(session, profile)


@router.get("/profiles/{profile}", response_model=schemas.ProfileDetail, tags=["profiles"])
def get_profile(session: SessionDep, profile: str, deleted: bool = False) -> schemas.ProfileDetail:
    return convert.profile_detail(session, ProfileRepo(session).get(profile, include_archived=deleted), deleted)


@router.patch("/profiles/{profile}", response_model=schemas.ProfileDetail, tags=["profiles"])
def rename_profile(session: SessionDep, profile: str, body: schemas.Rename) -> schemas.ProfileDetail:
    return convert.profile_detail(session, ProfileRepo(session).rename(profile, body.name))


@router.delete("/profiles/{profile}", status_code=204, tags=["profiles"])
def delete_profile(session: SessionDep, runs_dir: RunsDirDep, profile: str, purge: bool = False) -> Response:
    """Delete (archive) a profile; with `purge=true`, permanently remove an already-deleted one and its runs."""
    repo = ProfileRepo(session)
    if purge:
        remove_outputs(repo.purge(profile), runs_dir)
    else:
        repo.archive(profile)
    return Response(status_code=204)


@router.post("/profiles/{profile}/restore", response_model=schemas.ProfileDetail, tags=["profiles"])
def restore_profile(session: SessionDep, profile: str) -> schemas.ProfileDetail:
    return convert.profile_detail(session, ProfileRepo(session).restore(profile))


# --- documents ---------------------------------------------------------------------------------------------------


@router.get("/profiles/{profile}/documents", response_model=list[schemas.DocumentOut], tags=["documents"])
def list_documents(session: SessionDep, profile: str) -> list[schemas.DocumentOut]:
    """Every kind of document a profile can have (`id` null: an optional one it doesn't have yet), then its
    scenarios'."""
    found = ProfileRepo(session).get(profile)
    scenarios = [
        convert.document_out(session, ProfileRepo(session).document(found, Address("scenario", s.name)))
        for s in ScenarioRepo(session).list(found)
    ]
    return convert.profile_documents(session, found) + scenarios


@router.put("/profiles/{profile}/documents", response_model=schemas.SaveResult, tags=["documents"])
def save_documents(session: SessionDep, profile: str, body: schemas.BatchSave) -> schemas.SaveResult:
    """Save several documents at once; they're validated together, so e.g. a new account and a scenario that uses it
    can be saved in one step."""
    return _save(session, profile, _texts(session, profile, body.changes), body.note)


@router.get("/profiles/{profile}/documents/{address:path}", response_model=schemas.DocumentDetail, tags=["documents"])
def get_document_by_address(
    session: SessionDep, profile: str, address: str, revision: int | None = None
) -> schemas.DocumentDetail:
    repo = ProfileRepo(session)
    return convert.document_detail(session, repo.document(repo.get(profile), Address.parse(address)), revision)


@router.put("/profiles/{profile}/documents/{address:path}", response_model=schemas.SaveResult, tags=["documents"])
def save_document(session: SessionDep, profile: str, address: str, body: schemas.DocumentSave) -> schemas.SaveResult:
    """Save a new revision from YAML text or structured data (merged into the current text, keeping comments).
    Creates the document, or the scenario, if it doesn't exist yet."""
    return _save(session, profile, _texts(session, profile, {address: body}), body.note)


@router.get("/documents/{document_id}", response_model=schemas.DocumentDetail, tags=["documents"])
def get_document_by_id(session: SessionDep, document_id: int) -> schemas.DocumentDetail:
    return convert.document_detail(session, get_document(session, document_id))


@router.get("/documents/{document_id}/revisions", response_model=list[schemas.RevisionOut], tags=["documents"])
def list_revisions(session: SessionDep, document_id: int) -> list[schemas.RevisionOut]:
    return [convert.revision_out(r) for r in history(session, get_document(session, document_id))]


@router.get("/documents/{document_id}/revisions/{revision}", response_model=schemas.RevisionDetail, tags=["documents"])
def get_revision_detail(session: SessionDep, document_id: int, revision: int) -> schemas.RevisionDetail:
    return convert.revision_detail(get_revision(session, get_document(session, document_id), revision))


@router.get("/documents/{document_id}/diff", response_model=schemas.DiffOut, tags=["documents"])
def diff_revisions(
    session: SessionDep, document_id: int, old: int | None = None, new: int | None = None
) -> schemas.DiffOut:
    """Unified diff between two revisions (default: the latest and the one before it)."""
    document = get_document(session, document_id)
    newer = get_revision(session, document, new)
    older = get_revision(session, document, old if old is not None else max(1, newer.revision - 1))
    label, _, _ = convert.describe(document)
    lines = difflib.unified_diff(
        older.yaml_text.splitlines(keepends=True),
        newer.yaml_text.splitlines(keepends=True),
        f"{label}@{older.revision}",
        f"{label}@{newer.revision}",
    )
    return schemas.DiffOut(document_id=document_id, old=older.revision, new=newer.revision, diff="".join(lines))


@router.post(
    "/documents/{document_id}/revisions/{revision}/restore", response_model=schemas.SaveResult, tags=["documents"]
)
def restore_revision(
    session: SessionDep, document_id: int, revision: int, body: schemas.RestoreRequest | None = None
) -> schemas.SaveResult:
    """Save an earlier revision's text as a new revision (validated like any edit)."""
    document = get_document(session, document_id)
    owner = address_of(document)
    if owner is None:
        raise Conflict("rule documents are read-only here: edit data/rules and run `northward db seed`")
    text = get_revision(session, document, revision).yaml_text
    note = (body.note if body else None) or f"restore revision {revision}"
    return _save(session, owner[0], {str(owner[1]): text}, note)


# --- scenarios ---------------------------------------------------------------------------------------------------


@router.get("/profiles/{profile}/scenarios", response_model=list[schemas.ScenarioOut], tags=["scenarios"])
def list_scenarios(session: SessionDep, profile: str, deleted: bool = False) -> list[schemas.ScenarioOut]:
    found = ProfileRepo(session).get(profile)
    scenarios = ScenarioRepo(session).list(found, include_archived=deleted)
    return [convert.scenario_out(session, found, s) for s in scenarios]


@router.post(
    "/profiles/{profile}/scenarios", response_model=schemas.ScenarioDetail, status_code=201, tags=["scenarios"]
)
def create_scenario(session: SessionDep, profile: str, body: schemas.ScenarioCreate) -> schemas.ScenarioDetail:
    """A new scenario from content, or a clone of another (`clone_from`)."""
    found = ProfileRepo(session).get(profile)
    scenarios = ScenarioRepo(session)
    if (body.clone_from is None) == (body.content is None):
        raise ValueError("give exactly one of clone_from or content")
    if body.clone_from is not None:
        scenario = scenarios.clone(found, body.clone_from, body.name, body.note)
    else:
        if scenarios.find(found, body.name, include_archived=True) is not None:
            raise Conflict(f"profile '{profile}' already has a scenario '{body.name}'")
        assert body.content is not None
        address = f"{SCENARIO_PREFIX}{body.name}"
        _save(session, profile, _texts(session, profile, {address: body.content}), body.note)
        scenario = scenarios.get(found, body.name)
    return convert.scenario_out(session, found, scenario, detail=True)


@router.get("/profiles/{profile}/scenarios/{scenario}", response_model=schemas.ScenarioDetail, tags=["scenarios"])
def get_scenario(session: SessionDep, profile: str, scenario: str, deleted: bool = False) -> schemas.ScenarioDetail:
    found = ProfileRepo(session).get(profile)
    return convert.scenario_out(session, found, ScenarioRepo(session).get(found, scenario, deleted), detail=True)


@router.patch("/profiles/{profile}/scenarios/{scenario}", response_model=schemas.ScenarioDetail, tags=["scenarios"])
def rename_scenario(session: SessionDep, profile: str, scenario: str, body: schemas.Rename) -> schemas.ScenarioDetail:
    found = ProfileRepo(session).get(profile)
    return convert.scenario_out(session, found, ScenarioRepo(session).rename(found, scenario, body.name), detail=True)


@router.delete("/profiles/{profile}/scenarios/{scenario}", status_code=204, tags=["scenarios"])
def delete_scenario(
    session: SessionDep, runs_dir: RunsDirDep, profile: str, scenario: str, purge: bool = False
) -> Response:
    """Delete (archive) a scenario; with `purge=true`, permanently remove an already-deleted one and its runs."""
    found = ProfileRepo(session).get(profile)
    if purge:
        remove_outputs(ScenarioRepo(session).purge(found, scenario), runs_dir)
    else:
        ScenarioRepo(session).archive(found, scenario)
    return Response(status_code=204)


@router.post(
    "/profiles/{profile}/scenarios/{scenario}/restore", response_model=schemas.ScenarioDetail, tags=["scenarios"]
)
def restore_scenario(session: SessionDep, profile: str, scenario: str) -> schemas.ScenarioDetail:
    found = ProfileRepo(session).get(profile)
    return convert.scenario_out(session, found, ScenarioRepo(session).restore(found, scenario), detail=True)


# --- rule sets, schemas, validation ------------------------------------------------------------------------------


@router.get("/rule-sets", response_model=list[schemas.RuleSetOut], tags=["rules"])
def list_rule_sets(session: SessionDep) -> list[schemas.RuleSetOut]:
    return [convert.rule_set_out(session, r) for r in RuleRepo(session).list()]


@router.get("/rule-sets/{name}", response_model=schemas.RuleSetOut, tags=["rules"])
def get_rule_set(session: SessionDep, name: str) -> schemas.RuleSetOut:
    """A rule set by name (its tax year), or `latest`."""
    return convert.rule_set_out(session, RuleRepo(session).get(name))


@router.get("/rule-sets/{name}/documents/{kind}", response_model=schemas.DocumentDetail, tags=["rules"])
def get_rule_document(session: SessionDep, name: str, kind: str) -> schemas.DocumentDetail:
    rules = RuleRepo(session)
    return convert.document_detail(session, rules.document(rules.get(name), kind))


@router.get("/schemas/{kind}", tags=["schemas"])
def get_schema(kind: str) -> dict[str, Any]:
    """The JSON Schema of a document kind (a profile kind, `scenario`, or a rule kind), e.g. to build a form."""
    model = document_model(kind)
    if model is None:
        raise NotFound(f"unknown document kind '{kind}'")
    return model.model_json_schema()


@router.post("/validate", response_model=schemas.ValidateOut, tags=["validation"])
def validate(session: SessionDep, body: schemas.ValidateRequest) -> schemas.ValidateOut:
    """Check one document on its own, or a set of changes to a profile exactly as saving them would (nothing is
    stored)."""
    if body.kind is not None:
        assert body.content is not None
        if document_model(body.kind) is None:
            raise NotFound(f"unknown document kind '{body.kind}'")
        issues = validate_document(
            body.kind, RawDocument(f"{body.kind}.yaml", convert.content_text(body.content, None))
        )
    else:
        assert body.profile is not None and body.changes is not None
        texts = _texts(session, body.profile, body.changes, create=body.create)
        issues = ProfileRepo(session).check(body.profile, texts, create=body.create)
    return schemas.ValidateOut(valid=not issues, issues=[schemas.Issue.of(i) for i in issues])
