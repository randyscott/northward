"""Request and response bodies of the HTTP API.

Configuration documents themselves aren't redeclared here: they travel as YAML text (`yaml_text`) or as the parsed
data (`data`) the configuration models validate. Those models appear in the OpenAPI schema under their own names (e.g.
`AccountsDoc`), so generated client types describe `data` exactly.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from northward.config.base import ConfigIssue


class Issue(BaseModel):
    origin: str = Field(description="The document, e.g. profiles/default/accounts.yaml.")
    location: str = Field(description="Dotted path inside it, e.g. accounts[ira].owner (empty: the whole document).")
    message: str

    @classmethod
    def of(cls, issue: ConfigIssue) -> Issue:
        return cls(origin=issue.origin, location=issue.location, message=issue.message)


class ErrorOut(BaseModel):
    detail: str
    issues: list[Issue] = Field(default_factory=list, description="Configuration problems (422 responses).")


# --- documents -----------------------------------------------------------------------------------------------------


class Content(BaseModel):
    """A document's new content: YAML text, or structured data merged into the current text so its comments stay."""

    yaml_text: str | None = None
    data: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> Content:
        if (self.yaml_text is None) == (self.data is None):
            raise ValueError("give exactly one of yaml_text or data")
        return self


class BatchItem(Content):
    base_revision: int | None = Field(
        None, description="The revision the edit started from; a newer one makes the save fail with 409."
    )


class DocumentSave(BatchItem):
    note: str | None = None


class BatchSave(BaseModel):
    """Several documents saved together (validated together), keyed by address: `accounts`, `scenarios/base`, ..."""

    changes: dict[str, BatchItem]
    note: str | None = None


class RevisionOut(BaseModel):
    id: int
    document_id: int
    revision: int
    created_at: datetime
    note: str | None
    content_hash: str
    schema_version: int


class RevisionDetail(RevisionOut):
    yaml_text: str
    data: dict[str, Any]


class DocumentOut(BaseModel):
    address: str = Field(description="`accounts`, `scenarios/base`, or a rule kind.")
    kind: str
    id: int | None = Field(description="Null for an optional document the profile doesn't have yet.")
    required: bool
    description: str
    latest: RevisionOut | None


class DocumentDetail(DocumentOut):
    yaml_text: str
    data: dict[str, Any]


class SaveResult(BaseModel):
    saved: list[RevisionOut] = Field(description="New revisions (unchanged documents add none).")


class DiffOut(BaseModel):
    document_id: int
    old: int
    new: int
    diff: str = Field(description="Unified diff of the YAML text.")


class RestoreRequest(BaseModel):
    note: str | None = None


# --- profiles, scenarios, rule sets --------------------------------------------------------------------------------


class ScenarioOut(BaseModel):
    name: str
    description: str | None
    parent: str | None = Field(description="The scenario it was cloned from.")
    document_id: int
    latest: RevisionOut
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


class ScenarioDetail(ScenarioOut):
    yaml_text: str
    data: dict[str, Any]


class ProfileOut(BaseModel):
    name: str
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
    scenarios: list[str]


class ProfileDetail(ProfileOut):
    documents: list[DocumentOut] = Field(description="Every kind a profile can have, in order, present or not.")
    scenario_details: list[ScenarioOut]


class ProfileCreate(BaseModel):
    name: str
    documents: dict[str, Content] = Field(
        default_factory=dict, description="Initial documents by address (at least household, accounts, spending)."
    )
    copy_from: str | None = Field(None, description="Copy another profile's documents and scenarios instead.")
    note: str | None = None


class Rename(BaseModel):
    name: str


class ScenarioCreate(BaseModel):
    name: str
    clone_from: str | None = Field(None, description="Start from this scenario (remembered as the parent).")
    content: Content | None = None
    note: str | None = None


class RuleSetOut(BaseModel):
    name: str
    tax_year: int
    latest: bool
    source_hash: str
    created_at: datetime
    updated_at: datetime
    documents: list[DocumentOut]


# --- validation ----------------------------------------------------------------------------------------------------


class ValidateRequest(BaseModel):
    """Either one document on its own (`kind` + content), or a set of changes to a profile, checked as a save would
    check them (`profile` + `changes`, nothing is stored)."""

    kind: str | None = None
    content: Content | None = None
    profile: str | None = None
    changes: dict[str, Content] | None = None
    create: bool = Field(False, description="With `profile`: check as if creating the profile.")

    @model_validator(mode="after")
    def _one_form(self) -> ValidateRequest:
        single, change = self.kind is not None and self.content is not None, self.profile is not None
        if single == change or (change and not self.changes):
            raise ValueError("give either kind and content, or profile and changes")
        return self


class ValidateOut(BaseModel):
    valid: bool
    issues: list[Issue]


# --- runs ----------------------------------------------------------------------------------------------------------


class Progress(BaseModel):
    done: int
    total: int


class RunOut(BaseModel):
    id: int
    kind: Literal["deterministic", "monte_carlo"]
    profile: str
    scenario: str
    status: Literal["queued", "running", "complete", "failed"]
    seed: int | None
    n_sims: int | None
    engine_version: str
    input_hash: str
    created_at: datetime
    finished_at: datetime | None
    elapsed_seconds: float | None
    error: str | None
    summary: dict[str, Any] | None = Field(description="Headline statistics (Monte Carlo: without bands).")
    revisions: list[tuple[str, int]] = Field(description="Pinned documents and their revision numbers.")
    cached: bool = Field(False, description="This request was answered by an existing identical run.")
    progress: Progress | None = Field(None, description="Paths done so far, while queued or running here.")


class DeterministicRequest(BaseModel):
    profile: str
    scenario: str
    ledger: bool = Field(True, description="Include the transaction ledger.")


class DeterministicOut(BaseModel):
    run: RunOut
    years: list[dict[str, Any]]
    ledger: list[dict[str, Any]]
    warnings: list[str]


class MonteCarloRequest(BaseModel):
    profile: str
    scenario: str
    n_sims: int = Field(5000, ge=1, le=100_000)
    seed: int = 1
    use_cache: bool = Field(True, description="Return an identical stored run instead of running again.")


class GoalOverrides(BaseModel):
    """One-off changes to the profile's success criteria and legacy valuation (no rerun needed)."""

    allow_shortfall: bool = False
    shortfall_tolerance: float | None = Field(None, ge=0)
    liquidity_floor: float | None = Field(None, ge=0, description="Today's dollars; 0 turns the floor off.")
    heirs_tax_rate: float | None = Field(None, ge=0, le=1)


class YearsOut(BaseModel):
    """One simulated path in full: the year table, the ledger, and the telemetry buckets per year."""

    run_id: int
    death_ages: dict[str, float]
    years: list[dict[str, Any]]
    ledger: list[dict[str, Any]]
    warnings: list[str]
    buckets: dict[str, list[float | None]] = Field(
        description="Each telemetry bucket (net_worth, taxable, federal_tax, wages, ...) by year, nominal dollars."
    )


class PathOut(YearsOut):
    path: int
    seed: int


class CompareRequest(GoalOverrides):
    profile: str
    scenarios: list[str] = Field(min_length=2, description="The first is the baseline.")
    n_sims: int = Field(5000, ge=1, le=100_000)
    seed: int = 1


class CompareOut(BaseModel):
    status: Literal["complete", "pending"] = Field(
        description="pending: some runs are still queued or running; POST the same request again to collect them."
    )
    runs: list[RunOut]
    comparison: dict[str, Any] | None


class HealthOut(BaseModel):
    status: Literal["ok"]
    engine_version: str
    database: str
    schema_revision: str | None
