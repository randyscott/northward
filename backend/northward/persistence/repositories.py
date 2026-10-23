"""All reads and writes of stored configuration and runs go through these repositories (PLAN.md Phase 7).

Writes are validated before anything is stored: each document against its Pydantic model, then the whole profile and
every scenario of it, loaded as they would be after the change. A change that introduces a problem is rejected with
a `ConfigError`, so an invalid document never lands in the database. (Problems that already existed, e.g. after new
rules were seeded, don't block an edit that leaves them unchanged.)

`ProfileRepo` takes an `owner_user_id` for the per-user scoping of Phase 10 (D17); None means single-user mode.
"""

from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

import yaml
from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from northward.config.base import ConfigError, ConfigIssue
from northward.config.loader import check_profile, load_rules, load_simulation_input, validate_document
from northward.config.source import (
    LATEST_RULE_SET,
    PROFILE_KINDS,
    RULE_KINDS,
    SCENARIO_KIND,
    ConfigSource,
    RawDocument,
    SnapshotSource,
    rule_set_name,
)
from northward.persistence.models import Document, DocumentRevision, Profile, RuleSet, Run, Scenario, utc_now
from northward.persistence.source import DbSource, profile_origin

NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")  # profile and scenario names (they become file and folder names)
SCENARIO_PREFIX = "scenarios/"


class NotFound(LookupError):
    pass


class Conflict(ValueError):
    pass


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


@dataclass(frozen=True)
class Address:
    """A document within a profile, written as in the data/ layout: `accounts`, or `scenarios/<name>`."""

    kind: str  # a profile kind, or "scenario"
    scenario: str | None = None

    @classmethod
    def parse(cls, text: str) -> Address:
        text = text.removesuffix(".yaml")
        if text.startswith(SCENARIO_PREFIX):
            name = text[len(SCENARIO_PREFIX) :]
            if not NAME_PATTERN.match(name):
                raise ValueError(f"invalid scenario name '{name}' (use lowercase letters, digits, and underscores)")
            return cls(SCENARIO_KIND, name)
        if text not in PROFILE_KINDS:
            raise ValueError(
                f"unknown document '{text}' (expected one of {', '.join(PROFILE_KINDS)}, or scenarios/NAME)"
            )
        return cls(text)

    def __str__(self) -> str:
        return f"{SCENARIO_PREFIX}{self.scenario}" if self.scenario else self.kind

    def key(self, profile: str) -> tuple[str, str, str]:
        return ("scenario", profile, self.scenario) if self.scenario else ("profile", profile, self.kind)


# --- revisions -----------------------------------------------------------------------------------------------------


def latest_revision(session: Session, document: Document) -> DocumentRevision | None:
    return session.scalar(
        select(DocumentRevision)
        .where(DocumentRevision.document_id == document.id)
        .order_by(DocumentRevision.revision.desc())
        .limit(1)
    )


def get_revision(session: Session, document: Document, revision: int | None = None) -> DocumentRevision:
    """Revision `revision` of `document`, or its latest when None."""
    found = (
        latest_revision(session, document)
        if revision is None
        else session.scalar(
            select(DocumentRevision).where(
                DocumentRevision.document_id == document.id, DocumentRevision.revision == revision
            )
        )
    )
    if found is None:
        raise NotFound(f"revision {revision} not found" if revision is not None else "the document has no revisions")
    return found


def get_document(session: Session, document_id: int) -> Document:
    document = session.get(Document, document_id)
    if document is None:
        raise NotFound(f"unknown document {document_id}")
    return document


def address_of(document: Document) -> tuple[str, Address] | None:
    """(profile name, address) of a profile or scenario document; None for a rule document."""
    if document.profile is not None:
        return document.profile.name, Address(document.kind)
    if document.scenario is not None:
        return document.scenario.profile.name, Address(SCENARIO_KIND, document.scenario.name)
    return None


def history(session: Session, document: Document) -> list[DocumentRevision]:
    return list(
        session.scalars(
            select(DocumentRevision)
            .where(DocumentRevision.document_id == document.id)
            .order_by(DocumentRevision.revision)
        )
    )


def _append(session: Session, document: Document, text: str, note: str | None) -> DocumentRevision | None:
    """Add revision N+1 (None, and nothing added, when `text` is identical to the latest revision)."""
    latest = latest_revision(session, document) if document.id is not None else None
    digest = content_hash(text)
    if latest is not None and latest.content_hash == digest:
        return None
    revision = DocumentRevision(
        document=document,
        revision=1 if latest is None else latest.revision + 1,
        yaml_text=text,
        schema_version=yaml.safe_load(text)["schema_version"],  # validated before any write
        content_hash=digest,
        note=note,
    )
    session.add(revision)
    session.flush()
    return revision


# --- rules ---------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class RuleUpsert:
    rule_set: RuleSet
    created: bool
    changed: tuple[str, ...]  # kinds that got a new revision


class RuleRepo:
    def __init__(self, session: Session):
        self.session = session

    def list(self) -> list[RuleSet]:
        return list(self.session.scalars(select(RuleSet).order_by(RuleSet.tax_year, RuleSet.name)))

    def find(self, name: str = LATEST_RULE_SET) -> RuleSet | None:
        if name == LATEST_RULE_SET:
            return self.session.scalar(select(RuleSet).order_by(RuleSet.tax_year.desc(), RuleSet.id.desc()).limit(1))
        return self.session.scalar(select(RuleSet).where(RuleSet.name == name))

    def get(self, name: str = LATEST_RULE_SET) -> RuleSet:
        found = self.find(name)
        if found is None:
            raise NotFound(
                "no rule sets in the database; run `northward db seed`"
                if name == LATEST_RULE_SET
                else f"unknown rule set '{name}'"
            )
        return found

    def document(self, rule_set: RuleSet, kind: str) -> Document:
        found = self.session.scalar(select(Document).where(Document.rule_set_id == rule_set.id, Document.kind == kind))
        if found is None:
            raise NotFound(f"rule set '{rule_set.name}' has no '{kind}' document")
        return found

    def upsert(self, source: ConfigSource, note: str | None = None) -> RuleUpsert:
        """Store the source's rules (validated) as the rule set named for their tax year: create it, or add a
        revision to each document whose content changed. Rule files are the master copy (D14)."""
        load_rules(source)  # raises ConfigError
        texts = {kind: doc.text for kind in RULE_KINDS if (doc := source.rules_document(kind)) is not None}
        name = rule_set_name(texts["federal_tax"])
        source_hash = hashlib.sha256("".join(content_hash(texts[k]) for k in sorted(texts)).encode()).hexdigest()
        rule_set = self.find(name)
        created = rule_set is None
        if rule_set is None:
            rule_set = RuleSet(name=name, tax_year=int(name), source_hash=source_hash)
            self.session.add(rule_set)
        changed = []
        for kind, text in texts.items():
            document = (
                None
                if created
                else self.session.scalar(
                    select(Document).where(Document.rule_set_id == rule_set.id, Document.kind == kind)
                )
            )
            if document is None:
                document = Document(kind=kind, rule_set=rule_set)
                self.session.add(document)
            if _append(self.session, document, text, note) is not None:
                changed.append(kind)
        if changed:
            rule_set.source_hash = source_hash
            rule_set.updated_at = utc_now()
        self.session.flush()
        return RuleUpsert(rule_set, created, tuple(changed))


# --- profiles and scenarios ----------------------------------------------------------------------------------------


def _check_name(name: str, what: str) -> None:
    if not NAME_PATTERN.match(name):
        raise ValueError(f"invalid {what} name '{name}' (use lowercase letters, digits, and underscores)")


def _dedupe(issues: Iterable[ConfigIssue]) -> list[ConfigIssue]:
    return list(dict.fromkeys(issues))


class ProfileRepo:
    def __init__(self, session: Session, owner_user_id: int | None = None):
        self.session = session
        self.owner_user_id = owner_user_id

    def _scoped(self, query: Select) -> Select:
        return query if self.owner_user_id is None else query.where(Profile.owner_user_id == self.owner_user_id)

    def list(self, include_archived: bool = False) -> list[Profile]:
        query = self._scoped(select(Profile).order_by(Profile.name))
        if not include_archived:
            query = query.where(Profile.archived_at.is_(None))
        return list(self.session.scalars(query))

    def find(self, name: str, include_archived: bool = False) -> Profile | None:
        profile = self.session.scalar(self._scoped(select(Profile).where(Profile.name == name)))
        return None if profile is None or (profile.archived_at and not include_archived) else profile

    def get(self, name: str, include_archived: bool = False) -> Profile:
        profile = self.find(name, include_archived=True)
        if profile is None:
            raise NotFound(f"unknown profile '{name}'")
        if profile.archived_at and not include_archived:
            raise NotFound(
                f"profile '{name}' is deleted (archived); `northward db restore --profile {name}` brings it back"
            )
        return profile

    def document(self, profile: Profile, address: Address, include_archived: bool = False) -> Document:
        """The document at `address` (NotFound if the profile, scenario, or document doesn't exist)."""
        if address.scenario is not None:
            owner = ScenarioRepo(self.session).get(profile, address.scenario, include_archived)
            found = self.session.scalar(
                select(Document).where(Document.scenario_id == owner.id, Document.kind == SCENARIO_KIND)
            )
        else:
            found = self.session.scalar(
                select(Document).where(Document.profile_id == profile.id, Document.kind == address.kind)
            )
        if found is None:
            raise NotFound(f"profile '{profile.name}' has no '{address}' document")
        return found

    def save(
        self,
        name: str,
        changes: Mapping[str, str],
        note: str | None = None,
        create: bool = False,
    ) -> list[tuple[Address, DocumentRevision]]:
        """Validate `changes` ({address: YAML text}) together and store each as a new revision. Unknown scenarios
        are created; an unknown profile is created only when `create` is set. Unchanged documents are skipped.
        Raises ConfigError (nothing stored) if the change would introduce a configuration problem."""
        issues = self.check(name, changes, create)
        if issues:
            raise ConfigError(issues)
        addressed = {Address.parse(address): text for address, text in changes.items()}
        profile = self.find(name, include_archived=True)
        if profile is None:
            profile = Profile(name=name, owner_user_id=self.owner_user_id)
            self.session.add(profile)
            self.session.flush()
        saved = []
        for address, text in addressed.items():
            document = self._document_for_write(profile, address)
            revision = _append(self.session, document, text, note)
            if revision is not None:
                saved.append((address, revision))
        if saved:
            profile.updated_at = utc_now()
        self.session.flush()
        return saved

    def check(self, name: str, changes: Mapping[str, str], create: bool = False) -> list[ConfigIssue]:
        """The configuration problems saving `changes` would introduce (empty: `save` would accept them). Raises
        NotFound or Conflict when the profile or a scenario can't be written at all."""
        _check_name(name, "profile")
        addressed = {Address.parse(address): text for address, text in changes.items()}
        profile = self.find(name, include_archived=True)
        if profile is None and not create:
            raise NotFound(f"unknown profile '{name}' (create it with --create)")
        if profile is not None and profile.archived_at:
            raise Conflict(f"profile '{name}' is deleted (archived); restore it before editing")
        scenarios = ScenarioRepo(self.session)
        for address in addressed:
            if address.scenario and profile is not None:
                existing = scenarios.find(profile, address.scenario, include_archived=True)
                if existing is not None and existing.archived_at:
                    raise Conflict(f"scenario '{address.scenario}' is deleted (archived); restore it before editing")

        issues = _dedupe(
            issue
            for address, text in addressed.items()
            for issue in validate_document(address.kind, RawDocument(profile_origin(name, address), text))
        )
        if issues:
            return issues
        overlay = {address.key(name): text for address, text in addressed.items()}
        after = self._problems(DbSource(self.session, overlay=overlay, owner_user_id=self.owner_user_id), name)
        if after and profile is not None:
            before = set(self._problems(DbSource(self.session, owner_user_id=self.owner_user_id), name))
            after = [issue for issue in after if issue not in before]
        return after

    def latest_texts(self, profile: Profile) -> dict[str, str]:
        """{address: latest YAML text} of every document of the profile and of its (undeleted) scenarios."""
        texts = {d.kind: get_revision(self.session, d).yaml_text for d in profile.documents}
        for scenario in ScenarioRepo(self.session).list(profile):
            document = self.document(profile, Address(SCENARIO_KIND, scenario.name))
            texts[f"{SCENARIO_PREFIX}{scenario.name}"] = get_revision(self.session, document).yaml_text
        return texts

    def copy(self, name: str, new_name: str, note: str | None = None) -> Profile:
        """A new profile holding the latest revisions of `name`'s documents and scenarios."""
        source = self.get(name)
        if self.find(new_name, include_archived=True) is not None:
            raise Conflict(f"a profile named '{new_name}' already exists")
        self.save(new_name, self.latest_texts(source), note or f"copied from {name}", create=True)
        return self.get(new_name)

    def rename(self, name: str, new_name: str) -> Profile:
        _check_name(new_name, "profile")
        profile = self.get(name)
        if new_name != name and self.find(new_name, include_archived=True) is not None:
            raise Conflict(f"a profile named '{new_name}' already exists")
        profile.name, profile.updated_at = new_name, utc_now()
        self.session.flush()
        return profile

    def _document_for_write(self, profile: Profile, address: Address) -> Document:
        try:
            return self.document(profile, address)
        except NotFound:
            pass
        if address.scenario is None:
            document = Document(kind=address.kind, profile=profile)
        else:
            scenario = ScenarioRepo(self.session).find(profile, address.scenario)
            if scenario is None:
                scenario = Scenario(profile=profile, name=address.scenario)
                self.session.add(scenario)
            document = Document(kind=SCENARIO_KIND, scenario=scenario)
        self.session.add(document)
        return document

    @staticmethod
    def _problems(source: DbSource, name: str) -> list[ConfigIssue]:
        """Every problem in profile `name` and each of its scenarios, as `source` holds them."""
        issues = check_profile(source, name)
        for scenario in source.scenarios(name):
            try:
                load_simulation_input(source, name, scenario)
            except ConfigError as error:
                issues.extend(error.issues)
        return _dedupe(issues)

    def archive(self, name: str) -> Profile:
        profile = self.get(name)
        profile.archived_at = utc_now()
        return profile

    def restore(self, name: str) -> Profile:
        profile = self.get(name, include_archived=True)
        if profile.archived_at is None:
            raise Conflict(f"profile '{name}' isn't deleted")
        profile.archived_at = None
        return profile

    def purge(self, name: str) -> list[str]:
        """Permanently remove an archived profile with its scenarios, revisions, and runs. Returns the runs' output
        directories, for the caller to remove."""
        profile = self.get(name, include_archived=True)
        if profile.archived_at is None:
            raise Conflict(f"profile '{name}' must be deleted (archived) before it can be purged")
        outputs = [run.output_dir for scenario in profile.scenarios for run in scenario.runs if run.output_dir]
        self.session.delete(profile)
        self.session.flush()
        return outputs


class ScenarioRepo:
    def __init__(self, session: Session):
        self.session = session

    def list(self, profile: Profile, include_archived: bool = False) -> list[Scenario]:
        query = select(Scenario).where(Scenario.profile_id == profile.id).order_by(Scenario.name)
        if not include_archived:
            query = query.where(Scenario.archived_at.is_(None))
        return list(self.session.scalars(query))

    def find(self, profile: Profile, name: str, include_archived: bool = False) -> Scenario | None:
        scenario = self.session.scalar(select(Scenario).where(Scenario.profile_id == profile.id, Scenario.name == name))
        return None if scenario is None or (scenario.archived_at and not include_archived) else scenario

    def get(self, profile: Profile, name: str, include_archived: bool = False) -> Scenario:
        scenario = self.find(profile, name, include_archived=True)
        if scenario is None:
            raise NotFound(f"profile '{profile.name}' has no scenario '{name}'")
        if scenario.archived_at and not include_archived:
            raise NotFound(
                f"scenario '{name}' is deleted (archived); "
                f"`northward db restore --profile {profile.name} --scenario {name}` brings it back"
            )
        return scenario

    def clone(self, profile: Profile, name: str, new_name: str, note: str | None = None) -> Scenario:
        """A new scenario starting from `name`'s latest revision, remembering it as its parent."""
        _check_name(new_name, "scenario")
        parent = self.get(profile, name)
        if self.find(profile, new_name, include_archived=True) is not None:
            raise Conflict(f"profile '{profile.name}' already has a scenario '{new_name}'")
        document = ProfileRepo(self.session).document(profile, Address(SCENARIO_KIND, name))
        text = get_revision(self.session, document).yaml_text
        ProfileRepo(self.session).save(
            profile.name, {f"{SCENARIO_PREFIX}{new_name}": text}, note or f"cloned from {name}"
        )
        clone = self.get(profile, new_name)
        clone.parent = parent
        self.session.flush()
        return clone

    def rename(self, profile: Profile, name: str, new_name: str) -> Scenario:
        _check_name(new_name, "scenario")
        scenario = self.get(profile, name)
        if new_name != name and self.find(profile, new_name, include_archived=True) is not None:
            raise Conflict(f"profile '{profile.name}' already has a scenario '{new_name}'")
        scenario.name, scenario.updated_at = new_name, utc_now()
        self.session.flush()
        return scenario

    def archive(self, profile: Profile, name: str) -> Scenario:
        scenario = self.get(profile, name)
        scenario.archived_at = utc_now()
        return scenario

    def restore(self, profile: Profile, name: str) -> Scenario:
        scenario = self.get(profile, name, include_archived=True)
        if scenario.archived_at is None:
            raise Conflict(f"scenario '{name}' isn't deleted")
        scenario.archived_at = None
        return scenario

    def purge(self, profile: Profile, name: str) -> list[str]:
        """Permanently remove an archived scenario with its revisions and runs; returns the runs' output directories."""
        scenario = self.get(profile, name, include_archived=True)
        if scenario.archived_at is None:
            raise Conflict(f"scenario '{name}' must be deleted (archived) before it can be purged")
        outputs = [run.output_dir for run in scenario.runs if run.output_dir]
        self.session.delete(scenario)
        self.session.flush()
        return outputs


# --- runs ----------------------------------------------------------------------------------------------------------


class RunRepo:
    def __init__(self, session: Session):
        self.session = session

    def start(
        self,
        scenario: Scenario,
        kind: str,
        snapshot: SnapshotSource,
        engine_version: str,
        seed: int | None = None,
        n_sims: int | None = None,
        status: str = "running",
    ) -> Run:
        """Record a run (started, or queued), pinned to the revisions its inputs were loaded from."""
        revisions = list(
            self.session.scalars(select(DocumentRevision).where(DocumentRevision.id.in_(snapshot.revision_ids())))
        )
        run = Run(
            scenario=scenario,
            kind=kind,
            seed=seed,
            n_sims=n_sims,
            engine_version=engine_version,
            input_hash=snapshot.content_hash(),
            status=status,
            pid=os.getpid() if status == "running" else None,
            revisions=revisions,
        )
        self.session.add(run)
        self.session.flush()
        return run

    def get(self, run_id: int) -> Run:
        run = self.session.get(Run, run_id)
        if run is None:
            raise NotFound(f"unknown run {run_id}")
        return run

    def list(
        self,
        profile: str | None = None,
        scenario: str | None = None,
        limit: int = 50,
        kind: str | None = None,
        status: str | None = None,
    ) -> list[Run]:
        query = select(Run).join(Scenario).join(Profile).order_by(Run.id.desc()).limit(limit)
        if profile is not None:
            query = query.where(Profile.name == profile)
        if scenario is not None:
            query = query.where(Scenario.name == scenario)
        if kind is not None:
            query = query.where(Run.kind == kind)
        if status is not None:
            query = query.where(Run.status == status)
        return list(self.session.scalars(query))

    def unfinished(self) -> list[Run]:
        """Queued and running runs, oldest first."""
        query = select(Run).where(Run.status.in_(("queued", "running"))).order_by(Run.id)
        return list(self.session.scalars(query))

    def cached(
        self,
        scenario: Scenario,
        kind: str,
        input_hash: str,
        engine_version: str,
        seed: int | None,
        n_sims: int | None,
        statuses: tuple[str, ...] = ("complete",),
    ) -> list[Run]:
        """Runs of `scenario` with exactly these inputs, code, seed, and size (by default completed ones), newest
        first."""
        return list(
            self.session.scalars(
                select(Run)
                .where(
                    Run.scenario_id == scenario.id,
                    Run.kind == kind,
                    Run.input_hash == input_hash,
                    Run.engine_version == engine_version,
                    Run.seed == seed,
                    Run.n_sims == n_sims,
                    Run.status.in_(statuses),
                )
                .order_by(Run.id.desc())
            )
        )

    def source(self, run: Run) -> DbSource:
        """A source holding exactly the revisions `run` read, to reproduce it."""
        return DbSource(self.session, pinned=run.revisions)
