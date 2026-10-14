"""POST /v1/chat — 상담 에이전트 + 컴플라이언스 게이트웨이.

- mode=standard: 게이트웨이를 거친 최종 답변만 반환한다.
- mode=debug: 게이트웨이 판정은 그대로 수행·기록하되 원본(LLM) 답변을 반환하고, trace 와 수치 출처를 함께 보여준다.
모든 요청은 해시 체인 감사 로그에 남는다.
"""

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.api.deps import CurrentTenant, DbSession
from app.chat_service import ChatOutcome, handle_chat
from app.compliance.provenance import check_provenance
from app.services import Services, get_services

router = APIRouter(prefix="/v1", tags=["chat"])


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    conversation_id: str | None = Field(default=None, max_length=64)
    mode: Literal["standard", "debug"] = "standard"


class ChatResponse(BaseModel):
    request_id: str
    conversation_id: str
    mode: str
    status: str  # PASS / AUTO_FIXED / BLOCKED / ESCALATED
    answer: str
    masked_message: str  # 개인정보를 가린 고객 메시지 (화면에 이 값으로 다시 표시)
    escalation: dict[str, str] | None = None
    citations: list[dict[str, str]]
    pii_detected: dict[str, int]
    gateway: dict[str, Any] | None = None
    attempts: int
    latency_ms: int
    # --- debug 전용 ---
    gateway_answer: str | None = None  # standard 모드였다면 고객이 받았을 답변
    provenance: dict[str, list[dict[str, str]]] | None = None
    tools_called: list[str] | None = None
    usage: dict[str, int] | None = None
    llm_calls: int | None = None
    trace: list[dict[str, Any]] | None = None


def gateway_summary(outcome: ChatOutcome) -> dict[str, Any] | None:
    g = outcome.last.gateway
    if g is None:
        return None
    return {
        "status": g.status,
        "retryable": g.retryable,
        "rules_version": g.rules_version,
        "checks": [
            {
                "check": c.check,
                "outcome": c.outcome,
                "action": c.action,
                "findings": [f.model_dump() for f in c.findings],
            }
            for c in g.checks
        ],
    }


def to_response(outcome: ChatOutcome) -> ChatResponse:
    agent = outcome.last.agent
    resp = ChatResponse(
        request_id=outcome.request_id,
        conversation_id=outcome.conversation_id,
        mode=outcome.mode,
        status=outcome.status,
        answer=outcome.answer,
        masked_message=outcome.attempts[0].agent.masked_input,
        escalation=outcome.escalation,
        citations=agent.citations,
        pii_detected=outcome.attempts[0].agent.pii_detected,
        gateway=gateway_summary(outcome),
        attempts=len(outcome.attempts),
        latency_ms=outcome.latency_ms,
    )
    if outcome.mode == "debug":
        report = check_provenance(agent.answer, agent.source_figures)

        def items(ns):
            return [{"text": n.text, "unit": n.unit, "value": str(n.value)} for n in ns]

        g = outcome.last.gateway
        resp.gateway_answer = g.final_answer if g else None
        resp.provenance = {"checked": items(report.checked), "unsourced": items(report.unsourced)}
        resp.tools_called = agent.tool_names
        resp.usage = vars(outcome.usage)
        resp.llm_calls = sum(a.agent.llm_calls for a in outcome.attempts)
        resp.trace = [e.model_dump(mode="json") for e in agent.trace.events]
    return resp


@router.post("/chat", response_model=ChatResponse)
def chat(
    req: ChatRequest,
    tenant: CurrentTenant,
    session: DbSession,
    services: Annotated[Services, Depends(get_services)],
) -> ChatResponse:
    if req.mode == "debug" and not services.settings.allow_debug_mode:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "debug 모드가 비활성화되어 있습니다")
    conversation = services.conversations.get_or_create(tenant.id, req.conversation_id)
    outcome = handle_chat(
        services=services,
        session=session,
        tenant_id=tenant.id,
        conversation=conversation,
        message=req.message,
        mode=req.mode,
    )
    return to_response(outcome)
