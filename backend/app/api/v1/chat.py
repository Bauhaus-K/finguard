"""POST /v1/chat — 상담 에이전트.

Phase 2: 컴플라이언스 게이트웨이가 아직 없으므로 mode=debug(게이트웨이 미적용 원본 답변 + trace)만 허용한다.
게이트웨이를 거치지 않은 답변을 '고객용' 으로 내보내지 않는다(fail-safe 원칙).
"""

import time
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.agent.loop import AgentResult, run_agent, trace_record
from app.agent.tools import ToolContext
from app.api.deps import CurrentTenant, DbSession
from app.compliance.provenance import check_provenance
from app.services import Services, get_services

router = APIRouter(prefix="/v1", tags=["chat"])


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    conversation_id: str | None = Field(default=None, max_length=64)
    mode: Literal["standard", "debug"] = "standard"


class ProvenanceItem(BaseModel):
    text: str
    unit: str
    value: str


class ChatResponse(BaseModel):
    request_id: str
    conversation_id: str
    mode: str
    status: str
    answer: str
    gateway: dict[str, Any] | None = None  # Phase 3
    escalation: dict[str, str] | None = None
    citations: list[dict[str, str]]
    pii_detected: dict[str, int]
    # --- debug 전용 ---
    provenance: dict[str, list[ProvenanceItem]] | None = None
    tools_called: list[str] | None = None
    usage: dict[str, int] | None = None
    llm_calls: int | None = None
    latency_ms: int | None = None
    trace: list[dict[str, Any]] | None = None


def _provenance(result: AgentResult) -> dict[str, list[ProvenanceItem]]:
    report = check_provenance(result.answer, result.source_figures)

    def items(ns):
        return [ProvenanceItem(text=n.text, unit=n.unit, value=str(n.value)) for n in ns]

    return {"checked": items(report.checked), "unsourced": items(report.unsourced)}


@router.post("/chat", response_model=ChatResponse)
def chat(
    req: ChatRequest,
    tenant: CurrentTenant,
    session: DbSession,
    services: Annotated[Services, Depends(get_services)],
) -> ChatResponse:
    if req.mode == "standard":
        raise HTTPException(
            status.HTTP_501_NOT_IMPLEMENTED,
            "컴플라이언스 게이트웨이가 아직 적용되지 않았습니다(Phase 3). 현재는 mode=debug 만 사용할 수 있습니다.",
        )
    if not services.settings.allow_debug_mode:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "debug 모드가 비활성화되어 있습니다")

    conversation = services.conversations.get_or_create(tenant.id, req.conversation_id)
    ctx = ToolContext(
        session=session,
        tenant_id=tenant.id,
        settings=services.settings,
        retriever=services.retriever,
        conversation=conversation,
    )
    t0 = time.perf_counter()
    result = run_agent(
        llm=services.llm,
        ctx=ctx,
        conversation=conversation,
        user_message=req.message,
        max_steps=services.settings.agent_max_steps,
    )
    latency_ms = int((time.perf_counter() - t0) * 1000)
    conversation.append("user", result.masked_input)
    conversation.append("assistant", result.answer)

    provenance = _provenance(result)
    services.trace_logger.write(
        trace_record(
            result,
            {
                "mode": req.mode,
                "latency_ms": latency_ms,
                "provenance": {k: [i.model_dump() for i in v] for k, v in provenance.items()},
            },
        )
    )
    return ChatResponse(
        request_id=result.request_id,
        conversation_id=result.conversation_id,
        mode=req.mode,
        status=result.status,
        answer=result.answer,
        escalation=result.escalation,
        citations=result.citations,
        pii_detected=result.pii_detected,
        provenance=provenance,
        tools_called=result.tool_names,
        usage=vars(result.usage),
        llm_calls=result.llm_calls,
        latency_ms=latency_ms,
        trace=[e.model_dump(mode="json") for e in result.trace.events],
    )
