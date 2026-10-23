import numpy as np
import pytest

from northward.cli import main
from northward.config.loader import load_simulation_input
from northward.montecarlo import telemetry
from northward.persistence import runs
from northward.persistence.repositories import ProfileRepo
from northward.persistence.source import DbSource


def explode(*args, **kwargs):
    raise RuntimeError("worker crashed")


def load(db, scenario: str = "base"):
    with db.session() as session:
        return load_simulation_input(DbSource(session), "example", scenario)


def edit_accounts(db, old: str = "balance: 150000", new: str = "balance: 250000") -> None:
    with db.session() as session:
        text = DbSource(session).profile_document("example", "accounts").text
        ProfileRepo(session).save("example", {"accounts": text.replace(old, new)}, "edit")


def test_a_monte_carlo_run_is_recorded_with_its_pinned_revisions(db, tmp_path):
    sim = load(db)
    info, mc, summary = runs.monte_carlo(db, sim, 6, 2, tmp_path, workers=1)
    assert not info.cached and info.status == "complete" and info.kind == runs.MONTE_CARLO
    assert (info.n_sims, info.seed, info.profile, info.scenario) == (6, 2, "example", "base")
    assert info.output_dir == (tmp_path / str(info.id)).resolve()
    assert {p.name for p in info.output_dir.iterdir()} == {"telemetry.npz", "summary.json", "bands.csv"}
    assert info.input_hash == sim.snapshot.content_hash()
    assert len(info.revisions) == len(sim.snapshot.revision_ids())
    assert ("example/accounts", 1) in info.revisions and ("rules[2026]/federal_tax", 1) in info.revisions
    assert info.summary["success"]["probability"] == summary["success"]["probability"]
    assert "bands" not in info.summary
    assert runs.get_run(db, info.id) == info


def test_an_identical_request_is_answered_from_the_cache(db, tmp_path):
    first, mc, _ = runs.monte_carlo(db, load(db), 6, 2, tmp_path, workers=1)
    again, cached, _ = runs.monte_carlo(db, load(db), 6, 2, tmp_path, workers=1)
    assert again.cached and again.id == first.id
    assert np.array_equal(cached.telemetry, mc.telemetry.astype(np.float32), equal_nan=True)
    assert len(runs.list_runs(db)) == 1


@pytest.mark.parametrize(
    "change",
    ["seed", "n_sims", "edit", "no_cache", "engine", "telemetry_deleted"],
)
def test_the_cache_is_missed_when_anything_differs(db, tmp_path, monkeypatch, change):
    first, _, _ = runs.monte_carlo(db, load(db), 6, 2, tmp_path, workers=1)
    seed, n_sims, use_cache = 2, 6, True
    if change == "seed":
        seed = 3
    elif change == "n_sims":
        n_sims = 7
    elif change == "edit":
        edit_accounts(db)
    elif change == "no_cache":
        use_cache = False
    elif change == "engine":
        monkeypatch.setattr(runs, "engine_version", lambda: "0.1.0+changed")
    else:
        (first.output_dir / "telemetry.npz").unlink()
    again, _, _ = runs.monte_carlo(db, load(db), n_sims, seed, tmp_path, workers=1, use_cache=use_cache)
    assert not again.cached and again.id != first.id


def test_a_run_pinned_to_revision_n_reproduces_exactly_after_an_edit(db, tmp_path):
    original, mc, _ = runs.monte_carlo(db, load(db), 8, 4, tmp_path, workers=1)
    edit_accounts(db)  # accounts.yaml is now at revision 2
    edited, changed, _ = runs.monte_carlo(db, load(db), 8, 4, tmp_path, workers=1)
    assert not np.array_equal(changed.telemetry, mc.telemetry)
    assert ("example/accounts", 2) in edited.revisions

    info, sim = runs.load_run_input(db, original.id)
    assert info == original and ("example/accounts", 1) in info.revisions
    rerun, again, _ = runs.monte_carlo(db, sim, 8, 4, tmp_path, workers=2, use_cache=False)
    assert rerun.input_hash == original.input_hash and rerun.revisions == original.revisions
    stored = telemetry.load(original.output_dir / "telemetry.npz")
    assert np.array_equal(stored.telemetry, again.telemetry.astype(np.float32), equal_nan=True)


def test_a_deterministic_run_is_recorded(db, tmp_path):
    info, result, written = runs.deterministic(db, load(db), tmp_path)
    assert info.kind == runs.DETERMINISTIC and info.seed is None and info.status == "complete"
    assert [p.name for p in written] == ["years.csv", "ledger.csv"]
    assert info.summary["end_year"] == result.years[-1].year
    assert info.summary["final_net_worth"] == pytest.approx(result.years[-1].net_worth)
    assert info.summary["shortfall_years"] == []
    _, sim = runs.load_run_input(db, info.id)
    assert sim == load(db)


def test_a_failed_run_is_recorded_as_failed(db, tmp_path, monkeypatch):
    monkeypatch.setattr(runs, "run_monte_carlo", explode)
    with pytest.raises(RuntimeError):
        runs.monte_carlo(db, load(db), 6, 2, tmp_path, workers=1)
    (info,) = runs.list_runs(db)
    assert info.status == "failed" and info.error == "RuntimeError: worker crashed"
    monkeypatch.undo()
    retry, _, _ = runs.monte_carlo(db, load(db), 6, 2, tmp_path, workers=1)  # a failed run is never a cache hit
    assert not retry.cached


def test_runs_are_listed_newest_first_and_filtered(db, tmp_path):
    runs.deterministic(db, load(db), tmp_path)
    runs.deterministic(db, load(db, "survivor"), tmp_path)
    assert [r.scenario for r in runs.list_runs(db)] == ["survivor", "base"]
    assert [r.scenario for r in runs.list_runs(db, scenario="base")] == ["base"]
    assert runs.list_runs(db, profile="nobody") == []
    assert len(runs.list_runs(db, limit=1)) == 1


def test_a_failed_run_cant_be_rerun_for_comparison(db, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(runs, "run_monte_carlo", explode)
    with pytest.raises(RuntimeError):
        runs.monte_carlo(db, load(db), 6, 2, tmp_path, workers=1)
    assert main(["--db", db.url.render_as_string(), "runs", "rerun", "1"]) == 1
    assert "didn't complete" in capsys.readouterr().err
