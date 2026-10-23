"""The JSON Schemas the editor uses (`GET /api/schemas/{kind}`) must accept every valid document: a model that
converts other input first (e.g. a claiming age written as 67) has to say so in its schema too."""

import jsonschema
import pytest
import yaml

from northward.config.loader import document_model
from northward.config.source import PROFILE_KINDS, RULE_KINDS
from tests.conftest import DATA_DIR

DOCUMENTS = [
    *[(p, p.stem) for p in sorted((DATA_DIR / "rules").glob("*.yaml"))],
    *[(p, p.stem) for p in sorted((DATA_DIR / "profiles" / "example").glob("*.yaml"))],
    *[(p, "scenario") for p in sorted((DATA_DIR / "profiles" / "example" / "scenarios").glob("*.yaml"))],
]


@pytest.mark.parametrize(("path", "kind"), DOCUMENTS, ids=lambda v: getattr(v, "name", v))
def test_committed_documents_satisfy_their_json_schema(path, kind):
    schema = document_model(kind).model_json_schema()
    errors = [
        f"{'.'.join(map(str, e.absolute_path))}: {e.message}"
        for e in jsonschema.Draft202012Validator(schema).iter_errors(yaml.safe_load(path.read_text()))
    ]
    assert errors == []


def test_every_kind_is_covered():
    covered = {kind for _, kind in DOCUMENTS}
    assert set(RULE_KINDS) <= covered and "scenario" in covered
    assert {"household", "accounts", "income", "liabilities", "spending", "events", "goals"} <= covered
    assert set(PROFILE_KINDS) - covered <= {"health_costs"}  # the example has none


@pytest.mark.parametrize(
    ("kind", "data"),
    [
        (
            "scenario",
            {
                "schema_version": 1,
                "rule_set": 2026,
                "horizon": {"start_year": 2026, "end_age": 95},
                "levers": {"ss_claim_ages": {"a": 67, "b": {"years": 66, "months": 6}}},
            },
        ),
        ("liabilities", {"schema_version": 1, "liabilities": None}),
    ],
)
def test_converted_inputs_are_in_the_schema(kind, data):
    model = document_model(kind)
    model.model_validate(data)  # the model accepts it...
    assert (
        list(jsonschema.Draft202012Validator(model.model_json_schema()).iter_errors(data)) == []
    )  # ...so must the schema


def test_the_schema_still_rejects_what_the_model_rejects():
    schema = document_model("scenario").model_json_schema()
    bad = {"schema_version": 1, "horizon": {"start_year": 2026, "end_age": 95}, "levers": {"ss_claim_ages": {"a": 61}}}
    assert list(jsonschema.Draft202012Validator(schema).iter_errors(bad))
