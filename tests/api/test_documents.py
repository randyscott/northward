def accounts(client) -> dict:
    return client.get("/api/profiles/example/documents/accounts").json()


def test_list_a_profiles_documents_and_scenarios(client):
    docs = client.get("/api/profiles/example/documents").json()
    assert [d["address"] for d in docs][-4:] == [
        "scenarios/base",
        "scenarios/early_retire_roth_fill",
        "scenarios/historical_lifespans",
        "scenarios/survivor",
    ]
    assert docs[-1]["kind"] == "scenario" and docs[-1]["id"] is not None


def test_get_a_document_by_address_and_by_id(client):
    doc = accounts(client)
    assert doc["address"] == "accounts" and doc["latest"]["revision"] == 1
    assert doc["data"]["accounts"][0]["id"] == "alex_401k" and doc["yaml_text"].startswith("schema_version: 1\n")
    assert client.get(f"/api/documents/{doc['id']}").json() == doc
    scenario = client.get("/api/profiles/example/documents/scenarios/survivor").json()
    assert scenario["address"] == "scenarios/survivor" and scenario["data"]["description"].startswith("Alex dies")
    assert client.get("/api/profiles/example/documents/health_costs").status_code == 404
    assert client.get("/api/profiles/example/documents/nonsense").status_code == 400
    assert client.get("/api/documents/99999").status_code == 404


def test_save_yaml_text(client):
    doc = accounts(client)
    text = doc["yaml_text"].replace("balance: 150000", "balance: 160000")
    response = client.put("/api/profiles/example/documents/accounts", json={"yaml_text": text, "note": "statement"})
    assert response.status_code == 200
    (saved,) = response.json()["saved"]
    assert saved["revision"] == 2 and saved["note"] == "statement" and saved["document_id"] == doc["id"]
    assert accounts(client)["yaml_text"] == text
    old = client.get("/api/profiles/example/documents/accounts?revision=1").json()
    assert old["yaml_text"] == doc["yaml_text"]


def test_saving_data_keeps_the_yaml_comments(client):
    doc = accounts(client)
    data = doc["data"]
    data["accounts"][5]["balance"] = 175000
    assert client.put("/api/profiles/example/documents/accounts", json={"data": data}).status_code == 200
    text = accounts(client)["yaml_text"]
    assert text == doc["yaml_text"].replace("balance: 150000", "balance: 175000")  # only that line changed


def test_saving_unchanged_content_adds_no_revision(client):
    response = client.put("/api/profiles/example/documents/accounts", json={"data": accounts(client)["data"]})
    assert response.json() == {"saved": []}


def test_a_stale_base_revision_is_a_conflict(client):
    text = accounts(client)["yaml_text"]
    first = text.replace("balance: 150000", "balance: 1")
    assert (
        client.put(
            "/api/profiles/example/documents/accounts", json={"yaml_text": first, "base_revision": 1}
        ).status_code
        == 200
    )
    second = client.put("/api/profiles/example/documents/accounts", json={"yaml_text": text, "base_revision": 1})
    assert second.status_code == 409 and "has changed since revision 1 (it's at revision 2)" in second.json()["detail"]


def test_invalid_content_is_rejected_with_its_issues(client):
    data = accounts(client)["data"]
    data["accounts"][5]["owner"] = "nobody"
    response = client.put("/api/profiles/example/documents/accounts", json={"data": data})
    assert response.status_code == 422
    body = response.json()
    assert body["detail"].endswith("nothing was saved")
    assert {
        "origin": "profiles/example/accounts.yaml",
        "location": "accounts[joint_brokerage].owner",
        "message": "unknown member 'nobody'",
    } in body["issues"]
    assert (
        client.put(
            "/api/profiles/example/documents/goals", json={"yaml_text": "schema_version: 1\nsurprise: 1\n"}
        ).status_code
        == 422
    )
    both = client.put("/api/profiles/example/documents/goals", json={"yaml_text": "x", "data": {}})
    assert both.status_code == 422 and "exactly one of yaml_text or data" in both.text


def test_a_batch_is_validated_and_saved_together(client):
    scenario = client.get("/api/profiles/example/documents/scenarios/base").json()["data"]
    scenario["levers"]["surplus_sweep"] = [{"account": "joint_cd"}]
    alone = client.put("/api/profiles/example/documents/scenarios/base", json={"data": scenario})
    assert alone.status_code == 422 and "unknown account 'joint_cd'" in alone.text
    data = accounts(client)["data"]
    data["accounts"].append({"id": "joint_cd", "owner": "joint", "type": "savings", "balance": 10000})
    batch = {"changes": {"accounts": {"data": data}, "scenarios/base": {"data": scenario}}, "note": "add a CD"}
    response = client.put("/api/profiles/example/documents", json=batch)
    assert response.status_code == 200
    assert [(r["revision"], r["note"]) for r in response.json()["saved"]] == [(2, "add a CD"), (2, "add a CD")]


def test_create_an_optional_document(client):
    response = client.put("/api/profiles/example/documents/health_costs", json={"data": {"schema_version": 1}})
    assert response.status_code == 200 and response.json()["saved"][0]["revision"] == 1
    detail = client.get("/api/profiles/example").json()
    assert next(d for d in detail["documents"] if d["kind"] == "health_costs")["id"] is not None


def test_revision_history_diff_and_restore(client):
    doc = accounts(client)
    url = "/api/profiles/example/documents/accounts"
    client.put(url, json={"yaml_text": doc["yaml_text"].replace("balance: 150000", "balance: 2"), "note": "two"})
    revisions = client.get(f"/api/documents/{doc['id']}/revisions").json()
    assert [r["revision"] for r in revisions] == [1, 2]
    assert revisions[0]["note"].startswith("seeded from") and revisions[1]["note"] == "two"
    detail = client.get(f"/api/documents/{doc['id']}/revisions/1").json()
    assert detail["yaml_text"] == doc["yaml_text"] and detail["data"] == doc["data"]
    assert client.get(f"/api/documents/{doc['id']}/revisions/9").status_code == 404

    diff = client.get(f"/api/documents/{doc['id']}/diff").json()
    assert (diff["old"], diff["new"]) == (1, 2)
    assert "-    balance: 150000\n+    balance: 2\n" in diff["diff"] and diff["diff"].startswith("--- accounts@1")

    restored = client.post(f"/api/documents/{doc['id']}/revisions/1/restore", json={}).json()["saved"][0]
    assert restored["revision"] == 3 and restored["note"] == "restore revision 1"
    assert accounts(client)["yaml_text"] == doc["yaml_text"]


def test_rule_documents_are_read_only(client):
    rmd = client.get("/api/rule-sets/latest/documents/rmd").json()
    response = client.post(f"/api/documents/{rmd['id']}/revisions/1/restore")
    assert response.status_code == 409 and "read-only" in response.json()["detail"]
