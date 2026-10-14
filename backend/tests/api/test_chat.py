import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.db.session import get_session
from app.llm.fake import FakeLLM, call, say
from app.main import app
from app.services import build_services, get_services

KEY = "test-key"


@pytest.fixture
def make_client(engine, catalog, tmp_path):
    from app.db.seed import seed

    settings = Settings(_env_file=None, demo_api_key=KEY, trace_log_path=tmp_path / "traces.jsonl")
    with sessionmaker(engine)() as s:
        seed(s, catalog, settings)

    def _session():
        with sessionmaker(engine, expire_on_commit=False)() as s:
            yield s

    def factory(script, **overrides):
        services = build_services(settings.model_copy(update=overrides), llm=FakeLLM(script))
        app.dependency_overrides[get_session] = _session
        app.dependency_overrides[get_services] = lambda: services
        return TestClient(app), services

    yield factory
    app.dependency_overrides.clear()


H = {"X-API-Key": KEY}
DEPOSIT = (
    "calculate_deposit",
    dict(
        product_code="HB-DEP-001",
        principal=10_000_000,
        months=12,
        include_preferential=False,
        tax_type="GENERAL",
        early_termination_after_months=None,
    ),
)


def test_auth_required(make_client):
    client, _ = make_client([])
    assert client.post("/v1/chat", json={"message": "hi", "mode": "debug"}).status_code == 401
    r = client.post(
        "/v1/chat", json={"message": "hi", "mode": "debug"}, headers={"X-API-Key": "wrong"}
    )
    assert r.status_code == 401


def test_standard_mode_not_available_without_gateway(make_client):
    client, _ = make_client([])
    r = client.post("/v1/chat", json={"message": "hi"}, headers=H)
    assert r.status_code == 501


def test_debug_disabled(make_client):
    client, _ = make_client([], allow_debug_mode=False)
    assert (
        client.post("/v1/chat", json={"message": "hi", "mode": "debug"}, headers=H).status_code
        == 403
    )


def test_validation(make_client):
    client, _ = make_client([])
    assert (
        client.post("/v1/chat", json={"message": "", "mode": "debug"}, headers=H).status_code == 422
    )


def test_debug_chat_flow(make_client, tmp_path):
    client, services = make_client(
        [call(DEPOSIT), say("세후 이자는 279,180원입니다. 약 28만 원이에요.")]
    )
    r = client.post(
        "/v1/chat",
        json={"message": "1,000만 원 12개월 예금 이자? 연락처 010-1234-5678", "mode": "debug"},
        headers=H,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ANSWERED"
    assert body["tools_called"] == ["calculate_deposit"]
    assert body["pii_detected"] == {"PHONE": 1}
    assert [i["text"] for i in body["provenance"]["unsourced"]] == ["28만 원"]
    assert body["citations"][0]["product_code"] == "HB-DEP-001"
    assert body["llm_calls"] == 2
    assert [e["kind"] for e in body["trace"]] == [
        "input",
        "llm_call",
        "tool_call",
        "llm_call",
        "final",
    ]

    logged = [json.loads(line) for line in (tmp_path / "traces.jsonl").read_text().splitlines()]
    assert logged[0]["request_id"] == body["request_id"]
    assert "010-1234-5678" not in json.dumps(logged, ensure_ascii=False)

    # 같은 대화를 이어가면 이력이 전달된다(마스킹된 텍스트)
    services.llm._queue = [say("네, 이어서 안내드릴게요.")]
    r2 = client.post(
        "/v1/chat",
        json={
            "message": "다른 상품은요?",
            "mode": "debug",
            "conversation_id": body["conversation_id"],
        },
        headers=H,
    )
    assert r2.json()["conversation_id"] == body["conversation_id"]
    turns = services.llm.calls[-1][1]
    assert len(turns) == 3
    assert "[전화번호]" in turns[0].text


def test_escalation_response(make_client):
    client, _ = make_client(
        [call(("escalate_to_human", {"category": "OUT_OF_SCOPE", "summary": "주식"}))]
    )
    body = client.post(
        "/v1/chat", json={"message": "삼성전자 주식 사도 돼요?", "mode": "debug"}, headers=H
    ).json()
    assert body["status"] == "ESCALATED"
    assert body["escalation"]["category"] == "OUT_OF_SCOPE"
