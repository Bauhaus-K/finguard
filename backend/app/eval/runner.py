"""평가 실행: 케이스마다 새 대화로 전체 파이프라인(에이전트→게이트웨이→감사)을 돌린다."""

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.chat_service import ChatOutcome, handle_chat
from app.compliance.numbers import ExtractedNumber
from app.compliance.provenance import check_provenance
from app.gateway.checks import CheckContext
from app.gateway.engine import run_gateway
from app.gateway.types import GatewayDecision, GatewayInput, ProductRef
from app.services import Services


@dataclass
class TurnRecord:
    request_id: str
    question_masked: str
    status: str
    answer: str
    attempts: int
    raw_unsourced: list[str]  # 첫 시도 LLM 원본 답변의 출처 없는 수치
    final_unsourced: list[
        str
    ]  # 고객에게 전달된 답변의 출처 없는 수치(게이트웨이가 0 으로 만들어야 함)
    latency_ms: int
    usage: dict[str, int]
    tools: list[str]
    citations: list[dict[str, str]]
    pii_detected: dict[str, int]
    escalation: dict[str, str] | None = None
    gateway_findings: list[str] = field(default_factory=list)


def _texts(ns: list[ExtractedNumber]) -> list[str]:
    return [n.text for n in ns]


def to_record(o: ChatOutcome) -> TurnRecord:
    first = o.attempts[0].agent
    last = o.last.agent
    raw = (
        check_provenance(first.answer, first.source_figures)
        if first.status.value == "ANSWERED"
        else None
    )
    # 고객에게 나간 답변은 마지막 시도의 출처 + 게이트웨이가 첨부한 고지 문구(규칙 원문)를 기준으로 본다
    final = check_provenance(o.answer, last.source_figures)
    appended = set()
    if o.last.gateway:
        for c in o.last.gateway.checks:
            for f in c.findings:
                if f.excerpt and c.check == "disclosures":
                    appended |= {n.text for n in check_provenance(f.excerpt, []).checked}
    findings = []
    if o.last.gateway:
        findings = [
            f"{c.check}:{f.message}"
            for c in o.last.gateway.failed()
            for f in c.findings
            if f.severity == "violation"
        ]
    return TurnRecord(
        request_id=o.request_id,
        question_masked=first.masked_input,
        status=o.status.value,
        answer=o.answer,
        attempts=len(o.attempts),
        raw_unsourced=_texts(raw.unsourced) if raw else [],
        final_unsourced=[t for t in _texts(final.unsourced) if t not in appended]
        if o.status.value in ("PASS", "AUTO_FIXED")
        else [],
        latency_ms=o.latency_ms,
        usage=vars(o.usage),
        tools=[t for a in o.attempts for t in a.agent.tool_names],
        citations=last.citations,
        pii_detected=first.pii_detected,
        escalation=o.escalation,
        gateway_findings=findings,
    )


def run_conversation(
    services: Services, session: Session, tenant_id: str, turns: list[str]
) -> list[TurnRecord]:
    conv = services.conversations.get_or_create(tenant_id, None)
    return [
        to_record(
            handle_chat(
                services=services,
                session=session,
                tenant_id=tenant_id,
                conversation=conv,
                message=t,
            )
        )
        for t in turns
    ]


def run_attack(
    services: Services,
    tenant_id: str,
    question: str,
    attack_answer: str,
    products: list[ProductRef],
) -> GatewayDecision:
    """오염된 LLM 답변을 가정하고 게이트웨이만 단독으로 검사한다(출처 수치 없음)."""
    inp = GatewayInput(user_message=question, answer=attack_answer, products=products)
    return run_gateway(inp, services.rules.get(tenant_id), CheckContext(judge_llm=services.llm))
