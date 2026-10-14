from app.llm.fake import call, say

from .conftest import AH, DEPOSIT, H

GOOD = "한빛 정기예금(가상) 기준 세후 이자는 279,180원입니다."


def test_metrics(make_client):
    client, _ = make_client(
        [
            call(DEPOSIT),
            say(GOOD),
            say("안녕하세요!"),
            call(DEPOSIT),
            say("세후 이자는 297,180원입니다."),
            call(DEPOSIT),
            say(GOOD),
            call(("escalate_to_human", {"category": "OUT_OF_SCOPE", "summary": "x"})),
        ]
    )
    for msg in ["예금 이자?", "안녕", "예금 이자?", "주식?"]:
        client.post("/v1/chat", json={"message": msg}, headers=H)
    client.post("/v1/gateway/check", json={"answer": "확정 수익 보장"}, headers=H)

    m = client.get("/v1/metrics?days=7", headers=AH).json()
    assert m["total"] == 5
    assert m["by_status"] == {"PASS": 1, "AUTO_FIXED": 2, "BLOCKED": 1, "ESCALATED": 1}
    assert len(m["daily"]) == 7 and sum(m["daily"][-1][s] for s in m["by_status"]) == 5
    checks = {c["check"]: c for c in m["checks"]}
    assert checks["disclosures"]["FIXED"] == 2
    assert checks["forbidden_expressions"]["FAIL"] == 1
    assert m["escalation_categories"] == {"OUT_OF_SCOPE": 1}
    assert m["regenerated"] == 1
    assert m["latency_ms"]["avg"] is not None and m["latency_ms"]["p95"] is not None
    assert m["tokens"]["requests"] == 4 and m["tokens"]["avg_per_request"] > 0

    only_gw = client.get("/v1/metrics?mode=gateway_only", headers=AH).json()
    assert only_gw["total"] == 1 and only_gw["by_status"]["BLOCKED"] == 1
    assert client.get("/v1/metrics?days=0", headers=AH).status_code == 422


def test_metrics_empty(make_client):
    client, _ = make_client()
    m = client.get("/v1/metrics", headers=AH).json()
    assert m["total"] == 0 and m["latency_ms"] == {"avg": None, "p95": None}
    assert m["tokens"]["avg_per_request"] is None


def test_guidelines_placeholders(make_client):
    client, _ = make_client()
    g = client.get("/v1/guidelines", headers=AH).json()
    assert g["file"] == "data/guideline_mapping.yaml"
    assert g["principles"] and all(p["needs_review"] for p in g["principles"])
    # 원칙 내용은 지어내지 않는다: 모든 이름·요지가 TODO placeholder
    assert all(
        p["name"].startswith("TODO") and p["summary"].startswith("TODO") for p in g["principles"]
    )
    ids = {f["id"] for f in g["system_features"]}
    assert {"F-NUMERIC", "F-AUDIT", "F-PII"} <= ids


def test_guidelines_unknown_feature_and_broken_file(make_client, tmp_path, settings):
    import shutil

    data = tmp_path / "data"
    shutil.copytree(settings.data_dir, data)
    (data / "guideline_mapping.yaml").write_text(
        "principles:\n  - {id: P-01, name: 원칙, summary: 요지, features: [F-AUDIT, F-NOPE]}\n"
        "system_features:\n  - {id: F-AUDIT, name: 감사, description: d, evidence: []}\n",
        encoding="utf-8",
    )
    client, _ = make_client(data_dir=data)
    p = client.get("/v1/guidelines", headers=AH).json()["principles"][0]
    assert p["needs_review"] is False and p["unknown_features"] == ["F-NOPE"]
    (data / "guideline_mapping.yaml").write_text("principles: [\n", encoding="utf-8")
    assert client.get("/v1/guidelines", headers=AH).status_code == 500


def test_meta(make_client):
    client, _ = make_client()
    m = client.get("/v1/meta", headers=H).json()
    assert m == {
        "tenant_id": "demo",
        "tenant_name": "한빛저축은행(가상)",
        "llm_provider": "anthropic",
        "llm_model": "claude-sonnet-5-5",
        "scripted": False,
        "debug_mode_allowed": True,
    }
    assert client.get("/v1/meta").status_code == 401
