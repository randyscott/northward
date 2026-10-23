import math
import subprocess
import threading
import time

import numpy as np
import pytest

from northward.api.convert import json_safe
from northward.config.loader import load_simulation_input
from northward.montecarlo.runner import run_monte_carlo
from northward.persistence import runs
from northward.persistence.repositories import RunRepo
from northward.persistence.source import DbSource
from tests.api.conftest import start_mc, wait_for


@pytest.fixture
def endless_runs(monkeypatch) -> threading.Event:
    """Replace the Monte Carlo engine with one that reports progress until it's stopped; the event is set once it
    has started."""
    started = threading.Event()

    def endless(sim, n_sims, seed, workers=None, progress=None, mp_context=None):
        started.set()
        while True:
            progress(0, n_sims)  # raises when the run is cancelled or the server is stopping
            time.sleep(0.01)

    monkeypatch.setattr(runs, "run_monte_carlo", endless)
    return started


def test_a_deterministic_run_returns_its_table_and_ledger(client):
    response = client.post("/api/simulate/deterministic", json={"profile": "example", "scenario": "base"})
    assert response.status_code == 200
    body = response.json()
    assert body["run"]["kind"] == "deterministic" and body["run"]["status"] == "complete"
    assert body["years"][0]["year"] == 2026 and len(body["years"]) == body["run"]["summary"]["end_year"] - 2025
    assert {"year", "source", "dest", "amount"} <= set(body["ledger"][0])
    quiet = client.post("/api/simulate/deterministic", json={"profile": "example", "scenario": "base", "ledger": False})
    assert quiet.json()["ledger"] == []
    assert (
        client.post("/api/simulate/deterministic", json={"profile": "example", "scenario": "nope"}).status_code == 422
    )


def test_a_monte_carlo_run_is_queued_polled_and_fetched(client):
    queued = start_mc(client)
    assert queued["status"] in ("queued", "running", "complete") and not queued["cached"]
    run = wait_for(client, queued["id"])
    assert run["status"] == "complete" and run["summary"]["n_sims"] == 8 and run["progress"] is None
    assert ("example/accounts", 1) in [tuple(r) for r in run["revisions"]]

    results = client.get(f"/api/runs/{run['id']}/results").json()
    assert 0 <= results["success"]["probability"] <= 1 and set(results["bands"]) >= {"net_worth", "taxable"}
    assert set(results["bands"]["net_worth"]) == {"nominal", "real"}
    few = client.get(f"/api/runs/{run['id']}/results", params={"buckets": ["net_worth"], "bands": True}).json()
    assert list(few["bands"]) == ["net_worth"]
    assert "bands" not in client.get(f"/api/runs/{run['id']}/results?bands=false").json()
    floor = client.get(f"/api/runs/{run['id']}/results?liquidity_floor=100000000").json()
    assert floor["success"]["probability"] == 0.0
    assert client.get(f"/api/runs/{run['id']}/results?buckets=nope").status_code == 400


def test_an_identical_request_is_answered_by_the_stored_run(client):
    first = wait_for(client, start_mc(client)["id"])
    response = client.post("/api/simulate/montecarlo", json={"profile": "example", "scenario": "base", "n_sims": 8})
    assert response.status_code == 200 and response.json()["cached"] and response.json()["id"] == first["id"]
    fresh = start_mc(client, use_cache=False)
    assert fresh["id"] != first["id"]


def test_identical_pending_requests_share_one_run(client, endless_runs):
    first = start_mc(client)
    endless_runs.wait(5)
    again = start_mc(client)
    assert again["id"] == first["id"] and again["status"] == "running" and again["progress"]["total"] == 8
    client.post(f"/api/runs/{first['id']}/cancel")


def test_results_need_a_completed_monte_carlo_run(client, endless_runs):
    run = start_mc(client)
    endless_runs.wait(5)
    assert client.get(f"/api/runs/{run['id']}/results").status_code == 409
    client.post(f"/api/runs/{run['id']}/cancel")
    deterministic = client.post("/api/simulate/deterministic", json={"profile": "example", "scenario": "base"}).json()
    assert client.get(f"/api/runs/{deterministic['run']['id']}/results").status_code == 409
    assert client.get(f"/api/runs/{deterministic['run']['id']}/paths/0").status_code == 409
    assert client.get("/api/runs/999").status_code == 404


def test_drill_down_into_a_path(client):
    run = wait_for(client, start_mc(client, n_sims=4, seed=7)["id"])
    path = client.get(f"/api/runs/{run['id']}/paths/2").json()
    assert (path["run_id"], path["path"], path["seed"]) == (run["id"], 2, 7)
    assert path["years"][0]["year"] == 2026 and path["ledger"]
    assert client.get(f"/api/runs/{run['id']}/paths/2?ledger=false").json()["ledger"] == []
    assert client.get(f"/api/runs/{run['id']}/paths/4").status_code == 400


def test_run_history_is_filtered(client):
    wait_for(client, start_mc(client)["id"])
    client.post("/api/simulate/deterministic", json={"profile": "example", "scenario": "survivor", "ledger": False})
    assert [r["kind"] for r in client.get("/api/runs").json()] == ["deterministic", "monte_carlo"]
    assert [r["scenario"] for r in client.get("/api/runs?kind=monte_carlo").json()] == ["base"]
    assert [r["kind"] for r in client.get("/api/runs?scenario=survivor").json()] == ["deterministic"]
    assert len(client.get("/api/runs?limit=1").json()) == 1
    assert client.get("/api/runs?status=failed").json() == []


def test_cancel_queued_and_running_runs(client, endless_runs):
    running = start_mc(client, seed=1)
    endless_runs.wait(5)
    queued = start_mc(client, seed=2)
    assert queued["status"] == "queued"
    cancelled = client.post(f"/api/runs/{queued['id']}/cancel").json()
    assert (cancelled["status"], cancelled["error"]) == ("failed", "cancelled")
    stopped = client.post(f"/api/runs/{running['id']}/cancel").json()
    assert (stopped["status"], stopped["error"]) == ("failed", "cancelled")
    assert client.post(f"/api/runs/{running['id']}/cancel").status_code == 409


def test_runs_survive_a_server_restart(make_client):
    with make_client() as client:
        run = wait_for(client, start_mc(client)["id"])
        results = client.get(f"/api/runs/{run['id']}/results").json()
    with make_client() as client:  # a new app on the same database: as after a restart
        history = client.get("/api/runs").json()
        assert [r["id"] for r in history] == [run["id"]] and history[0]["status"] == "complete"
        assert client.get(f"/api/runs/{run['id']}").json()["summary"] == run["summary"]
        assert client.get(f"/api/runs/{run['id']}/results").json() == results


def test_stopping_the_server_requeues_the_active_run_and_restarting_resumes_it(
    make_client, db, endless_runs, monkeypatch
):
    with make_client() as client:
        run = start_mc(client)
        endless_runs.wait(5)
    assert runs.get_run(db, run["id"]).status == "queued"
    monkeypatch.undo()  # the real engine again
    with make_client() as client:
        assert wait_for(client, run["id"])["status"] == "complete"


def test_a_run_whose_process_died_is_marked_failed_at_startup(make_client, db):
    with db.session() as session:
        sim = load_simulation_input(DbSource(session), "example", "base")
    info = runs.queue_monte_carlo(db, sim, 8, 1)
    dead = subprocess.Popen(["true"])
    dead.wait()
    with db.session() as session:
        stored = RunRepo(session).get(info.id)
        stored.status, stored.pid = "running", dead.pid
    with make_client() as client:
        run = client.get(f"/api/runs/{info.id}").json()
    assert run["status"] == "failed" and run["error"].startswith("interrupted")


def test_compare_queues_runs_then_returns_the_comparison(client):
    request = {"profile": "example", "scenarios": ["base", "survivor"], "n_sims": 6, "seed": 2}
    first = client.post("/api/compare", json=request)
    assert first.status_code in (200, 202)
    for run in first.json()["runs"]:
        wait_for(client, run["id"])
    done = client.post("/api/compare", json=request)
    assert done.status_code == 200 and done.json()["status"] == "complete"
    rows = done.json()["comparison"]["scenarios"]
    assert [r["scenario"] for r in rows] == ["base", "survivor"]
    assert [r["id"] for r in done.json()["runs"]] == [r["id"] for r in first.json()["runs"]]  # the same runs
    assert client.post("/api/compare", json={**request, "scenarios": ["base"]}).status_code == 422


def test_jobs_run_in_spawned_worker_processes(make_client, db):
    with make_client(workers=2, mp_context="spawn") as client:
        run = wait_for(client, start_mc(client, n_sims=6, seed=4)["id"], timeout=120)
    assert run["status"] == "complete", run["error"]
    info, sim, mc = runs.load_monte_carlo(db, run["id"])
    in_process = run_monte_carlo(sim, 6, 4, workers=1)
    assert np.array_equal(mc.telemetry, in_process.telemetry.astype(np.float32), equal_nan=True)


def test_responses_never_contain_nan():
    assert json_safe({"a": [1.0, math.nan, math.inf], "b": {"c": -math.inf}, "d": "x"}) == {
        "a": [1.0, None, None],
        "b": {"c": None},
        "d": "x",
    }


def test_a_path_carries_its_telemetry_buckets(client):
    run = wait_for(client, start_mc(client, n_sims=4)["id"])
    path = client.get(f"/api/runs/{run['id']}/paths/1").json()
    years = len(path["years"])
    assert set(path["buckets"]) >= {"net_worth", "taxable", "deferred", "federal_tax", "wages", "price_level"}
    assert all(len(values) == years for values in path["buckets"].values())
    assert path["buckets"]["price_level"][0] == 1.0


def test_a_deterministic_run_can_be_reopened(client):
    ran = client.post("/api/simulate/deterministic", json={"profile": "example", "scenario": "base"}).json()
    reopened = client.get(f"/api/runs/{ran['run']['id']}/years").json()
    assert reopened["years"] == ran["years"] and reopened["ledger"] == ran["ledger"]
    assert reopened["buckets"]["net_worth"][-1] == pytest.approx(ran["years"][-1]["net_worth"])
    mc = wait_for(client, start_mc(client, n_sims=2)["id"])
    assert client.get(f"/api/runs/{mc['id']}/years").status_code == 409
