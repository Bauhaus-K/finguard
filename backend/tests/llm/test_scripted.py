"""오프라인 리허설용 스크립트 LLM: 데모 시나리오 1~4 가 전체 파이프라인(도구·게이트웨이·감사)을 통과하는지."""

import pytest

from app.chat_service import handle_chat
from app.config import Settings
from app.gateway.types import GatewayStatus
from app.llm.factory import build_llm
from app.llm.scripted import ScriptedLLM
from app.services import build_services


@pytest.fixture
def run(seeded_session):
    services = build_services(Settings(_env_file=None, llm_provider="scripted"))
    assert isinstance(services.llm, ScriptedLLM)
    conv = services.conversations.get_or_create("demo", None)

    def _run(message):
        return handle_chat(
            services=services,
            session=seeded_session,
            tenant_id="demo",
            conversation=conv,
            message=message,
        )

    return _run


def test_factory_scripted():
    assert isinstance(build_llm(Settings(_env_file=None, llm_provider="scripted")), ScriptedLLM)


def test_demo_1_deposit(run):
    o = run("1,000만 원을 12개월 예금하면 이자가 얼마예요?")
    assert o.status is GatewayStatus.AUTO_FIXED
    assert "279,180원" in o.answer and "예금자보호법" in o.answer
    assert o.attempts[0].agent.tool_names == ["calculate_deposit"]


def test_demo_2_loan_guarantee(run):
    o = run("무조건 대출 승인되는 상품 알려줘")
    assert o.status in (GatewayStatus.PASS, GatewayStatus.AUTO_FIXED)
    assert "무조건 승인되는 대출 상품은 없습니다" in o.answer and "연소득" in o.answer
    forbidden = next(c for c in o.last.gateway.checks if c.check == "forbidden_expressions")
    assert forbidden.findings and forbidden.findings[0].severity == "info"  # 부정 문맥으로 허용


def test_demo_3_pii(run):
    o = run("제 주민번호는 900101-1234567 입니다")
    assert o.attempts[0].agent.pii_detected == {"RRN": 1}
    assert "900101" not in o.attempts[0].agent.masked_input


def test_demo_4_out_of_scope(run):
    o = run("삼성전자 주식 사도 돼요?")
    assert o.status is GatewayStatus.ESCALATED
    assert o.escalation["category"] == "OUT_OF_SCOPE"


def test_loan_after_suitability_and_others(run):
    run("무조건 대출 승인되는 상품 알려줘")
    o = run("연소득 3,000만 원이고 부채는 없어요. 회사원이고 생활비로 대출 쓰려고요")
    assert o.status is GatewayStatus.AUTO_FIXED
    assert o.attempts[0].agent.tool_names == ["record_suitability_check"]
    assert "비상금 소액대출" in o.answer
    assert run("월 30만 원씩 24개월 적금 넣으면?").status is GatewayStatus.AUTO_FIXED
    assert "1억원" in run("예금자보호는 얼마까지 돼요?").answer
    assert run("상담원 연결해 주세요").escalation["category"] == "CUSTOMER_REQUEST"
    assert "스크립트 모드" in run("오늘 날씨 어때요?").answer
    assert "계산할 수 없습니다" in run("100만 원 예금 600개월").answer


def test_judge_mode_returns_no_violations():
    from app.llm.base import UserTurn

    r = ScriptedLLM().complete(system="judge", turns=[UserTurn("x")], tools=[])
    assert r.assistant.text == '{"violations": []}'


def test_audit_records_scripted_provider(run, seeded_session):
    from sqlalchemy import select

    from app.db.models import AuditRecord

    o = run("1,000만 원을 12개월 예금하면 이자가 얼마예요?")
    rec = seeded_session.scalar(select(AuditRecord).where(AuditRecord.request_id == o.request_id))
    assert rec.payload["llm_provider"] == "scripted"
    assert rec.payload["model"] == "scripted"  # 실제 LLM 모델명으로 기록하지 않는다
