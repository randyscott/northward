from northward.config.source import PROFILE_KINDS


def test_health(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok" and body["schema_revision"] == "0002" and body["engine_version"].startswith("0.1.0+")


def test_list_and_get_profiles(client):
    assert [(p["name"], p["scenarios"]) for p in client.get("/api/profiles").json()] == [
        ("example", ["base", "early_retire_roth_fill", "historical_lifespans", "survivor"])
    ]
    detail = client.get("/api/profiles/example").json()
    assert [d["address"] for d in detail["documents"]] == list(PROFILE_KINDS)
    health = next(d for d in detail["documents"] if d["kind"] == "health_costs")
    assert health["id"] is None and health["latest"] is None and not health["required"]
    assert "healthcare cost" in health["description"]
    household = detail["documents"][0]
    assert household["required"] and household["latest"]["revision"] == 1
    base = next(s for s in detail["scenario_details"] if s["name"] == "base")
    assert base["description"] == "Baseline for the example household." and base["parent"] is None


def test_unknown_profile_is_404(client):
    response = client.get("/api/profiles/nobody")
    assert response.status_code == 404 and response.json() == {"detail": "unknown profile 'nobody'", "issues": []}


def test_create_a_profile_from_documents(client):
    docs = {
        kind: {"yaml_text": client.get(f"/api/profiles/example/documents/{kind}").json()["yaml_text"]}
        for kind in ("household", "accounts", "spending")
    }
    response = client.post("/api/profiles", json={"name": "fresh", "documents": docs, "note": "new"})
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "fresh" and body["scenarios"] == []
    assert [d["address"] for d in body["documents"] if d["id"] is not None] == ["household", "accounts", "spending"]
    assert client.post("/api/profiles", json={"name": "fresh", "documents": docs}).status_code == 409


def test_creating_a_profile_without_required_documents_is_rejected(client):
    household = client.get("/api/profiles/example/documents/household").json()["yaml_text"]
    response = client.post(
        "/api/profiles", json={"name": "partial", "documents": {"household": {"yaml_text": household}}}
    )
    assert response.status_code == 422
    messages = {(i["origin"], i["message"]) for i in response.json()["issues"]}
    assert ("profiles/partial/accounts.yaml", "required profile document is missing") in messages
    assert client.get("/api/profiles/partial").status_code == 404


def test_copy_a_profile(client):
    response = client.post("/api/profiles", json={"name": "copy", "copy_from": "example"})
    assert response.status_code == 201
    assert response.json()["scenarios"] == client.get("/api/profiles/example").json()["scenarios"]
    original = client.get("/api/profiles/example/documents/accounts").json()["yaml_text"]
    copied = client.get("/api/profiles/copy/documents/accounts").json()
    assert copied["yaml_text"] == original and copied["latest"]["note"] == "copied from example"
    both = client.post(
        "/api/profiles", json={"name": "x", "copy_from": "example", "documents": {"goals": {"data": {}}}}
    )
    assert both.status_code == 400


def test_rename_a_profile(client):
    assert client.patch("/api/profiles/example", json={"name": "renamed"}).json()["name"] == "renamed"
    assert client.get("/api/profiles/example").status_code == 404
    assert client.get("/api/profiles/renamed/documents/accounts").status_code == 200
    assert client.patch("/api/profiles/renamed", json={"name": "Bad Name"}).status_code == 400


def test_delete_restore_and_purge_a_profile(client):
    assert client.delete("/api/profiles/example?purge=true").status_code == 409  # must be deleted first
    assert client.delete("/api/profiles/example").status_code == 204
    assert client.get("/api/profiles").json() == []
    deleted = client.get("/api/profiles?deleted=true").json()
    assert deleted[0]["name"] == "example" and deleted[0]["deleted_at"] is not None
    assert client.get("/api/profiles/example").status_code == 404
    assert client.get("/api/profiles/example?deleted=true").status_code == 200
    assert client.post("/api/profiles/example/restore").json()["deleted_at"] is None
    assert client.delete("/api/profiles/example").status_code == 204
    assert client.delete("/api/profiles/example?purge=true").status_code == 204
    assert client.get("/api/profiles?deleted=true").json() == []


def test_list_get_and_create_scenarios(client):
    names = [s["name"] for s in client.get("/api/profiles/example/scenarios").json()]
    assert names == ["base", "early_retire_roth_fill", "historical_lifespans", "survivor"]
    base = client.get("/api/profiles/example/scenarios/base").json()
    assert base["data"]["horizon"] == {"start_year": 2026, "end_age": 95} and base["yaml_text"].startswith("schema")

    data = dict(base["data"], description="Retire later")
    created = client.post("/api/profiles/example/scenarios", json={"name": "later", "content": {"data": data}})
    assert created.status_code == 201 and created.json()["description"] == "Retire later"
    assert (
        client.post("/api/profiles/example/scenarios", json={"name": "later", "content": {"data": data}}).status_code
        == 409
    )
    neither = client.post("/api/profiles/example/scenarios", json={"name": "empty"})
    assert neither.status_code == 400


def test_clone_rename_delete_and_restore_scenarios(client):
    clone = client.post("/api/profiles/example/scenarios", json={"name": "what_if", "clone_from": "base"}).json()
    assert clone["parent"] == "base" and clone["latest"]["note"] == "cloned from base"
    renamed = client.patch("/api/profiles/example/scenarios/what_if", json={"name": "what_if_2"}).json()
    assert renamed["name"] == "what_if_2" and renamed["parent"] == "base"
    assert client.patch("/api/profiles/example/scenarios/what_if_2", json={"name": "base"}).status_code == 409

    assert client.delete("/api/profiles/example/scenarios/what_if_2").status_code == 204
    assert "what_if_2" not in client.get("/api/profiles/example").json()["scenarios"]
    assert any(s["name"] == "what_if_2" for s in client.get("/api/profiles/example/scenarios?deleted=true").json())
    assert client.get("/api/profiles/example/scenarios/what_if_2").status_code == 404
    assert client.get("/api/profiles/example/scenarios/what_if_2?deleted=true").json()["deleted_at"] is not None
    assert client.post("/api/profiles/example/scenarios/what_if_2/restore").json()["deleted_at"] is None
    client.delete("/api/profiles/example/scenarios/what_if_2")
    assert client.delete("/api/profiles/example/scenarios/what_if_2?purge=true").status_code == 204
    assert client.get("/api/profiles/example/scenarios/what_if_2?deleted=true").status_code == 404
