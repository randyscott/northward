"""`DbSource`: the database as a `ConfigSource`, so the loader builds the same `SimulationInput` from it as from files.

It reads the latest revision of every document, unless it is
- `pinned` to a set of revisions (a stored run's inputs, to reproduce the run exactly), or given
- an `overlay` of unsaved texts that stand in for (or add to) the stored ones, used to validate a change before
  it is written.

Origins in error messages follow the data/ layout (`profiles/<profile>/<kind>.yaml`), as with files.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import Session

from northward.config.source import LATEST_RULE_SET, DocumentKey, RawDocument
from northward.persistence.models import Document, DocumentRevision, Profile, RuleSet, Scenario

if TYPE_CHECKING:
    from northward.persistence.repositories import Address


def profile_origin(profile: str, address: Address | str) -> str:
    return f"profiles/{profile}/{address}.yaml"


def _origin(key: DocumentKey) -> str:
    scope, a, b = key
    if scope == "rules":
        return f"rules/{a}.yaml"
    return f"profiles/{a}/{b}.yaml" if scope == "profile" else f"profiles/{a}/scenarios/{b}.yaml"


def revision_key(revision: DocumentRevision) -> DocumentKey:
    """The key a pinned revision answers. Rule documents answer for any rule set name: a run pins one set."""
    document = revision.document
    if document.rule_set is not None:
        return ("rules", document.kind, "")
    if document.profile is not None:
        return ("profile", document.profile.name, document.kind)
    assert document.scenario is not None
    return ("scenario", document.scenario.profile.name, document.scenario.name)


class DbSource:
    def __init__(
        self,
        session: Session,
        pinned: Iterable[DocumentRevision] | None = None,
        overlay: Mapping[DocumentKey, str] | None = None,
        owner_user_id: int | None = None,
    ):
        self.session = session
        self.pinned = None if pinned is None else {revision_key(r): r for r in pinned}
        self.overlay = dict(overlay or {})
        self.owner_user_id = owner_user_id

    # --- ConfigSource ---------------------------------------------------------------------------------------------

    def rules_document(self, kind: str, rule_set: str = LATEST_RULE_SET) -> RawDocument | None:
        key: DocumentKey = ("rules", kind, rule_set)
        if self.pinned is not None:
            return self._pinned(("rules", kind, ""), key)
        found = self._rule_set(rule_set)
        query = select(Document).where(Document.rule_set_id == found.id, Document.kind == kind)
        return self._latest(self.session.scalar(query), key)

    def profile_document(self, profile: str, kind: str) -> RawDocument | None:
        key: DocumentKey = ("profile", profile, kind)
        if key in self.overlay:
            return RawDocument(_origin(key), self.overlay[key])
        if self.pinned is not None:
            return self._pinned(key, key)
        owner = self._profile(profile)
        if owner is None:
            return None
        query = select(Document).where(Document.profile_id == owner.id, Document.kind == kind)
        return self._latest(self.session.scalar(query), key)

    def scenario_document(self, profile: str, scenario: str) -> RawDocument | None:
        key: DocumentKey = ("scenario", profile, scenario)
        if key in self.overlay:
            return RawDocument(_origin(key), self.overlay[key])
        if self.pinned is not None:
            return self._pinned(key, key)
        owner = self._profile(profile)
        if owner is None:
            return None
        query = (
            select(Document)
            .join(Scenario, Document.scenario_id == Scenario.id)
            .where(Scenario.profile_id == owner.id, Scenario.name == scenario, Scenario.archived_at.is_(None))
        )
        return self._latest(self.session.scalar(query), key)

    def profiles(self) -> list[str]:
        if self.pinned is not None:
            stored = {key[1] for key in self.pinned if key[0] != "rules"}
        else:
            query = select(Profile.name).where(Profile.archived_at.is_(None))
            if self.owner_user_id is not None:
                query = query.where(Profile.owner_user_id == self.owner_user_id)
            stored = set(self.session.scalars(query))
        return sorted(stored | {key[1] for key in self.overlay})

    def scenarios(self, profile: str) -> list[str]:
        if self.pinned is not None:
            stored = {key[2] for key in self.pinned if key[0] == "scenario" and key[1] == profile}
        else:
            owner = self._profile(profile)
            stored = (
                set()
                if owner is None
                else set(
                    self.session.scalars(
                        select(Scenario.name).where(Scenario.profile_id == owner.id, Scenario.archived_at.is_(None))
                    )
                )
            )
        added = {key[2] for key in self.overlay if key[0] == "scenario" and key[1] == profile}
        return sorted(stored | added)

    # --- helpers --------------------------------------------------------------------------------------------------

    def _rule_set(self, name: str) -> RuleSet:
        query = select(RuleSet)
        if name == LATEST_RULE_SET:
            query = query.order_by(RuleSet.tax_year.desc(), RuleSet.id.desc()).limit(1)
        else:
            query = query.where(RuleSet.name == name)
        found = self.session.scalar(query)
        if found is None:
            names = ", ".join(self.session.scalars(select(RuleSet.name).order_by(RuleSet.tax_year)))
            if not names:
                raise ValueError("the database has no rule sets; run `northward db seed`")
            raise ValueError(f"unknown rule set '{name}' (the database has {names})")
        return found

    def _profile(self, name: str) -> Profile | None:
        query = select(Profile).where(Profile.name == name, Profile.archived_at.is_(None))
        if self.owner_user_id is not None:
            query = query.where(Profile.owner_user_id == self.owner_user_id)
        return self.session.scalar(query)

    def _latest(self, document: Document | None, key: DocumentKey) -> RawDocument | None:
        if document is None:
            return None
        revision = self.session.scalar(
            select(DocumentRevision)
            .where(DocumentRevision.document_id == document.id)
            .order_by(DocumentRevision.revision.desc())
            .limit(1)
        )
        return None if revision is None else RawDocument(_origin(key), revision.yaml_text, revision.id)

    def _pinned(self, lookup: DocumentKey, key: DocumentKey) -> RawDocument | None:
        assert self.pinned is not None
        revision = self.pinned.get(lookup)
        return None if revision is None else RawDocument(_origin(key), revision.yaml_text, revision.id)
