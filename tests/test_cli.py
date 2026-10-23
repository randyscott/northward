import json
import shutil

from northward.cli import main


def test_validate_all(data_dir, capsys):
    assert main(["--data-dir", str(data_dir), "validate"]) == 0
    assert capsys.readouterr().out.startswith("OK: ")


def test_validate_reports_problems(data_dir, tmp_path, capsys):
    shutil.copytree(data_dir, tmp_path / "data")
    household = tmp_path / "data" / "profiles" / "example" / "household.yaml"
    household.write_text(household.read_text().replace("birth_month: 9", "birth_month: 13"))

    assert main(["--data-dir", str(tmp_path / "data"), "validate", "--profile", "example"]) == 1
    err = capsys.readouterr().err
    assert "profiles/example/household.yaml: members[alex].birth_month: Input should be less than or equal to 12" in err


def test_show_config(data_dir, capsys):
    assert main(["--data-dir", str(data_dir), "show-config", "--profile", "example"]) == 0
    out = capsys.readouterr().out
    assert "Profile 'example', scenario 'base'" in out
    assert "sam_529" in out
    assert "Market preset: forward_conservative" in out


def test_run_writes_results(data_dir, tmp_path, capsys):
    out = tmp_path / "out"
    args = ["--data-dir", str(data_dir), "run", "--profile", "example", "--out", str(out)]
    assert main(args) == 0
    printed = capsys.readouterr().out
    assert "Deterministic run: profile 'example'" in printed
    header = (out / "years.csv").read_text().splitlines()[0]
    assert header.startswith("year,residence,age_alex,age_jordan,price_level,gross_wages")
    assert "balance_sam_529" in header and "spending_sam_college" in header
    assert (out / "ledger.csv").read_text().startswith("year,source,dest,amount,description,tax_category")

    assert main([*args[:-2], "--out", str(tmp_path / "json"), "--format", "json", "--no-ledger"]) == 0
    assert (tmp_path / "json" / "years.json").exists() and not (tmp_path / "json" / "ledger.json").exists()


def test_monte_carlo_writes_telemetry_and_statistics(data_dir, tmp_path, capsys):
    out = tmp_path / "mc"
    args = ["--data-dir", str(data_dir), "mc", "--profile", "example", "--sims", "12", "--workers", "2"]
    assert main([*args, "--seed", "3", "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert "Monte Carlo: profile 'example', scenario 'base': 12 paths, seed 3" in printed
    assert "Probability of success:" in printed and "cash + brokerage below 50,000" in printed
    summary = json.loads((out / "summary.json").read_text())
    assert summary["n_sims"] == 12 and summary["goals"]["success"]["liquidity_floor"]["amount"] == 50000
    assert (out / "bands.csv").read_text().startswith("year,bucket,basis,p10,p25,p50,p75,p90")

    # Statistics can be recomputed from the saved telemetry under other criteria, without rerunning.
    assert main(["--data-dir", str(data_dir), "stats", str(out), "--json", "--liquidity-floor", "0"]) == 0
    rescored = json.loads(capsys.readouterr().out)
    assert rescored["goals"]["success"]["liquidity_floor"] is None
    assert rescored["success"]["probability"] >= summary["success"]["probability"]
    assert "liquidity_floor" not in rescored["success"]["failure_probability"]

    # Any path can be re-run with the ledger on.
    path = summary["representative_paths"]["p50"]
    drill = tmp_path / "drill"
    run = ["--data-dir", str(data_dir), "run", "--profile", "example", "--path", str(path), "--seed", "3"]
    assert main([*run, "--out", str(drill)]) == 0
    assert f"Monte Carlo path {path} (seed 3)" in capsys.readouterr().out
    assert (drill / "ledger.csv").exists()


def test_compare_runs_scenarios_on_the_same_draws(data_dir, tmp_path, capsys):
    args = ["--data-dir", str(data_dir), "compare", "--profile", "example", "--sims", "6", "--workers", "1"]
    scenarios = ["--scenario", "base", "--scenario", "early_retire_roth_fill"]
    assert main([*args, *scenarios, "--out", str(tmp_path)]) == 0
    printed = capsys.readouterr().out
    assert "6 paths each, seed 1 (the same draws for every scenario)" in printed
    assert "early_retire_roth_fill: succeeds where base fails" in printed
    comparison = json.loads((tmp_path / "comparison.json").read_text())
    assert [s["scenario"] for s in comparison["scenarios"]] == ["base", "early_retire_roth_fill"]
    assert main([*args, "--scenario", "base"]) == 1
