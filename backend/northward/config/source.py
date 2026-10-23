"""Where configuration documents come from. The loader only sees `ConfigSource`, never file paths (PLAN.md D13).

`FileSource` reads the `data/` tree; `MemorySource` holds documents in memory (tests, API validation);
`northward.persistence.source.DbSource` reads the database.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import yaml

RULE_KINDS = (
    "account_types",
    "federal_tax",
    "rmd",
    "contribution_limits",
    "social_security",
    "glide_paths",
    "market_assumptions",
    "state_tax",
    "healthcare",
    "mortality",
    "historical_returns",
)
PROFILE_KINDS = ("household", "accounts", "income", "liabilities", "spending", "events", "health_costs", "goals")
# What each profile document holds (for listings and editors).
PROFILE_KIND_DESCRIPTIONS = {
    "household": "members, dependents, filing status, state of residence",
    "accounts": "account balances, owners, asset strategies",
    "income": "salaries, pensions, other income, payroll elections",
    "liabilities": "amortizing and interest-only debt",
    "spending": "base spending plus phased and periodic categories",
    "events": "one-time events: windfalls, home sales, inheritances",
    "health_costs": "overrides of the default healthcare cost assumptions",
    "goals": "Monte Carlo success criteria and the heirs' tax rate",
}
SCENARIO_KIND = "scenario"
LATEST_RULE_SET = "latest"


@dataclass(frozen=True)
class RawDocument:
    origin: str  # human-readable location used in error messages
    text: str
    revision_id: int | None = None  # the database revision it was read from (None outside the database)


def rule_set_name(federal_tax_text: str) -> str:
    """A rule set is named for its tax year, the `metadata.base_year` of its federal tax rules (PLAN.md D16)."""
    try:
        year = (yaml.safe_load(federal_tax_text) or {})["metadata"]["base_year"]
    except (yaml.YAMLError, KeyError, TypeError) as error:
        raise ValueError("federal_tax.yaml has no metadata.base_year to name its rule set") from error
    if not isinstance(year, int) or isinstance(year, bool):
        raise ValueError("federal_tax.yaml's metadata.base_year must be a year")
    return str(year)


class ConfigSource(Protocol):
    def rules_document(self, kind: str, rule_set: str = LATEST_RULE_SET) -> RawDocument | None: ...

    def profile_document(self, profile: str, kind: str) -> RawDocument | None: ...

    def scenario_document(self, profile: str, scenario: str) -> RawDocument | None: ...

    def profiles(self) -> list[str]: ...

    def scenarios(self, profile: str) -> list[str]: ...


class FileSource:
    """Reads `<root>/rules/<kind>.yaml`, `<root>/profiles/<profile>/<kind>.yaml`, and
    `<root>/profiles/<profile>/scenarios/<scenario>.yaml`. Files hold a single rule set, addressed as "latest" or by
    its name (its tax year)."""

    def __init__(self, root: Path | str):
        self.root = Path(root)

    def rules_document(self, kind: str, rule_set: str = LATEST_RULE_SET) -> RawDocument | None:
        if rule_set != LATEST_RULE_SET and rule_set != self._rule_set_name():
            raise ValueError(f"unknown rule set '{rule_set}' (data/rules holds '{self._rule_set_name()}')")
        return self._read(Path("rules") / f"{kind}.yaml")

    def _rule_set_name(self) -> str | None:
        doc = self._read(Path("rules") / "federal_tax.yaml")
        try:
            return None if doc is None else rule_set_name(doc.text)
        except ValueError:
            return None

    def profile_document(self, profile: str, kind: str) -> RawDocument | None:
        return self._read(Path("profiles") / profile / f"{kind}.yaml")

    def scenario_document(self, profile: str, scenario: str) -> RawDocument | None:
        return self._read(Path("profiles") / profile / "scenarios" / f"{scenario}.yaml")

    def profiles(self) -> list[str]:
        base = self.root / "profiles"
        return sorted(p.name for p in base.iterdir() if p.is_dir()) if base.is_dir() else []

    def scenarios(self, profile: str) -> list[str]:
        base = self.root / "profiles" / profile / "scenarios"
        return sorted(p.stem for p in base.glob("*.yaml"))

    def _read(self, relative: Path) -> RawDocument | None:
        path = self.root / relative
        if not path.is_file():
            return None
        return RawDocument(origin=relative.as_posix(), text=path.read_text())


@dataclass
class MemorySource:
    """Documents held as YAML text: `rules[kind]`, `profile_docs[profile][kind]`, `scenario_docs[profile][name]`."""

    rules: dict[str, str]
    profile_docs: dict[str, dict[str, str]]
    scenario_docs: dict[str, dict[str, str]]

    @classmethod
    def copy_of(cls, source: ConfigSource) -> MemorySource:
        rules = {k: doc.text for k in RULE_KINDS if (doc := source.rules_document(k)) is not None}
        profile_docs: dict[str, dict[str, str]] = {}
        scenario_docs: dict[str, dict[str, str]] = {}
        for profile in source.profiles():
            profile_docs[profile] = {
                k: doc.text for k in PROFILE_KINDS if (doc := source.profile_document(profile, k)) is not None
            }
            scenario_docs[profile] = {
                name: doc.text
                for name in source.scenarios(profile)
                if (doc := source.scenario_document(profile, name)) is not None
            }
        return cls(rules, profile_docs, scenario_docs)

    def rules_document(self, kind: str, rule_set: str = LATEST_RULE_SET) -> RawDocument | None:
        if rule_set != LATEST_RULE_SET:
            raise ValueError(f"memory sources hold one rule set ('{LATEST_RULE_SET}'); '{rule_set}' was requested")
        text = self.rules.get(kind)
        return None if text is None else RawDocument(f"rules/{kind}.yaml", text)

    def profile_document(self, profile: str, kind: str) -> RawDocument | None:
        text = self.profile_docs.get(profile, {}).get(kind)
        return None if text is None else RawDocument(f"profiles/{profile}/{kind}.yaml", text)

    def scenario_document(self, profile: str, scenario: str) -> RawDocument | None:
        text = self.scenario_docs.get(profile, {}).get(scenario)
        return None if text is None else RawDocument(f"profiles/{profile}/scenarios/{scenario}.yaml", text)

    def profiles(self) -> list[str]:
        return sorted(self.profile_docs)

    def scenarios(self, profile: str) -> list[str]:
        return sorted(self.scenario_docs.get(profile, {}))


DocumentKey = tuple[
    str, str, str
]  # ("rules", kind, rule set) | ("profile", profile, kind) | ("scenario", profile, name)


def scope_kind(key: DocumentKey) -> str:
    """The document kind a key addresses, without profile, scenario, or rule set names."""
    scope, a, b = key
    return a if scope == "rules" else b if scope == "profile" else SCENARIO_KIND


@dataclass(frozen=True)
class SnapshotSource:
    """Exactly the documents one load read, so the load can be replayed (e.g. in a worker process)."""

    documents: dict[DocumentKey, RawDocument | None]

    def content_hash(self) -> str:
        """SHA-256 of the documents' contents, ignoring profile, scenario, and rule set names (a rename doesn't
        change the inputs). Absent optional documents count, since they default to empty ones."""
        entries = sorted(
            (key[0], scope_kind(key), "" if doc is None else doc.text, doc is None)
            for key, doc in self.documents.items()
        )
        return hashlib.sha256(json.dumps(entries).encode()).hexdigest()

    def revision_ids(self) -> list[int]:
        """The database revisions read (empty for file or memory sources)."""
        return sorted(doc.revision_id for doc in self.documents.values() if doc and doc.revision_id is not None)

    def rules_document(self, kind: str, rule_set: str = LATEST_RULE_SET) -> RawDocument | None:
        return self.documents.get(("rules", kind, rule_set))

    def profile_document(self, profile: str, kind: str) -> RawDocument | None:
        return self.documents.get(("profile", profile, kind))

    def scenario_document(self, profile: str, scenario: str) -> RawDocument | None:
        return self.documents.get(("scenario", profile, scenario))

    def profiles(self) -> list[str]:
        return sorted({key[1] for key in self.documents if key[0] != "rules"})

    def scenarios(self, profile: str) -> list[str]:
        return sorted(key[2] for key in self.documents if key[0] == "scenario" and key[1] == profile)


class RecordingSource:
    """Wraps a source and records every document read through it."""

    def __init__(self, inner: ConfigSource):
        self.inner = inner
        self.documents: dict[DocumentKey, RawDocument | None] = {}

    def rules_document(self, kind: str, rule_set: str = LATEST_RULE_SET) -> RawDocument | None:
        doc = self.documents[("rules", kind, rule_set)] = self.inner.rules_document(kind, rule_set)
        return doc

    def profile_document(self, profile: str, kind: str) -> RawDocument | None:
        doc = self.documents[("profile", profile, kind)] = self.inner.profile_document(profile, kind)
        return doc

    def scenario_document(self, profile: str, scenario: str) -> RawDocument | None:
        doc = self.documents[("scenario", profile, scenario)] = self.inner.scenario_document(profile, scenario)
        return doc

    def profiles(self) -> list[str]:
        return self.inner.profiles()

    def scenarios(self, profile: str) -> list[str]:
        return self.inner.scenarios(profile)

    def snapshot(self) -> SnapshotSource:
        return SnapshotSource(dict(self.documents))
