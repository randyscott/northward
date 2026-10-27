"""The documents people edit (and state tax rules, which contributors write) are documented twice: in the JSON Schema
the editor shows on hover (field docstrings) and in docs/configuration/. Every field must have a description, and be
mentioned on its document's page."""

import re
from pathlib import Path

import pytest

from northward.config.loader import document_model

DOCS = Path(__file__).parents[2] / "docs" / "configuration"

# Each kind's page, plus pages whose shared parts it embeds (scenario events are documented with events.yaml).
PAGES = {
    "household": ["household.md"],
    "accounts": ["accounts.md"],
    "income": ["income.md"],
    "spending": ["spending.md"],
    "liabilities": ["liabilities.md"],
    "events": ["events.md", "accounts.md"],
    "health_costs": ["health-costs.md"],
    "goals": ["goals.md"],
    "scenario": ["scenarios.md", "events.md", "accounts.md"],
    "state_tax": ["state-tax.md"],  # the one rules document written for contributors
}


def fields(schema: dict) -> list[tuple[str, str, dict]]:
    """(model, field, field schema) for the document and every model it uses."""
    models = [(schema.get("title", "document"), schema), *schema.get("$defs", {}).items()]
    return [(name, field, spec) for name, model in models for field, spec in model.get("properties", {}).items()]


@pytest.mark.parametrize("kind", PAGES)
def test_every_field_has_a_description(kind):
    schema = document_model(kind).model_json_schema()
    defs = schema.get("$defs", {})

    def described(spec: dict) -> bool:
        if spec.get("description") or "const" in spec:  # a fixed value (a union's `type` or `kind` tag) explains itself
            return True
        # Pydantic leaves out a field description that repeats the referenced model's own.
        refs = [spec, *spec.get("anyOf", [])]
        return any(defs.get(r.get("$ref", "").rsplit("/", 1)[-1], {}).get("description") for r in refs)

    missing = [f"{model}.{field}" for model, field, spec in fields(schema) if not described(spec)]
    assert missing == []


@pytest.mark.parametrize("kind", PAGES)
def test_every_field_is_on_its_page(kind):
    text = "\n".join((DOCS / page).read_text() for page in [*PAGES[kind], "README.md"])
    schema = document_model(kind).model_json_schema()
    text = re.sub(r"```.*?```", "", text, flags=re.S)  # examples don't count; the field must be explained
    # Field names count in code spans (`a.pia_at_fra`) and in headings named after them (### cash_reserve).
    code = " ".join([*re.findall(r"`([^`]*)`", text), *re.findall(r"^#+ (.*)$", text, re.M)])
    missing = sorted({f"{model}.{field}" for model, field, _ in fields(schema) if not re.search(rf"\b{field}\b", code)})
    assert missing == []
