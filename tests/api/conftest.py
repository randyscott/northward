import time
from collections.abc import Callable, Iterator

import pytest
from fastapi.testclient import TestClient

from northward.api.app import create_app
from northward.persistence.db import Database


@pytest.fixture
def make_client(db: Database, tmp_path) -> Iterator[Callable[..., TestClient]]:
    """Build API clients on the seeded example database. Monte Carlo runs in the job thread (workers=1) unless
    `workers` is given. Leaving the client's `with` block stops the app (and its job runner)."""

    def make(workers: int = 1, mp_context: str | None = None) -> TestClient:
        return TestClient(create_app(db, tmp_path / "runs", workers=workers, mp_context=mp_context))

    yield make


@pytest.fixture
def client(make_client) -> Iterator[TestClient]:
    with make_client() as test_client:
        yield test_client


def wait_for(client: TestClient, run_id: int, timeout: float = 60) -> dict:
    """Poll a run until it's complete or failed."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        run = client.get(f"/api/runs/{run_id}").json()
        if run["status"] in ("complete", "failed"):
            return run
        time.sleep(0.05)
    raise AssertionError(f"run {run_id} didn't finish in {timeout} s")


def start_mc(client: TestClient, scenario: str = "base", n_sims: int = 8, seed: int = 1, **extra) -> dict:
    response = client.post(
        "/api/simulate/montecarlo",
        json={"profile": "example", "scenario": scenario, "n_sims": n_sims, "seed": seed, **extra},
    )
    assert response.status_code in (200, 202), response.text
    return response.json()
