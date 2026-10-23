import json

from northward.cli import main
from northward.config.source import PROFILE_KINDS, RULE_KINDS


def test_rule_sets(client):
    (rule_set,) = client.get("/api/rule-sets").json()
    assert rule_set["name"] == "2026" and rule_set["tax_year"] == 2026 and rule_set["latest"]
    assert [d["kind"] for d in rule_set["documents"]] == list(RULE_KINDS)
    assert client.get("/api/rule-sets/latest").json() == client.get("/api/rule-sets/2026").json()
    assert client.get("/api/rule-sets/1999").status_code == 404
    federal = client.get("/api/rule-sets/2026/documents/federal_tax").json()
    assert federal["data"]["metadata"]["base_year"] == 2026 and federal["required"]
    assert client.get("/api/rule-sets/2026/documents/nope").status_code == 404


def test_document_schemas(client):
    schema = client.get("/api/schemas/accounts").json()
    assert schema["title"] == "AccountsDoc" and "accounts" in schema["properties"]
    assert client.get("/api/schemas/scenario").json()["title"] == "ScenarioDoc"
    assert client.get("/api/schemas/nope").status_code == 404


def test_validate_a_single_document(client):
    ok = client.post("/api/validate", json={"kind": "goals", "content": {"data": {"schema_version": 1}}}).json()
    assert ok == {"valid": True, "issues": []}
    bad = client.post("/api/validate", json={"kind": "goals", "content": {"yaml_text": "schema_version: 1\nx: 1\n"}})
    assert bad.status_code == 200 and not bad.json()["valid"]
    assert bad.json()["issues"][0]["message"] == "Extra inputs are not permitted"
    assert client.post("/api/validate", json={"kind": "nope", "content": {"data": {}}}).status_code == 404


def test_validate_changes_without_saving_them(client):
    doc = client.get("/api/profiles/example/documents/accounts").json()
    data = doc["data"]
    data["accounts"][5]["owner"] = "nobody"
    body = client.post("/api/validate", json={"profile": "example", "changes": {"accounts": {"data": data}}}).json()
    assert not body["valid"] and "unknown member 'nobody'" in [i["message"] for i in body["issues"]]
    data["accounts"][5]["owner"] = "joint"
    data["accounts"][5]["balance"] = 1
    good = client.post("/api/validate", json={"profile": "example", "changes": {"accounts": {"data": data}}}).json()
    assert good == {"valid": True, "issues": []}
    assert client.get("/api/profiles/example/documents/accounts").json()["latest"]["revision"] == 1  # nothing saved
    neither = client.post("/api/validate", json={"profile": "example"})
    assert neither.status_code == 422


def test_the_openapi_schema_includes_every_endpoint_and_the_document_models(client):
    spec = client.get("/openapi.json").json()
    paths = set(spec["paths"])
    for path in (
        "/api/validate",
        "/api/profiles",
        "/api/profiles/{profile}",
        "/api/profiles/{profile}/documents/{address}",
        "/api/documents/{document_id}/revisions/{revision}",
        "/api/profiles/{profile}/scenarios/{scenario}",
        "/api/rule-sets/{name}",
        "/api/simulate/deterministic",
        "/api/simulate/montecarlo",
        "/api/runs/{run_id}",
        "/api/runs/{run_id}/results",
        "/api/runs/{run_id}/paths/{path}",
        "/api/compare",
    ):
        assert path in paths, path
    components = spec["components"]["schemas"]
    for model in ("HouseholdDoc", "AccountsDoc", "ScenarioDoc", "FederalTaxDoc", "RunOut", "ProfileDetail"):
        assert model in components, model
    ids = [op["operationId"] for item in spec["paths"].values() for op in item.values()]
    assert len(ids) == len(set(ids)) and "list_profiles" in ids
    # Every $ref resolves.
    refs = {ref.split("/")[-1] for ref in _refs(spec)}
    assert refs <= set(components)


def _refs(node):
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "$ref":
                yield value
            else:
                yield from _refs(value)
    elif isinstance(node, list):
        for item in node:
            yield from _refs(item)


def test_northward_openapi_writes_the_schema(tmp_path, db, capsys):
    out = tmp_path / "openapi.json"
    assert main(["--db", db.url.render_as_string(), "openapi", str(out)]) == 0
    spec = json.loads(out.read_text())
    assert spec["info"]["title"] == "Northward" and len(PROFILE_KINDS) <= len(spec["components"]["schemas"])
