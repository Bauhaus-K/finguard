from app.llm.base import SystemNoteTurn
from app.llm.fake import call, say

from .conftest import DEPOSIT, H

GOOD = (
    "한빛 정기예금(가상)(HB-DEP-001) 기준 연 3.30%로 12개월 예치하면 세후 이자는 279,180원입니다."
)
WRONG = "한빛 정기예금(가상) 기준 세후 이자는 297,180원입니다."


def post(client, message, **kw):
    return client.post("/v1/chat", json={"message": message, **kw}, headers=H)


def audit(client, request_id):
    return client.get(f"/v1/audit/records/{request_id}", headers=H).json()


def test_auth_required(make_client):
    client, _ = make_client()
    assert client.post("/v1/chat", json={"message": "hi"}).status_code == 401
    assert (
        client.post("/v1/chat", json={"message": "hi"}, headers={"X-API-Key": "x"}).status_code
        == 401
    )


def test_validation_and_debug_disabled(make_client):
    client, _ = make_client(allow_debug_mode=False)
    assert post(client, "").status_code == 422
    assert post(client, "hi", mode="debug").status_code == 403


def test_standard_flow_auto_fixed(make_client):
    """데모 시나리오 1: 정확한 세후 이자 + 예금자보호 고지 자동 첨부."""
    client, services = make_client([call(DEPOSIT), say(GOOD)])
    r = post(client, "1,000만 원을 12개월 예금하면 이자가 얼마예요?")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "AUTO_FIXED"
    assert body["answer"].startswith(GOOD)
    assert "예금자보호법" in body["answer"]
    assert body["attempts"] == 1
    checks = {c["check"]: c["outcome"] for c in body["gateway"]["checks"]}
    assert checks["numeric"] == "PASS" and checks["disclosures"] == "FIXED"
    assert body["trace"] is None and body["provenance"] is None  # debug 전용 필드

    rec = audit(client, body["request_id"])
    assert rec["status"] == "AUTO_FIXED"
    assert rec["payload"]["final"]["answer"] == body["answer"]
    assert rec["payload"]["attempts"][0]["agent"]["raw_answer"] == GOOD
    assert rec["payload"]["attempts"][0]["agent"]["tools"][0]["name"] == "calculate_deposit"
    assert rec["payload"]["rules"]["digest"]
    # 대화 이력에는 게이트웨이를 거친 최종 답변이 남는다
    conv = services.conversations.get_or_create("demo", body["conversation_id"])
    assert conv.history[-1] == ("assistant", body["answer"])


def test_wrong_number_regenerated_once(make_client):
    client, services = make_client([call(DEPOSIT), say(WRONG), call(DEPOSIT), say(GOOD)])
    body = post(client, "1,000만 원 12개월 예금 이자?").json()
    assert body["status"] == "AUTO_FIXED"
    assert body["attempts"] == 2
    assert "297,180원" not in body["answer"]
    # 재생성 호출에는 게이트웨이 피드백이 system 메시지로 들어간다
    second_first_call = services.llm.calls[2][1]
    assert isinstance(second_first_call[-1], SystemNoteTurn)
    assert "297,180원" in second_first_call[-1].text
    rec = audit(client, body["request_id"])
    assert [a["gateway"]["status"] for a in rec["payload"]["attempts"]] == ["BLOCKED", "AUTO_FIXED"]


def test_wrong_number_twice_escalates(make_client):
    client, _ = make_client([call(DEPOSIT), say(WRONG), call(DEPOSIT), say(WRONG)])
    body = post(client, "1,000만 원 12개월 예금 이자?").json()
    assert body["status"] == "ESCALATED"
    assert body["escalation"]["category"] == "GATEWAY"
    assert "상담원" in body["answer"]
    assert "297,180원" not in body["answer"]


def test_agent_escalation(make_client):
    """데모 시나리오 4: 업무 범위 밖 → 상담원 이관."""
    client, _ = make_client(
        [call(("escalate_to_human", {"category": "OUT_OF_SCOPE", "summary": "주식 추천"}))]
    )
    body = post(client, "삼성전자 주식 사도 돼요?").json()
    assert body["status"] == "ESCALATED"
    assert body["gateway"] is None
    assert body["escalation"]["category"] == "OUT_OF_SCOPE"
    rec = audit(client, body["request_id"])
    assert rec["payload"]["gateway"] is None and rec["status"] == "ESCALATED"


def test_scope_violation_escalated_by_gateway(make_client):
    client, _ = make_client([say("삼성전자 주식은 지금 매수하시는 게 좋습니다.")])
    body = post(client, "삼성전자 주식 사도 돼요?").json()
    assert body["status"] == "ESCALATED"
    assert body["escalation"]["category"] == "GATEWAY"
    assert "scope" in body["escalation"]["reason"]


def test_pii_masked_everywhere(make_client):
    """데모 시나리오 3: 주민등록번호 입력 → 즉시 마스킹, 로그에도 마스킹."""
    client, services = make_client([say("개인정보는 입력하지 않으셔도 됩니다.")])
    body = post(client, "제 주민번호는 900101-1234567 이에요").json()
    assert body["pii_detected"] == {"RRN": 1}
    sent = services.llm.calls[0][1][-1].text
    assert "900101" not in sent
    export = client.get("/v1/audit/export?format=json", headers=H).text
    assert "900101-1234567" not in export and "[주민등록번호]" in export


def test_suitability_replacement(make_client):
    loan = (
        "calculate_loan",
        dict(
            product_code="HB-LOAN-002",
            principal=2_000_000,
            months=12,
            assumed_annual_rate=12,
            repayment_method="EQUAL_PAYMENT",
            prepayment_after_days=None,
            prepayment_amount=None,
        ),
    )
    client, _ = make_client([call(loan), say("월 상환액은 177,697원입니다.")])
    body = post(client, "200만 원 대출 매달 얼마예요?").json()
    assert body["status"] == "BLOCKED"
    assert "연소득" in body["answer"]


def test_debug_mode_returns_raw_answer(make_client):
    client, _ = make_client([call(DEPOSIT), say(GOOD + " 약 28만 원이에요.")])
    body = post(client, "1,000만 원 12개월 예금 이자?", mode="debug").json()
    assert body["answer"] == GOOD + " 약 28만 원이에요."  # 원본
    assert body["status"] == "BLOCKED"  # debug 는 재생성 없이 판정만
    assert body["attempts"] == 1
    assert "28만 원" not in body["gateway_answer"]
    assert [i["text"] for i in body["provenance"]["unsourced"]] == ["28만 원"]
    assert body["tools_called"] and body["trace"] and body["usage"]


def test_debug_mode_gateway_answer(make_client):
    client, _ = make_client([call(DEPOSIT), say(GOOD)])
    body = post(client, "1,000만 원 12개월 예금 이자?", mode="debug").json()
    assert body["answer"] == GOOD
    assert body["gateway_answer"].startswith(GOOD) and "예금자보호법" in body["gateway_answer"]
    assert body["status"] == "AUTO_FIXED"


def test_conversation_continues(make_client):
    client, services = make_client([say("안녕하세요!"), say("네, 예금 상품을 안내해 드릴게요.")])
    first = post(client, "안녕").json()
    second = post(client, "예금 상품 알려줘", conversation_id=first["conversation_id"]).json()
    assert second["conversation_id"] == first["conversation_id"]
    assert len(services.llm.calls[-1][1]) == 3


def test_rules_error_escalates(make_client, tmp_path):
    (tmp_path / "rules").mkdir()
    (tmp_path / "rules" / "default.yaml").write_text("order: [\n")
    client, _ = make_client([say("안녕하세요")], rules_dir=tmp_path / "rules")
    body = post(client, "안녕").json()
    assert body["status"] == "ESCALATED"
    assert "rules" in body["escalation"]["reason"]
