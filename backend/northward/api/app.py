"""The FastAPI application (Phase 8). `northward serve` runs it; tests build one with `create_app`.

It's meant for one local user (D17): no authentication, so serve it on localhost only.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.openapi.utils import get_openapi
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic.json_schema import models_json_schema

from northward import __version__
from northward.api import schemas
from northward.api.deps import DatabaseDep
from northward.api.jobs import JobRunner
from northward.api.routes import config, runs
from northward.config.base import ConfigError
from northward.config.loader import document_model
from northward.config.source import PROFILE_KINDS, RULE_KINDS, SCENARIO_KIND
from northward.fingerprint import engine_version
from northward.persistence.db import Database
from northward.persistence.repositories import Conflict, NotFound


def _error(status: int, detail: str, issues: list[schemas.Issue] | None = None) -> JSONResponse:
    return JSONResponse(status_code=status, content=schemas.ErrorOut(detail=detail, issues=issues or []).model_dump())


def _add_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ConfigError)
    async def config_error(_: Request, error: ConfigError) -> JSONResponse:
        issues = [schemas.Issue.of(issue) for issue in error.issues]
        return _error(422, f"{len(issues)} configuration problem(s); nothing was saved", issues)

    @app.exception_handler(NotFound)
    async def not_found(_: Request, error: NotFound) -> JSONResponse:
        return _error(404, str(error.args[0] if error.args else error))

    @app.exception_handler(Conflict)
    async def conflict(_: Request, error: Conflict) -> JSONResponse:
        return _error(409, str(error))

    @app.exception_handler(ValueError)
    async def bad_request(_: Request, error: ValueError) -> JSONResponse:
        return _error(400, str(error))


def document_schemas() -> dict[str, Any]:
    """JSON Schemas of every configuration document model (and the models they use), keyed by model name."""
    kinds = (*PROFILE_KINDS, SCENARIO_KIND, *RULE_KINDS)
    models = [document_model(kind) for kind in kinds]
    _, schema = models_json_schema(
        [(model, "validation") for model in models if model is not None], ref_template="#/components/schemas/{model}"
    )
    return schema["$defs"]


def _openapi(app: FastAPI) -> dict[str, Any]:
    """The API's OpenAPI schema plus the configuration document models, so generated clients get their types."""
    if app.openapi_schema is None:
        spec = get_openapi(title=app.title, version=app.version, description=app.description, routes=app.routes)
        components = spec.setdefault("components", {}).setdefault("schemas", {})
        for name, schema in document_schemas().items():
            if name in components and components[name] != schema:
                raise RuntimeError(f"API schema name '{name}' collides with a configuration model")
            components[name] = schema
        app.openapi_schema = spec
    return app.openapi_schema


def create_app(
    db: Database | None = None,
    runs_dir: Path = Path("var/runs"),
    workers: int | None = None,
    mp_context: str | None = "spawn",
    ui_dir: Path | None = None,
) -> FastAPI:
    """The API over `db` (default: `--db`/`$NORTHWARD_DATABASE_URL`/var/northward.db). Monte Carlo jobs use `workers`
    processes (default: one per CPU; 1 runs in the job thread itself). With `ui_dir` (a built frontend), the app is
    served too, from the same origin."""
    database = db or Database()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        database.check_schema()
        jobs = JobRunner(database, runs_dir, workers, mp_context)
        app.state.jobs = jobs
        jobs.start()
        try:
            yield
        finally:
            jobs.stop()

    app = FastAPI(
        title="Northward",
        version=__version__,
        description="Northward: retirement planning with a year-by-year engine and Monte Carlo simulation.",
        lifespan=lifespan,
        generate_unique_id_function=lambda route: route.name,  # operation ids are the handlers' names
    )
    app.state.db, app.state.runs_dir = database, runs_dir
    _add_error_handlers(app)
    app.include_router(config.router)
    app.include_router(runs.router)

    @app.get("/api/health", response_model=schemas.HealthOut, tags=["meta"])
    def health(db: DatabaseDep) -> schemas.HealthOut:
        where = str(db.sqlite_path) if db.sqlite_path else db.url.render_as_string()
        return schemas.HealthOut(
            status="ok", engine_version=engine_version(), database=where, schema_revision=db.current_revision()
        )

    if ui_dir is not None:
        _serve_ui(app, ui_dir)
    app.openapi = lambda: _openapi(app)  # type: ignore[method-assign]
    return app


def _serve_ui(app: FastAPI, ui_dir: Path) -> None:
    """Serve a built single-page app: its files as they are, and index.html for every other non-API path, so the
    app's own routes (e.g. /runs/12) load it. Registered after the API, so API routes win."""
    root = ui_dir.resolve()
    if not (root / "index.html").is_file():
        raise FileNotFoundError(f"{ui_dir} has no index.html; build the frontend first (make ui)")
    if (root / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=root / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        if path == "api" or path.startswith("api/"):
            raise NotFound(f"no API endpoint /{path}")
        file = (root / path).resolve()
        if path and file.is_file() and file.is_relative_to(root):
            return FileResponse(file)
        return FileResponse(root / "index.html", headers={"Cache-Control": "no-cache"})
