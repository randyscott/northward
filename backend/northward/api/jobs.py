"""Background Monte Carlo runs for the API: one at a time (each already uses every CPU), in a worker thread.

Run state lives in the `runs` table, so it survives a restart: at startup, runs whose process died are marked failed
and queued runs are resumed. Stopping the server puts the active run back in the queue, so it resumes too.
Progress is kept in memory, since only this process can report it.
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

from northward.config.loader import SimulationInput
from northward.persistence import runs
from northward.persistence.db import Database
from northward.persistence.repositories import Conflict
from northward.persistence.runs import RunCancelled, RunInfo, RunInterrupted

log = logging.getLogger(__name__)


class JobRunner:
    def __init__(self, db: Database, runs_dir: Path, workers: int | None = None, mp_context: str | None = "spawn"):
        self.db, self.runs_dir, self.workers, self.mp_context = db, runs_dir, workers, mp_context
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="northward-run")
        self._lock = threading.Lock()
        self._submitting = threading.Lock()  # one find-or-queue at a time, so identical requests share a run
        self._futures: dict[int, Future[None]] = {}
        self._progress: dict[int, tuple[int, int]] = {}
        self._cancelled: set[int] = set()
        self._stopping = False

    def start(self) -> list[int]:
        """Reconcile runs left over from an earlier process and resume the queued ones; returns their ids."""
        queued = runs.reconcile(self.db)
        for run_id in queued:
            info, sim = runs.load_run_input(self.db, run_id)
            self._submit(info, sim)
        return queued

    def stop(self) -> None:
        """Stop taking work; the active run goes back to the queue (resumed at the next start)."""
        with self._lock:
            self._stopping = True
        self._executor.shutdown(wait=True, cancel_futures=True)

    def submit(self, sim: SimulationInput, n_sims: int, seed: int, use_cache: bool = True) -> RunInfo:
        """A Monte Carlo run of `sim`: an identical completed run (if `use_cache`), else an identical one already
        queued or running, else a newly queued one."""
        with self._submitting:
            if use_cache and (done := runs.find_cached(self.db, sim, n_sims, seed)) is not None:
                return done
            pending = runs.find_cached(self.db, sim, n_sims, seed, statuses=("queued", "running"))
            if pending is not None:
                return pending
            info = runs.queue_monte_carlo(self.db, sim, n_sims, seed)
            self._submit(info, sim)
            return info

    def cancel(self, run_id: int) -> RunInfo:
        info = runs.get_run(self.db, run_id)
        if info.status not in ("queued", "running"):
            raise Conflict(f"run {run_id} is {info.status}; only queued or running runs can be cancelled")
        with self._lock:
            future = self._futures.get(run_id)
            self._cancelled.add(run_id)
        if future is not None and future.cancel():  # hadn't started
            self._forget(run_id)
            return runs.cancel_queued(self.db, run_id)
        if future is None and info.status == "queued":  # queued by another process
            return runs.cancel_queued(self.db, run_id)
        if future is not None:
            future.exception()  # wait for the run to stop at its next progress report
        return runs.get_run(self.db, run_id)

    def progress(self, run_id: int) -> tuple[int, int] | None:
        with self._lock:
            return self._progress.get(run_id)

    def _submit(self, info: RunInfo, sim: SimulationInput) -> None:
        assert info.n_sims is not None
        with self._lock:
            self._progress[info.id] = (0, info.n_sims)
            self._futures[info.id] = self._executor.submit(self._execute, info.id, sim)

    def _report(self, run_id: int, done: int, total: int) -> None:
        with self._lock:
            if run_id in self._cancelled:
                raise RunCancelled()
            if self._stopping:
                raise RunInterrupted()
            self._progress[run_id] = (done, total)

    def _execute(self, run_id: int, sim: SimulationInput) -> None:
        try:
            self._report(run_id, 0, self._progress[run_id][1])  # cancelled or stopping before it started
            runs.execute_monte_carlo(
                self.db,
                run_id,
                sim,
                self.runs_dir,
                workers=self.workers,
                mp_context=self.mp_context,
                progress=lambda done, total: self._report(run_id, done, total),
            )
        except RunInterrupted:
            pass  # back in the queue for the next start
        except RunCancelled:
            if runs.get_run(self.db, run_id).status == "queued":  # stopped before execute marked it running
                runs.cancel_queued(self.db, run_id)
        except Exception:
            log.exception("Monte Carlo run %s failed", run_id)
        finally:
            self._forget(run_id)

    def _forget(self, run_id: int) -> None:
        with self._lock:
            self._futures.pop(run_id, None)
            self._progress.pop(run_id, None)
            self._cancelled.discard(run_id)
