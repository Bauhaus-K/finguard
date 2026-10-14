from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.llm.fake import say

from .conftest import H


def _make(make_client, n=3):
    client, _ = make_client([say("안녕하세요!") for _ in range(n)])
    ids = [
        client.post("/v1/chat", json={"message": "안녕"}, headers=H).json()["request_id"]
        for _ in range(n)
    ]
    client.post("/v1/gateway/check", json={"answer": "확정 수익 보장"}, headers=H)
    return client, ids


def test_list_and_filter(make_client):
    client, ids = _make(make_client)
    body = client.get("/v1/audit/records", headers=H).json()
    assert body["total"] == 4
    assert [i["seq"] for i in body["items"]] == [4, 3, 2, 1]
    assert body["items"][-1]["request_id"] == ids[0]
    blocked = client.get("/v1/audit/records?status=BLOCKED", headers=H).json()
    assert blocked["total"] == 1 and blocked["items"][0]["mode"] == "gateway_only"
    page = client.get("/v1/audit/records?limit=1&offset=1", headers=H).json()
    assert [i["seq"] for i in page["items"]] == [3]


def test_detail_and_404(make_client):
    client, ids = _make(make_client, 1)
    rec = client.get(f"/v1/audit/records/{ids[0]}", headers=H).json()
    assert rec["payload"]["input"]["user_message"] == "안녕"
    assert rec["tenant_id"] == "demo"
    assert client.get("/v1/audit/records/nope", headers=H).status_code == 404


def test_verify_and_tamper(make_client, engine):
    client, _ = _make(make_client)
    assert client.get("/v1/audit/verify", headers=H).json() == {
        "ok": True,
        "checked": 4,
        "broken_seq": None,
        "reason": None,
        "last_hash": client.get("/v1/audit/records?limit=1", headers=H).json()["items"][0][
            "record_hash"
        ],
    }
    with sessionmaker(engine)() as s:
        s.execute(text("DROP TRIGGER audit_records_no_update"))
        s.execute(text("UPDATE audit_records SET status='PASS' WHERE seq=4"))
        s.commit()
    result = client.get("/v1/audit/verify", headers=H).json()
    assert result["ok"] is False and result["broken_seq"] == 4


def test_export(make_client):
    client, _ = _make(make_client, 2)
    csv = client.get("/v1/audit/export?format=csv", headers=H)
    assert csv.headers["content-type"].startswith("text/csv")
    lines = csv.text.lstrip("﻿").splitlines()
    assert lines[0].startswith("seq,created_at,request_id,status")
    assert len(lines) == 4
    js = client.get("/v1/audit/export?format=json", headers=H).json()
    assert [r["seq"] for r in js] == [1, 2, 3]
    assert "payload" in js[0]
    assert client.get("/v1/audit/export?format=xml", headers=H).status_code == 422


def test_rules_endpoint(make_client):
    client, _ = make_client()
    body = client.get("/v1/rules", headers=H).json()
    assert body["files"] == ["default.yaml", "tenants/demo.yaml"]
    assert body["error"] is None and body["version"]
    assert body["rules"]["order"][0] == "pii"
    assert client.get("/v1/rules").status_code == 401
