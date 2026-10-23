import shlex
import shutil
import sys

import pytest

from northward.cli import main
from northward.config.source import PROFILE_KINDS


@pytest.fixture
def cli(tmp_path, seeded_template, capsys):
    """Run `northward` against a seeded copy of the example database; returns (exit code, stdout, stderr)."""
    shutil.copy(seeded_template, tmp_path / "northward.db")
    prefix = ["--db", f"sqlite:///{tmp_path / 'northward.db'}", "--runs-dir", str(tmp_path / "runs")]

    def run(*args: str) -> tuple[int, str, str]:
        code = main([*prefix, *args])
        captured = capsys.readouterr()
        return code, captured.out, captured.err

    return run


def editor(tmp_path, monkeypatch, old: str, new: str) -> None:
    """Point $EDITOR at a script that replaces `old` with `new` in each file it's given."""
    script = tmp_path / "editor.py"
    script.write_text(
        "import sys, pathlib\n"
        "for name in sys.argv[1:]:\n"
        "    p = pathlib.Path(name)\n"
        f"    p.write_text(p.read_text().replace({old!r}, {new!r}))\n"
    )
    monkeypatch.setenv("EDITOR", f"{shlex.quote(sys.executable)} {shlex.quote(str(script))}")
    monkeypatch.delenv("VISUAL", raising=False)


def test_without_a_database_commands_explain_what_to_do(tmp_path, capsys):
    assert main(["--db", f"sqlite:///{tmp_path / 'none.db'}", "validate"]) == 1
    assert "run `northward db init` and `northward db seed`, or pass --data-dir" in capsys.readouterr().err


def test_init_and_seed_a_new_database(tmp_path, example_data, capsys):
    db = ["--db", f"sqlite:///{tmp_path / 'var' / 'new.db'}"]
    assert main([*db, "db", "init"]) == 0
    assert "schema created at 0002" in capsys.readouterr().out
    assert main([*db, "db", "seed", str(example_data)]) == 0
    out = capsys.readouterr().out
    assert "Rule set 2026: created" in out and "Imported profile example" in out
    assert main([*db, "db", "seed", str(example_data)]) == 0
    assert "Rule set 2026: unchanged" in capsys.readouterr().out
    assert main([*db, "db", "migrate"]) == 0
    assert "schema up to date (0002)" in capsys.readouterr().out


def test_list_validate_and_show_config(cli):
    code, out, _ = cli("db", "list")
    assert code == 0 and "2026 (latest)" in out and "    scenarios/survivor" in out
    assert cli("validate")[1].startswith("OK: 4 scenario(s) across 1 profile(s)")
    assert (
        "Profile 'example', scenario 'survivor'"
        in cli("show-config", "--profile", "example", "--scenario", "survivor")[1]
    )


def test_show_history_and_diff_documents(cli):
    code, out, _ = cli("db", "show", "--profile", "example", "scenarios/base")
    assert code == 0 and out.startswith("schema_version: 1\ndescription:")
    assert cli("db", "show", "--rule-set", "2026", "rmd")[1].startswith("# ")
    code, out, _ = cli("db", "history", "--profile", "example")
    assert "profiles/example/accounts.yaml" in out and "profiles/example/scenarios/survivor.yaml" in out
    assert "seeded from" in out
    assert "has only revision 1" in cli("db", "diff", "--profile", "example", "accounts")[1]
    code, _, err = cli("db", "show", "--profile", "example", "nonsense")
    assert code == 1 and "unknown document 'nonsense'" in err


def test_edit_saves_a_new_revision_and_rejects_invalid_changes(cli, tmp_path, monkeypatch):
    editor(tmp_path, monkeypatch, "target_retirement_age: 62", "target_retirement_age: 58")
    code, out, _ = cli("db", "edit", "--profile", "example", "household", "--note", "retire earlier")
    assert code == 0 and "saved profiles/example/household.yaml revision 2" in out
    code, out, _ = cli("db", "diff", "--profile", "example", "household")
    assert "-    target_retirement_age: 62\n+    target_retirement_age: 58" in out
    assert "retire earlier" in cli("db", "history", "--profile", "example", "household")[1]

    editor(tmp_path, monkeypatch, "birth_month: 9", "birth_month: 13")
    code, _, err = cli("db", "edit", "--profile", "example", "household")
    assert code == 1 and "Input should be less than or equal to 12" in err and "nothing was saved" in err

    editor(tmp_path, monkeypatch, "nothing to find", "")
    assert cli("db", "edit", "--profile", "example", "household")[1] == "No changes.\n"


def test_put_revert_and_clone(cli, tmp_path):
    code, out, _ = cli("db", "show", "--profile", "example", "accounts")
    edited = tmp_path / "accounts.yaml"
    edited.write_text(out.replace("balance: 150000", "balance: 175000"))
    assert "accounts.yaml revision 2" in cli("db", "put", "--profile", "example", str(edited))[1]
    assert "accounts.yaml revision 3" in cli("db", "revert", "--profile", "example", "accounts", "--revision", "1")[1]
    assert "balance: 150000" in cli("db", "show", "--profile", "example", "accounts")[1]
    assert "revert to revision 1" in cli("db", "history", "--profile", "example", "accounts")[1]

    code, out, _ = cli("db", "clone", "--profile", "example", "base", "what_if")
    assert code == 0 and "Created profiles/example/scenarios/what_if.yaml from base" in out
    assert "scenarios/what_if  (cloned from base)" in cli("db", "list")[1]
    scenario = tmp_path / "draft.yaml"
    scenario.write_text(cli("db", "show", "--profile", "example", "scenarios/base")[1])
    assert (
        "scenarios/draft.yaml revision 1" in cli("db", "put", "--profile", "example", f"scenarios/draft={scenario}")[1]
    )


def test_delete_restore_and_purge(cli):
    assert cli("mc", "--profile", "example", "--scenario", "survivor", "--sims", "4", "--workers", "1")[0] == 0
    out = cli("db", "delete", "--profile", "example", "--scenario", "survivor")[1]
    assert "`northward db restore --profile example --scenario survivor` brings it back" in out
    assert "survivor" not in cli("db", "list")[1] and "[deleted" in cli("db", "list", "--deleted")[1]
    assert (
        cli("db", "restore", "--profile", "example", "--scenario", "survivor")[1]
        == "Restored scenario 'survivor' of profile 'example'.\n"
    )
    cli("db", "delete", "--profile", "example", "--scenario", "survivor")
    code, _, err = cli("db", "purge", "--profile", "example", "--scenario", "survivor")
    assert code == 1 and "Pass --yes to confirm" in err
    code, out, _ = cli("db", "purge", "--profile", "example", "--scenario", "survivor", "--yes")
    assert code == 0 and "Purged" in out
    assert cli("runs", "list")[1] == "No runs.\n"
    code, _, err = cli("db", "purge", "--profile", "example", "--yes")
    assert code == 1 and "must be deleted (archived)" in err


def test_runs_are_recorded_cached_and_reproducible(cli, tmp_path):
    code, out, _ = cli("run", "--profile", "example")
    assert code == 0 and "Deterministic run #1" in out and (tmp_path / "runs" / "1" / "years.csv").is_file()

    mc = ("mc", "--profile", "example", "--sims", "6", "--seed", "3", "--workers", "1")
    code, out, _ = cli(*mc)
    assert code == 0 and "Run #2: 6 paths" in out and "northward run --from-run 2 --path N" in out
    code, out, _ = cli(*mc)
    assert "Stored run #2 from" in out
    assert "Run #3" in cli(*mc, "--no-cache")[1]

    code, out, _ = cli("stats", "2")
    assert code == 0 and "200 paths" not in out and "6 paths, seed 3" in out
    code, out, _ = cli("run", "--from-run", "2", "--path", "4")
    assert code == 0 and "Monte Carlo path 4 of run #2 (seed 3)" in out
    assert (tmp_path / "runs" / "2" / "path-4" / "ledger.csv").is_file()

    code, out, _ = cli("runs", "list")
    assert out.splitlines()[0].startswith("#3") and "deterministic" in out.splitlines()[-1]
    code, out, _ = cli("runs", "show", "2")
    assert "6 paths, seed 3" in out and "example/accounts @ 1" in out and "rules[2026]/rmd @ 1" in out


def test_rerun_reproduces_a_run_after_its_documents_change(cli, tmp_path, monkeypatch):
    assert cli("mc", "--profile", "example", "--sims", "6", "--workers", "1")[0] == 0
    assert cli("run", "--profile", "example")[0] == 0
    editor(tmp_path, monkeypatch, "balance: 150000", "balance: 999999")
    assert cli("db", "edit", "--profile", "example", "accounts")[0] == 0
    for run_id in ("1", "2"):
        code, out, _ = cli("runs", "rerun", run_id)
        assert code == 0 and "Results are identical." in out


def test_compare_uses_and_records_runs(cli):
    args = ("compare", "--profile", "example", "--scenario", "base", "--scenario", "survivor", "--sims", "4")
    code, out, _ = cli(*args, "--workers", "1")
    assert code == 0 and "base: run #1" in out and "survivor: run #2" in out and "Scenario comparison" in out
    assert "survivor: stored run #2" in cli(*args, "--workers", "1")[1]


def test_export_and_backup(cli, tmp_path, example_data):
    code, out, _ = cli("db", "export", str(tmp_path / "export"))
    assert code == 0 and "Exported 22 documents" in out
    assert (tmp_path / "export" / "profiles" / "example" / "scenarios" / "base.yaml").read_bytes() == (
        example_data / "profiles" / "example" / "scenarios" / "base.yaml"
    ).read_bytes()
    code, out, _ = cli("db", "backup", str(tmp_path / "backup"))
    assert code == 0 and (tmp_path / "backup" / "northward.db").is_file()
    assert (tmp_path / "backup" / "data" / "rules" / "rmd.yaml").is_file()


def test_file_mode_still_works_without_a_database(tmp_path, example_data, capsys):
    assert main(["--db", f"sqlite:///{tmp_path / 'none.db'}", "--data-dir", str(example_data), "validate"]) == 0
    assert capsys.readouterr().out.startswith("OK: 4 scenario(s)")
    code = main(["--data-dir", str(example_data), "stats", "1"])
    assert code == 1 and "needs the database" in capsys.readouterr().err


def test_runs_that_cant_be_compared_or_rescored_are_explained(cli, tmp_path):
    assert cli("mc", "--profile", "example", "--sims", "4", "--workers", "1")[0] == 0
    (tmp_path / "runs" / "1" / "telemetry.npz").unlink()
    code, _, err = cli("stats", "1")
    assert code == 1 and "telemetry is missing" in err
    code, _, err = cli("runs", "show", "99")
    assert code == 1 and "unknown run 99" in err


def test_list_a_profiles_documents_including_optional_ones_it_lacks(cli, tmp_path, monkeypatch):
    editor(tmp_path, monkeypatch, "target_retirement_age: 62", "target_retirement_age: 58")
    assert cli("db", "edit", "--profile", "example", "household")[0] == 0
    cli("db", "clone", "--profile", "example", "base", "what_if")
    code, out, _ = cli("db", "list", "--profile", "example")
    lines = out.splitlines()
    assert code == 0 and lines[0] == "Profile example"
    assert [line.split()[0] for line in lines[1:9]] == list(PROFILE_KINDS)
    assert "revision 2" in lines[1] and "members, dependents, filing status" in lines[1]
    health = next(line for line in lines if line.strip().startswith("health_costs"))
    assert "(none yet; optional)" in health and "healthcare cost assumptions" in health
    assert any("scenarios/base" in line and "Baseline for the example household." in line for line in lines)
    assert any("scenarios/what_if" in line and "[cloned from base]" in line for line in lines)
    assert "northward db show --profile example DOCUMENT" in out

    cli("db", "delete", "--profile", "example", "--scenario", "what_if")
    assert "what_if" not in cli("db", "list", "--profile", "example")[1]
    assert "deleted" in cli("db", "list", "--profile", "example", "--deleted")[1]
    code, _, err = cli("db", "list", "--profile", "nobody")
    assert code == 1 and "unknown profile 'nobody'" in err
