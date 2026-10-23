"""Request dependencies: the database, a per-request session (committed on success), and the job runner."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from northward.api.jobs import JobRunner
from northward.persistence.db import Database


def _db(request: Request) -> Database:
    return request.app.state.db


def _session(request: Request) -> Iterator[Session]:
    with request.app.state.db.session() as session:
        yield session


def _jobs(request: Request) -> JobRunner:
    return request.app.state.jobs


def _runs_dir(request: Request) -> Path:
    return request.app.state.runs_dir


DatabaseDep = Annotated[Database, Depends(_db)]
SessionDep = Annotated[Session, Depends(_session)]
JobsDep = Annotated[JobRunner, Depends(_jobs)]
RunsDirDep = Annotated[Path, Depends(_runs_dir)]
