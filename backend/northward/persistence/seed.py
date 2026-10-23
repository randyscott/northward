"""Moving documents between the data/ tree and the database (D14), and backups.

- `seed` is idempotent: rules from `data/rules/` (the master copy) become a new revision whenever their content
  changes, while profiles and scenarios are imported only if the database doesn't have them yet, since the database
  is their master copy once seeded.
- `export` writes the database's latest revisions back out in the data/ layout, byte for byte as stored.
- `backup` is an export plus a consistent copy of the SQLite file.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from northward.config.base import ConfigError, ConfigIssue
from northward.config.loader import check_profile, load_simulation_input
from northward.config.source import LATEST_RULE_SET, PROFILE_KINDS, RULE_KINDS, FileSource
from northward.persistence.db import Database
from northward.persistence.repositories import (
    SCENARIO_PREFIX,
    Address,
    ProfileRepo,
    RuleRepo,
    ScenarioRepo,
    get_revision,
)
from northward.persistence.source import DbSource

SEED_NOTE = "seeded from {root}"


@dataclass
class SeedReport:
    rule_set: str = ""
    rule_set_created: bool = False
    rules_updated: tuple[str, ...] = ()
    profiles_added: list[str] = field(default_factory=list)
    scenarios_added: list[str] = field(default_factory=list)  # "profile/scenario"
    skipped: list[str] = field(default_factory=list)  # already in the database (possibly deleted)
    rejected: dict[str, list[ConfigIssue]] = field(default_factory=dict)  # not imported: their problems
    problems: list[ConfigIssue] = field(default_factory=list)  # stored profiles that the new rules break


def seed(db: Database, root: Path) -> SeedReport:
    """Upsert rules and import missing profiles and scenarios from the data/ tree at `root`."""
    source = FileSource(root)
    report = SeedReport()
    note = SEED_NOTE.format(root=root)
    with db.session() as session:
        upsert = RuleRepo(session).upsert(source, note)  # raises ConfigError for invalid rules
        report.rule_set, report.rule_set_created, report.rules_updated = (
            upsert.rule_set.name,
            upsert.created,
            upsert.changed,
        )

    for profile in source.profiles():
        with db.session() as session:
            repo = ProfileRepo(session)
            existing = repo.find(profile, include_archived=True)
            if existing is None:
                changes = {kind: doc.text for kind in PROFILE_KINDS if (doc := source.profile_document(profile, kind))}
                added = source.scenarios(profile)
            elif existing.archived_at is not None:
                report.skipped.append(f"{profile} (deleted)")
                continue
            else:
                report.skipped.append(profile)
                scenarios = ScenarioRepo(session)
                added = [s for s in source.scenarios(profile) if scenarios.find(existing, s, True) is None]
                report.skipped.extend(f"{profile}/{s}" for s in source.scenarios(profile) if s not in added)
                changes = {}
            for scenario in added:
                doc = source.scenario_document(profile, scenario)
                assert doc is not None
                changes[f"{SCENARIO_PREFIX}{scenario}"] = doc.text
            if not changes:
                continue
            try:
                repo.save(profile, changes, note, create=existing is None)
            except ConfigError as error:
                report.rejected[profile] = error.issues
                continue
        if existing is None:
            report.profiles_added.append(profile)
        report.scenarios_added.extend(f"{profile}/{s}" for s in added)

    if report.rule_set_created or report.rules_updated:
        report.problems = validate_stored(db)
    return report


def validate_stored(db: Database) -> list[ConfigIssue]:
    """Every problem in the stored profiles and scenarios (e.g. after new rules were seeded)."""
    issues: list[ConfigIssue] = []
    with db.session() as session:
        source = DbSource(session)
        for profile in source.profiles():
            issues.extend(check_profile(source, profile))
            for scenario in source.scenarios(profile):
                try:
                    load_simulation_input(source, profile, scenario)
                except ConfigError as error:
                    issues.extend(error.issues)
    return list(dict.fromkeys(issues))


def export(db: Database, out: Path, profiles: list[str] | None = None, rule_set: str = LATEST_RULE_SET) -> list[Path]:
    """Write a rule set (to `rules/`) and the profiles' latest revisions (deleted ones excluded) in the data/ layout."""
    written = []

    def write(relative: str, text: str) -> None:
        path = out / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        written.append(path)

    with db.session() as session:
        rules = RuleRepo(session)
        stored = rules.get(rule_set)
        for kind in RULE_KINDS:
            write(f"rules/{kind}.yaml", get_revision(session, rules.document(stored, kind)).yaml_text)
        repo = ProfileRepo(session)
        selected = [repo.get(name) for name in profiles] if profiles else repo.list()
        for profile in selected:
            for document in profile.documents:
                write(f"profiles/{profile.name}/{document.kind}.yaml", get_revision(session, document).yaml_text)
            for scenario in ScenarioRepo(session).list(profile):
                document = repo.document(profile, Address("scenario", scenario.name))
                write(
                    f"profiles/{profile.name}/scenarios/{scenario.name}.yaml",
                    get_revision(session, document).yaml_text,
                )
    return written


def timestamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def backup(db: Database, out: Path) -> list[Path]:
    """`out/data/` (an export of everything) plus `out/northward.db`, a consistent copy of a SQLite database."""
    written = export(db, out / "data")
    if db.sqlite_path is not None:
        copy = out / "northward.db"
        copy.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(db.sqlite_path)) as live, closing(sqlite3.connect(copy)) as target:
            live.backup(target)
        written.append(copy)
    return written
