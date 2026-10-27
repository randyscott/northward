"""Shared building blocks for configuration models: strict base model, common field types, and errors."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Annotated, Any, Generic, TypeVar

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, StringConstraints, ValidationError, WithJsonSchema

T = TypeVar("T")

# Lowercase snake_case identifiers used for ids and cross-references between documents.
Identifier = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*$")]
Money = Annotated[float, Field(ge=0)]
Rate = Annotated[float, Field(ge=0, le=1)]
Year = Annotated[int, Field(ge=1900, le=2200)]
Month = Annotated[int, Field(ge=1, le=12)]
Age = Annotated[float, Field(ge=0, le=125)]

JOINT_OWNER = "joint"

_PERCENT_FRACTION = re.compile(r"^\s*(\d+)\s*/\s*(\d+)\s*%\s*$")


def _parse_percent_fraction(value: Any) -> Any:
    if isinstance(value, str) and (match := _PERCENT_FRACTION.match(value)):
        return int(match[1]) / int(match[2]) / 100
    return value


# A rate that may be written as a number or as a fraction of a percent, e.g. "5/9%" (statutory SSA factors).
FractionalRate = Annotated[
    float,
    BeforeValidator(_parse_percent_fraction),
    Field(ge=0, le=1),
    WithJsonSchema(
        {
            "anyOf": [
                {"type": "number", "minimum": 0, "maximum": 1},
                {"type": "string", "pattern": _PERCENT_FRACTION.pattern},
            ]
        }
    ),
]


def also_accepts(*alternatives: dict[str, Any]) -> Any:
    """`json_schema_extra` for a model or field whose validator converts other inputs first (e.g. a bare number):
    the JSON Schema (used by editors) accepts those inputs too, so valid documents aren't flagged."""

    def widen(schema: dict[str, Any], *_: Any) -> None:
        original = dict(schema)
        description = original.pop("description", None)
        title = original.pop("title", None)
        schema.clear()
        schema["anyOf"] = [original, *alternatives]
        schema.update({k: v for k, v in (("title", title), ("description", description)) if v is not None})

    return widen


class StrictModel(BaseModel):
    """Base for every config model: unknown keys are errors and instances are immutable.

    A docstring under a field becomes its description in the JSON Schema, which the editor shows on hover (and
    tests/config/test_schema_docs.py requires for profile and scenario documents).
    """

    model_config = ConfigDict(extra="forbid", frozen=True, use_attribute_docstrings=True)


class Document(StrictModel):
    """Base for a top-level YAML document. `schema_version` drives upgrades (see `versioning`)."""

    schema_version: int
    """The document format's version. Currently 1 for every document."""


class FilingStatus(str, Enum):
    MARRIED_FILING_JOINTLY = "married_filing_jointly"
    SINGLE = "single"
    MARRIED_FILING_SEPARATELY = "married_filing_separately"
    HEAD_OF_HOUSEHOLD = "head_of_household"
    QUALIFYING_SURVIVING_SPOUSE = "qualifying_surviving_spouse"


class ByFilingStatus(StrictModel, Generic[T]):
    """A value per filing status.

    Qualifying surviving spouse uses the married-filing-jointly value unless `qualifying_surviving_spouse` is given:
    it shares the joint brackets and standard deduction, but several provisions (e.g. the Additional Medicare Tax,
    Social Security taxability, credit phase-outs) treat it as an unmarried filer.
    """

    married_filing_jointly: T
    """The value for married filing jointly."""
    single: T
    """The value for single filers."""
    married_filing_separately: T
    """The value for married filing separately."""
    head_of_household: T
    """The value for head of household."""
    qualifying_surviving_spouse: T | None = None
    """The value for a qualifying surviving spouse. Default: the married-filing-jointly value."""

    def for_status(self, status: FilingStatus) -> T:
        if status is FilingStatus.QUALIFYING_SURVIVING_SPOUSE:
            if self.qualifying_surviving_spouse is not None:
                return self.qualifying_surviving_spouse
            return self.married_filing_jointly
        return getattr(self, status.value)


@dataclass(frozen=True)
class ConfigIssue:
    origin: str  # document the problem was found in, e.g. "profiles/default/accounts.yaml"
    location: str  # dotted path inside the document, e.g. "accounts[alex_ira].owner"
    message: str

    def __str__(self) -> str:
        where = f"{self.origin}: {self.location}" if self.location else self.origin
        return f"{where}: {self.message}"


class ConfigError(Exception):
    """One or more configuration problems, reported together."""

    def __init__(self, issues: list[ConfigIssue]):
        self.issues = issues
        super().__init__("\n".join(str(issue) for issue in issues))


def format_location(loc: tuple[int | str, ...], raw: Any, missing_field: bool = False) -> str:
    """Render a pydantic error location, naming list items by their `id`/`name` when the raw data has one.

    Pydantic inserts discriminated-union tags (e.g. "static_allocation") into locations; they aren't keys in the
    YAML, so a segment absent from the raw data is dropped, except the final segment of a missing-field error.
    """
    parts: list[str] = []
    node = raw
    for i, segment in enumerate(loc):
        is_last = i == len(loc) - 1
        is_tag = isinstance(segment, str) and isinstance(node, dict) and segment not in node
        if is_tag and not (is_last and missing_field):
            continue
        if isinstance(segment, int):
            label = str(segment)
            if isinstance(node, list) and 0 <= segment < len(node):
                node = node[segment]
                if isinstance(node, dict):
                    label = str(node.get("id", node.get("name", segment)))
            else:
                node = None
            parts.append(f"[{label}]")
        else:
            node = node.get(segment) if isinstance(node, dict) else None
            parts.append(f".{segment}" if parts else segment)
    return "".join(parts)


def issues_from_validation_error(error: ValidationError, origin: str, raw: Any, prefix: str = "") -> list[ConfigIssue]:
    issues = []
    for err in error.errors():
        location = format_location(err["loc"], raw, missing_field=err["type"] == "missing")
        if prefix:
            location = f"{prefix}{'.' if location and not location.startswith('[') else ''}{location}"
        message = err["msg"]
        if message.startswith("Value error, "):
            message = message[len("Value error, ") :]
        issues.append(ConfigIssue(origin, location, message))
    return issues
