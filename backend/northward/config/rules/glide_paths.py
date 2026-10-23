"""Target-date glide paths (PLAN.md §4.2)."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from northward.config.base import Document, Identifier, Rate, StrictModel


class PostTarget(StrictModel):
    years_after: int = Field(gt=0)
    final_equity: Rate


class NonEquitySplit(StrictModel):
    bonds: Rate
    cash: Rate

    @model_validator(mode="after")
    def _check_sum(self) -> NonEquitySplit:
        if abs(self.bonds + self.cash - 1) > 1e-9:
            raise ValueError(f"bonds + cash must equal 1 (got {self.bonds + self.cash:g})")
        return self


class GlidePath(StrictModel):
    """Equity share: `start_equity` until `years_before` the target, linear to `target_equity` at the target year,
    then flat (or linear to `post_target.final_equity` over `post_target.years_after`)."""

    id: Identifier
    kind: Literal["linear"] = "linear"
    start_equity: Rate
    years_before: int = Field(gt=0)
    target_equity: Rate
    post_target: PostTarget | None = None
    non_equity: NonEquitySplit


class GlidePathsDoc(Document):
    glide_paths: tuple[GlidePath, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_unique(self) -> GlidePathsDoc:
        ids = [g.id for g in self.glide_paths]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"glide path ids must be unique; duplicated: {', '.join(duplicates)}")
        return self

    def get(self, glide_path_id: str) -> GlidePath | None:
        return next((g for g in self.glide_paths if g.id == glide_path_id), None)
