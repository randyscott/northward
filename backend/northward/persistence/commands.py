"""`northward db ...` and `northward runs ...`: the database's schema, seeding, export and backup, document editing and
history, deleting and restoring, and stored runs."""

from __future__ import annotations

import argparse
import difflib
import os
import shlex
import subprocess
import sys
import tempfile
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import yaml
from sqlalchemy.orm import Session

from northward.config.base import ConfigError
from northward.config.loader import REQUIRED_PROFILE_DOCS, SimulationInput
from northward.config.source import PROFILE_KIND_DESCRIPTIONS, PROFILE_KINDS, RULE_KINDS
from northward.fingerprint import engine_version
from northward.montecarlo import telemetry
from northward.persistence import runs
from northward.persistence.db import Database
from northward.persistence.models import Document, DocumentRevision
from northward.persistence.repositories import (
    SCENARIO_PREFIX,
    Address,
    Conflict,
    NotFound,
    ProfileRepo,
    RuleRepo,
    ScenarioRepo,
    get_revision,
    history,
    latest_revision,
)
from northward.persistence.seed import backup, export, seed, timestamp
from northward.persistence.source import profile_origin

NEW_DOCUMENT = "schema_version: 1\n"
# Builds the progress display of a run of a SimulationInput (None: no display).
ProgressFor = Callable[[SimulationInput], Callable[[int, int], None] | None]


def when(moment: datetime | None) -> str:
    """A stored UTC time in local time (SQLite returns naive datetimes)."""
    if moment is None:
        return "-"
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone().strftime("%Y-%m-%d %H:%M")


def _confirm(prompt: str, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        print(f"{prompt} Pass --yes to confirm.", file=sys.stderr)
        return False
    return input(f"{prompt} [y/N] ").strip().lower() in ("y", "yes")


# --- argument parsing ------------------------------------------------------------------------------------------------


def add_db_commands(subparsers: argparse._SubParsersAction) -> None:
    db = subparsers.add_parser("db", help="Manage the database: schema, seed/export/backup, documents, history.")
    commands = db.add_subparsers(dest="db_command", required=True)

    commands.add_parser("init", help="Create the database (and var/) and bring its schema up to date.")
    commands.add_parser("migrate", help="Upgrade the database schema to the latest migration.")

    p = commands.add_parser("seed", help="Upsert rules from data/rules; import profiles and scenarios not yet stored.")
    p.add_argument("data", nargs="?", type=Path, default=Path("data"), help="A data/ tree (default: data).")

    p = commands.add_parser("export", help="Write the stored documents out in the data/ layout.")
    p.add_argument("out", nargs="?", type=Path, help="Output directory (default: var/export/<timestamp>).")
    p.add_argument("--profile", action="append", help="Only this profile (repeatable; default: all).")
    p.add_argument("--rule-set", default="latest", help="Rule set written to rules/ (default: latest).")

    p = commands.add_parser("backup", help="Export everything plus a copy of the SQLite file.")
    p.add_argument("out", nargs="?", type=Path, help="Output directory (default: var/backups/<timestamp>).")

    p = commands.add_parser(
        "list", help="List rule sets, profiles, and scenarios, or (with --profile) a profile's documents."
    )
    p.add_argument("--profile", help="List this profile's documents, including optional ones it doesn't have yet.")
    p.add_argument("--deleted", action="store_true", help="Include deleted (archived) profiles and scenarios.")

    def target(p: argparse.ArgumentParser, rules_too: bool = True) -> None:
        group = p.add_mutually_exclusive_group(required=True)
        group.add_argument("--profile", help="The profile whose document this is.")
        if rules_too:
            group.add_argument("--rule-set", help="A rule set (read-only: data/rules is the master copy).")

    p = commands.add_parser("show", help="Print a document (latest revision, or --revision N).")
    target(p)
    p.add_argument("doc", help="accounts, scenarios/base, ... (or a rule kind with --rule-set)")
    p.add_argument("--revision", type=int)

    p = commands.add_parser("history", help="A document's revisions (or every document's latest).")
    target(p)
    p.add_argument("doc", nargs="?")

    p = commands.add_parser("diff", help="Differences between two revisions (default: the last two).")
    target(p)
    p.add_argument("doc")
    p.add_argument("old", nargs="?", type=int, help="Older revision (default: the one before NEW).")
    p.add_argument("new", nargs="?", type=int, help="Newer revision (default: the latest).")

    p = commands.add_parser("edit", help="Edit documents in $VISUAL/$EDITOR and save them as new revisions.")
    target(p, rules_too=False)
    p.add_argument("doc", nargs="+", help="accounts, scenarios/base, ... (several are validated together)")
    p.add_argument("--note", help="Revision note.")

    p = commands.add_parser("put", help="Save files as new revisions (validated together).")
    target(p, rules_too=False)
    p.add_argument(
        "items", nargs="+", metavar="FILE|DOC=FILE", help="e.g. accounts.yaml, or scenarios/what_if=/tmp/x.yaml"
    )
    p.add_argument("--note", help="Revision note.")
    p.add_argument("--create", action="store_true", help="Create the profile if it doesn't exist.")

    p = commands.add_parser("revert", help="Save an earlier revision's text as a new revision.")
    target(p, rules_too=False)
    p.add_argument("doc")
    p.add_argument("--revision", type=int, required=True)
    p.add_argument("--note")

    p = commands.add_parser("clone", help="Copy a scenario to a new one (its parent).")
    target(p, rules_too=False)
    p.add_argument("scenario")
    p.add_argument("new_name")
    p.add_argument("--note")

    for name, help_text in (
        ("delete", "Delete (archive) a profile or scenario; `restore` brings it back."),
        ("restore", "Restore a deleted profile or scenario."),
        ("purge", "Permanently remove a deleted profile or scenario, with its history and runs."),
    ):
        p = commands.add_parser(name, help=help_text)
        p.add_argument("--profile", required=True)
        p.add_argument("--scenario")
        if name == "purge":
            p.add_argument("--yes", action="store_true", help="Don't ask for confirmation.")


def add_runs_commands(subparsers: argparse._SubParsersAction) -> None:
    group = subparsers.add_parser("runs", help="Stored runs: list, show, and rerun from their pinned inputs.")
    commands = group.add_subparsers(dest="runs_command", required=True)
    p = commands.add_parser("list", help="Recent runs, newest first.")
    p.add_argument("--profile")
    p.add_argument("--scenario")
    p.add_argument("--limit", type=int, default=20)
    p = commands.add_parser("show", help="A run's details, pinned revisions, and headline results.")
    p.add_argument("run_id", type=int)
    p = commands.add_parser("rerun", help="Run again on exactly the pinned revisions, and check the results match.")
    p.add_argument("run_id", type=int)
    p.add_argument("--workers", type=int, help="Worker processes (default: one per CPU).")


# --- db ----------------------------------------------------------------------------------------------------------


def _document(session: Session, args: argparse.Namespace) -> tuple[Document, str]:
    """The document `args.doc` of `--profile` or `--rule-set`, and its label."""
    if getattr(args, "rule_set", None):
        if args.doc not in RULE_KINDS:
            raise NotFound(f"unknown rule kind '{args.doc}' (expected one of {', '.join(RULE_KINDS)})")
        rules = RuleRepo(session)
        rule_set = rules.get(args.rule_set)
        return rules.document(rule_set, args.doc), f"rules[{rule_set.name}]/{args.doc}.yaml"
    repo = ProfileRepo(session)
    address = Address.parse(args.doc)
    return repo.document(repo.get(args.profile), address), profile_origin(args.profile, address)


def _print_revisions(label: str, revisions: list[DocumentRevision]) -> None:
    print(label)
    print(f"  {'rev':>4}  {'saved':<16}  {'hash':<8}  {'schema':<6}  note")
    for r in revisions:
        print(
            f"  {r.revision:>4}  {when(r.created_at):<16}  {r.content_hash[:8]}  v{r.schema_version:<5}  {r.note or ''}"
        )


def _print_saved(profile: str, saved: list[tuple[Address, DocumentRevision]]) -> None:
    if not saved:
        print("No changes: every document matches its latest revision.")
    for address, revision in saved:
        print(f"saved {profile_origin(profile, address)} revision {revision.revision}")


def _print_issues(error: ConfigError) -> None:
    for issue in error.issues:
        print(issue, file=sys.stderr)
    print(f"\nRejected: {len(error.issues)} problem(s); nothing was saved.", file=sys.stderr)


def _scenario_description(text: str) -> str:
    try:
        description = (yaml.safe_load(text) or {}).get("description")
    except (yaml.YAMLError, AttributeError):
        return ""
    return description if isinstance(description, str) else ""


def _db_list_profile(db: Database, args: argparse.Namespace) -> int:
    """Every document a profile can have, with its latest revision, and the profile's scenarios."""
    with db.session() as session:
        repo = ProfileRepo(session)
        profile = repo.get(args.profile, include_archived=args.deleted)
        stored = {d.kind: d for d in profile.documents}
        rows = []
        for kind in PROFILE_KINDS:
            document = stored.get(kind)
            latest = None if document is None else latest_revision(session, document)
            if latest is not None:
                status = f"revision {latest.revision:<3} {when(latest.created_at)}"
            else:
                status = "(missing; required)" if kind in REQUIRED_PROFILE_DOCS else "(none yet; optional)"
            rows.append((kind, status, PROFILE_KIND_DESCRIPTIONS[kind]))
        for scenario in ScenarioRepo(session).list(profile, include_archived=args.deleted):
            latest = get_revision(session, repo.document(profile, Address("scenario", scenario.name), True))
            notes = [f"cloned from {scenario.parent.name}"] if scenario.parent else []
            if scenario.archived_at:
                notes.append(f"deleted {when(scenario.archived_at)}")
            description = _scenario_description(latest.yaml_text)
            extra = f"[{', '.join(notes)}] " if notes else ""
            rows.append(
                (
                    f"{SCENARIO_PREFIX}{scenario.name}",
                    f"revision {latest.revision:<3} {when(latest.created_at)}",
                    extra + description,
                )
            )
    deleted = f"  [deleted {when(profile.archived_at)}]" if profile.archived_at else ""
    print(f"Profile {profile.name}{deleted}")
    name_width = max(len(name) for name, _, _ in rows)
    status_width = max(len(status) for _, status, _ in rows)
    for name, status, description in rows:
        print(f"  {name:<{name_width}}  {status:<{status_width}}  {description}".rstrip())
    print(f"\nView one with `northward db show --profile {profile.name} DOCUMENT`; change it with `northward db edit`.")
    return 0


def _db_list(db: Database, args: argparse.Namespace) -> int:
    if args.profile:
        return _db_list_profile(db, args)
    with db.session() as session:
        rule_sets = RuleRepo(session).list()
        latest = RuleRepo(session).find()
        print("Rule sets:")
        for rule_set in rule_sets:
            mark = " (latest)" if latest is not None and rule_set.id == latest.id else ""
            print(f"  {rule_set.name}{mark}  updated {when(rule_set.updated_at)}  hash {rule_set.source_hash[:8]}")
        print("Profiles:")
        for profile in ProfileRepo(session).list(include_archived=args.deleted):
            deleted = f"  [deleted {when(profile.archived_at)}]" if profile.archived_at else ""
            print(f"  {profile.name}{deleted}")
            for scenario in ScenarioRepo(session).list(profile, include_archived=args.deleted):
                parent = f"  (cloned from {scenario.parent.name})" if scenario.parent else ""
                deleted = f"  [deleted {when(scenario.archived_at)}]" if scenario.archived_at else ""
                print(f"    {SCENARIO_PREFIX}{scenario.name}{parent}{deleted}")
    return 0


def _db_history(db: Database, args: argparse.Namespace) -> int:
    with db.session() as session:
        if args.doc:
            document, label = _document(session, args)
            _print_revisions(label, history(session, document))
            return 0
        if args.rule_set:
            rules = RuleRepo(session)
            rule_set = rules.get(args.rule_set)
            documents = [(f"rules[{rule_set.name}]/{k}.yaml", rules.document(rule_set, k)) for k in RULE_KINDS]
        else:
            repo = ProfileRepo(session)
            profile = repo.get(args.profile)
            documents = [
                (profile_origin(profile.name, d.kind), d) for d in sorted(profile.documents, key=lambda d: d.kind)
            ]
            documents += [
                (
                    profile_origin(profile.name, f"{SCENARIO_PREFIX}{s.name}"),
                    repo.document(profile, Address("scenario", s.name)),
                )
                for s in ScenarioRepo(session).list(profile)
            ]
        width = max(len(label) for label, _ in documents)
        for label, document in documents:
            latest = latest_revision(session, document)
            assert latest is not None
            print(f"{label:<{width}}  revision {latest.revision:<3}  {when(latest.created_at)}  {latest.note or ''}")
    return 0


def _db_diff(db: Database, args: argparse.Namespace) -> int:
    with db.session() as session:
        document, label = _document(session, args)
        new = get_revision(session, document, args.new)
        old_number = args.old if args.old is not None else new.revision - 1
        if old_number < 1:
            print(f"{label} has only revision {new.revision}.")
            return 0
        old = get_revision(session, document, old_number)
        lines = difflib.unified_diff(
            old.yaml_text.splitlines(keepends=True),
            new.yaml_text.splitlines(keepends=True),
            f"{label}@{old.revision}",
            f"{label}@{new.revision}",
        )
        sys.stdout.writelines(lines)
    return 0


def _put_items(items: list[str]) -> dict[str, str]:
    changes = {}
    for item in items:
        doc, sep, file = item.partition("=")
        if not sep:
            path = Path(item)
            doc = f"{SCENARIO_PREFIX}{path.stem}" if path.parent.name == "scenarios" else path.stem
            file = item
        changes[doc] = Path(file).read_text()
    return changes


def _db_edit(db: Database, args: argparse.Namespace, run_editor: Callable[[list[Path]], None]) -> int:
    addresses = [Address.parse(doc) for doc in args.doc]
    with db.session() as session:
        repo = ProfileRepo(session)
        profile = repo.get(args.profile)
        originals = {}
        for address in addresses:
            try:
                originals[address] = get_revision(session, repo.document(profile, address)).yaml_text
            except NotFound:
                originals[address] = NEW_DOCUMENT
    with tempfile.TemporaryDirectory(prefix="northward-edit-") as tmp:
        files = {}
        for address, text in originals.items():
            path = Path(tmp) / "profiles" / args.profile / f"{address}.yaml"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
            files[address] = path
        while True:
            run_editor(list(files.values()))
            changes = {
                str(address): text
                for address, path in files.items()
                if (text := path.read_text()) != originals[address]
            }
            if not changes:
                print("No changes.")
                return 0
            try:
                with db.session() as session:
                    saved = ProfileRepo(session).save(args.profile, changes, args.note)
            except ConfigError as error:
                _print_issues(error)
                if sys.stdin.isatty() and input("Edit again? [Y/n] ").strip().lower() in ("", "y", "yes"):
                    continue
                return 1
            _print_saved(args.profile, saved)
            return 0


def default_editor(paths: list[Path]) -> None:
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or "vi"
    subprocess.run([*shlex.split(editor), *map(str, paths)], check=False)


def _remove_outputs(outputs: list[str], runs_dir: Path) -> None:
    for path in runs.remove_outputs(outputs, runs_dir):
        print(f"kept {path} (outside {runs_dir})")


def _db_lifecycle(db: Database, args: argparse.Namespace) -> int:
    action, name, scenario = args.db_command, args.profile, args.scenario
    what = f"scenario '{scenario}' of profile '{name}'" if scenario else f"profile '{name}'"
    if action == "purge" and not _confirm(f"Permanently remove {what}, its revisions, and its runs?", args.yes):
        return 1
    with db.session() as session:
        profiles = ProfileRepo(session)
        method = "archive" if action == "delete" else action
        if scenario is None:
            outputs = getattr(profiles, method)(name)
        else:
            profile = profiles.get(name, include_archived=True)
            outputs = getattr(ScenarioRepo(session), method)(profile, scenario)
    if action == "purge":
        _remove_outputs(outputs, args.runs_dir)
        print(f"Purged {what}.")
    elif action == "delete":
        restore = f"--profile {name}" + (f" --scenario {scenario}" if scenario else "")
        print(
            f"Deleted {what}. `northward db restore {restore}` brings it back; `northward db purge {restore}` removes it."
        )
    else:
        print(f"Restored {what}.")
    return 0


def _db_seed(db: Database, args: argparse.Namespace) -> int:
    report = seed(db, args.data)
    if report.rule_set_created:
        print(f"Rule set {report.rule_set}: created")
    elif report.rules_updated:
        print(f"Rule set {report.rule_set}: new revisions of {', '.join(report.rules_updated)}")
    else:
        print(f"Rule set {report.rule_set}: unchanged")
    for profile in report.profiles_added:
        print(f"Imported profile {profile}")
    for scenario in report.scenarios_added:
        print(f"Imported scenario {scenario}")
    if report.skipped:
        print(f"Already stored (the database is their master copy): {', '.join(report.skipped)}")
    for profile, issues in report.rejected.items():
        print(f"\nNot imported: {profile}", file=sys.stderr)
        for issue in issues:
            print(f"  {issue}", file=sys.stderr)
    if report.problems:
        print("\nThe new rules leave problems in stored profiles:", file=sys.stderr)
        for issue in report.problems:
            print(f"  {issue}", file=sys.stderr)
    return 1 if report.rejected or report.problems else 0


def db_command(db: Database, args: argparse.Namespace, editor: Callable[[list[Path]], None] = default_editor) -> int:
    command = args.db_command
    if command in ("init", "migrate"):
        before, after = db.migrate()
        where = db.sqlite_path or db.url.render_as_string()
        if before == after:
            print(f"{where}: schema up to date ({after}).")
        else:
            print(f"{where}: schema {'created' if before is None else 'upgraded from ' + before} at {after}.")
            if before is None:
                print("Next: `northward db seed` imports data/rules and data/profiles.")
        return 0
    db.check_schema()
    try:
        if command == "seed":
            return _db_seed(db, args)
        if command == "export":
            out = args.out or Path("var") / "export" / timestamp()
            written = export(db, out, args.profile, args.rule_set)
            print(f"Exported {len(written)} documents to {out}")
            return 0
        if command == "backup":
            out = args.out or Path("var") / "backups" / timestamp()
            written = backup(db, out)
            print(f"Backed up {len(written)} files to {out}")
            return 0
        if command == "list":
            return _db_list(db, args)
        if command == "show":
            with db.session() as session:
                document, _ = _document(session, args)
                sys.stdout.write(get_revision(session, document, args.revision).yaml_text)
            return 0
        if command == "history":
            return _db_history(db, args)
        if command == "diff":
            return _db_diff(db, args)
        if command == "edit":
            return _db_edit(db, args, editor)
        if command == "put":
            with db.session() as session:
                saved = ProfileRepo(session).save(args.profile, _put_items(args.items), args.note, create=args.create)
            _print_saved(args.profile, saved)
            return 0
        if command == "revert":
            with db.session() as session:
                document, label = _document(session, args)
                text = get_revision(session, document, args.revision).yaml_text
                note = args.note or f"revert to revision {args.revision}"
                saved = ProfileRepo(session).save(args.profile, {args.doc: text}, note)
            _print_saved(args.profile, saved)
            return 0
        if command == "clone":
            with db.session() as session:
                profile = ProfileRepo(session).get(args.profile)
                ScenarioRepo(session).clone(profile, args.scenario, args.new_name, args.note)
            print(f"Created {profile_origin(args.profile, SCENARIO_PREFIX + args.new_name)} from {args.scenario}")
            return 0
        return _db_lifecycle(db, args)
    except ConfigError as error:
        _print_issues(error)
        return 1
    except (NotFound, Conflict, ValueError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


# --- runs --------------------------------------------------------------------------------------------------------


def _headline(info: runs.RunInfo) -> str:
    summary = info.summary or {}
    if info.status != "complete":
        return info.error or info.status
    if info.kind == runs.MONTE_CARLO:
        legacy = summary.get("legacy_after_tax", {}).get("real", {}).get("p50")
        success = summary.get("success", {}).get("probability")
        return f"success {success:.1%}, median legacy {legacy:,.0f} (today $)" if legacy is not None else ""
    shortfalls = len(summary.get("shortfall_years", []))
    return f"final net worth {summary.get('final_net_worth_real', 0):,.0f} (today $), {shortfalls} shortfall year(s)"


def runs_command(db: Database, args: argparse.Namespace, progress: ProgressFor) -> int:
    db.check_schema()
    try:
        if args.runs_command == "list":
            found = runs.list_runs(db, args.profile, args.scenario, args.limit)
            if not found:
                print("No runs.")
            for info in found:
                size = f"{info.n_sims:,} paths seed {info.seed}" if info.kind == runs.MONTE_CARLO else "deterministic"
                print(
                    f"#{info.id:<5} {when(info.created_at)}  {info.profile}/{info.scenario:<24} {size:<22} "
                    f"{info.status:<9} {_headline(info)}"
                )
            return 0
        if args.runs_command == "show":
            info = runs.get_run(db, args.run_id)
            print(f"Run #{info.id}: {info.kind} run of {info.profile}/{info.scenario}, {info.status}")
            if info.kind == runs.MONTE_CARLO:
                print(f"  {info.n_sims:,} paths, seed {info.seed}")
            print(f"  started {when(info.created_at)}, finished {when(info.finished_at)}", end="")
            print(f" ({info.elapsed_seconds:.1f} s)" if info.elapsed_seconds is not None else "")
            print(f"  engine {info.engine_version}, inputs {info.input_hash[:12]}")
            print(f"  output {info.output_dir or '-'}")
            print(f"  {_headline(info)}")
            print("  pinned revisions:")
            for label, revision in info.revisions:
                print(f"    {label} @ {revision}")
            return 0
        return _rerun(db, args, progress)
    except NotFound as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


def _rerun(db: Database, args: argparse.Namespace, progress: ProgressFor) -> int:
    original = runs.get_run(db, args.run_id)
    if original.status != "complete" or original.output_dir is None:
        print(f"error: run #{original.id} didn't complete, so there's nothing to compare with", file=sys.stderr)
        return 1
    _, sim = runs.load_run_input(db, args.run_id)
    if original.engine_version != engine_version():
        print(f"note: run #{original.id} used engine {original.engine_version}; this is {engine_version()}")
    if original.kind == runs.MONTE_CARLO:
        assert original.n_sims is not None and original.seed is not None
        info, mc, _ = runs.monte_carlo(
            db,
            sim,
            original.n_sims,
            original.seed,
            args.runs_dir,
            workers=args.workers,
            use_cache=False,
            progress=progress(sim),
        )
        before = telemetry.load(Path(original.output_dir or "") / "telemetry.npz").telemetry
        same = before.shape == mc.telemetry.shape and np.array_equal(
            before, mc.telemetry.astype(np.float32).astype(np.float64), equal_nan=True
        )
    else:
        info, _, written = runs.deterministic(db, sim, args.runs_dir)
        before_dir = original.output_dir or Path()
        same = all(
            (before_dir / p.name).is_file() and (before_dir / p.name).read_bytes() == p.read_bytes() for p in written
        )
    print(f"Reran #{original.id} as run #{info.id} on its pinned revisions -> {info.output_dir}")
    print("Results are identical." if same else f"Results differ from run #{original.id}.")
    return 0 if same else 1
