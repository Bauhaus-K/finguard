"""상담 요청 처리: 에이전트 → 게이트웨이 → (수치 검증 실패 시 재생성 1회) → 감사 로그.

게이트웨이를 거친 최종 답변만 고객에게 전달되고 대화 이력에 남는다(debug 모드 제외).
"""

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.loop import AgentResult, AgentStatus, run_agent
from app.agent.state import ConversationState
from app.agent.tools import ToolContext
from app.audit.hashchain import append_audit
from app.db.models import Product
from app.gateway.checks import CheckContext
from app.gateway.engine import run_gateway
from app.gateway.rules import LoadedRules
from app.gateway.types import (
    GatewayDecision,
    GatewayInput,
    GatewayStatus,
    ProductRef,
    SuitabilityInfo,
)
from app.llm.base import LLMUsage
from app.services import Services

Mode = Literal["standard", "debug"]
CALC_TOOLS = {"calculate_deposit", "calculate_savings", "calculate_loan"}
MAX_ATTEMPTS = 2  # 최초 1회 + 재생성 1회


@dataclass
class Attempt:
    agent: AgentResult
    gateway: GatewayDecision | None


@dataclass
class ChatOutcome:
    request_id: str
    conversation_id: str
    mode: Mode
    status: GatewayStatus
    answer: str  # 고객에게 전달되는 답변 (debug 모드에서는 원본 답변)
    attempts: list[Attempt]
    escalation: dict[str, str] | None
    latency_ms: int
    rules: LoadedRules
    usage: LLMUsage = field(default_factory=LLMUsage)

    @property
    def last(self) -> Attempt:
        return self.attempts[-1]


def product_refs(session: Session, tenant_id: str) -> list[ProductRef]:
    rows = session.scalars(select(Product).where(Product.tenant_id == tenant_id))
    return [ProductRef(code=p.code, name=p.name, product_type=p.product_type.value) for p in rows]


def gateway_input(
    result: AgentResult, conversation: ConversationState, products: list[ProductRef]
) -> GatewayInput:
    by_code = {p.code: p.product_type for p in products}
    calc_types = [
        by_code[e.data["input"]["product_code"]]
        for e in result.trace.events
        if e.kind == "tool_call"
        and e.data["name"] in CALC_TOOLS
        and not e.data["is_error"]
        and e.data["input"].get("product_code") in by_code
    ]
    s = conversation.suitability
    return GatewayInput(
        user_message=result.masked_input,
        answer=result.answer,
        sources=result.source_figures,
        tools_called=result.tool_names,
        product_types=sorted(set(calc_types)),
        products=products,
        suitability=SuitabilityInfo(
            recorded=s is not None, declined=bool(s and s.get("customer_declined"))
        ),
    )


def regeneration_note(decision: GatewayDecision) -> str:
    issues = [
        f.excerpt or f.message
        for c in decision.failed()
        for f in c.findings
        if f.severity == "violation"
    ]
    return (
        "[게이트웨이 검수] 직전에 작성한 답변이 차단되었습니다. 사유: 도구 결과에 없는 수치 "
        f"({', '.join(issues)}). 모든 수치는 이번 답변을 위해 호출한 도구 결과의 값을 그대로 쓰고, "
        "직접 계산·반올림·어림하지 마세요. 필요한 도구를 다시 호출한 뒤 답변을 새로 작성하세요."
    )


def handle_chat(
    *,
    services: Services,
    session: Session,
    tenant_id: str,
    conversation: ConversationState,
    message: str,
    mode: Mode = "standard",
) -> ChatOutcome:
    t0 = time.perf_counter()
    request_id = f"req_{uuid.uuid4().hex}"
    loaded = services.rules.get(tenant_id)
    escalation_text = loaded.rules.messages.escalation if loaded.rules else None
    products = product_refs(session, tenant_id)
    ctx = ToolContext(session, tenant_id, services.settings, services.retriever, conversation)

    attempts: list[Attempt] = []
    note: str | None = None
    # debug 모드는 원본 답변 점검용이므로 재생성하지 않고 1회 판정만 보여준다
    max_attempts = 1 if mode == "debug" else MAX_ATTEMPTS
    for _ in range(max_attempts):
        result = run_agent(
            llm=services.llm,
            ctx=ctx,
            conversation=conversation,
            user_message=message,
            max_steps=services.settings.agent_max_steps,
            request_id=request_id,
            system_note=note,
        )
        if result.status is AgentStatus.ESCALATED:
            attempts.append(Attempt(result, None))
            break
        decision = run_gateway(
            gateway_input(result, conversation, products),
            loaded,
            CheckContext(judge_llm=services.llm),
        )
        attempts.append(Attempt(result, decision))
        if not (decision.status is GatewayStatus.BLOCKED and decision.retryable):
            break
        note = regeneration_note(decision)

    last = attempts[-1]
    escalation = None
    if last.gateway is None:  # 에이전트가 이관
        status = GatewayStatus.ESCALATED
        answer = escalation_text or last.agent.answer
        escalation = last.agent.escalation
    elif (
        last.gateway.status is GatewayStatus.BLOCKED
        and last.gateway.retryable
        and len(attempts) == MAX_ATTEMPTS
    ):
        # 수치 검증 실패가 재생성 후에도 계속 → 이관
        status = GatewayStatus.ESCALATED
        answer = escalation_text or last.agent.answer
        escalation = {
            "category": "GATEWAY",
            "reason": "수치 검증 실패(재생성 후에도 출처 없는 수치)",
        }
    else:
        status = last.gateway.status
        answer = last.gateway.final_answer
        if status is GatewayStatus.ESCALATED:
            failed = last.gateway.failed()
            escalation = {
                "category": "GATEWAY",
                "reason": "; ".join(
                    f"{c.check}: {c.findings[-1].message}" for c in failed if c.findings
                ),
            }

    usage = LLMUsage()
    for a in attempts:
        usage = usage + a.agent.usage
    shown = last.agent.answer if mode == "debug" else answer
    conversation.append("user", last.agent.masked_input)
    conversation.append("assistant", shown)

    outcome = ChatOutcome(
        request_id=request_id,
        conversation_id=conversation.conversation_id,
        mode=mode,
        status=status,
        answer=shown,
        attempts=attempts,
        escalation=escalation,
        latency_ms=int((time.perf_counter() - t0) * 1000),
        rules=loaded,
        usage=usage,
    )
    append_audit(
        session,
        tenant_id=tenant_id,
        request_id=request_id,
        status=status.value,
        payload=audit_payload(outcome, services),
    )
    return outcome


def _agent_record(r: AgentResult) -> dict[str, Any]:
    return {
        "status": r.status,
        "raw_answer": r.answer,
        "escalation": r.escalation,
        "tools": [
            {k: e.data[k] for k in ("call_id", "name", "input", "output", "is_error")}
            for e in r.trace.events
            if e.kind == "tool_call"
        ],
        "citations": r.citations,
        "llm_calls": r.llm_calls,
        "usage": vars(r.usage),
        "trace": [e.model_dump(mode="json") for e in r.trace.events],
    }


def audit_payload(outcome: ChatOutcome, services: Services) -> dict[str, Any]:
    first = outcome.attempts[0].agent
    last_gateway = outcome.last.gateway
    return {
        "mode": outcome.mode,
        "conversation_id": outcome.conversation_id,
        # 실제 응답한 공급자·모델 (스크립트 모드는 실제 LLM 이 아님)
        "llm_provider": services.settings.llm_provider,
        "model": (
            services.settings.llm_model
            if services.settings.llm_provider == "anthropic"
            else services.settings.llm_provider
        ),
        "input": {"user_message": first.masked_input, "pii_detected": first.pii_detected},
        "attempts": [
            {
                "attempt": i + 1,
                "agent": _agent_record(a.agent),
                "gateway": a.gateway.model_dump(mode="json") if a.gateway else None,
            }
            for i, a in enumerate(outcome.attempts)
        ],
        "gateway": last_gateway.model_dump(mode="json") if last_gateway else None,
        "final": {
            "status": outcome.status,
            "answer": outcome.answer,
            "escalation": outcome.escalation,
        },
        "rules": {
            "version": outcome.rules.rules.version if outcome.rules.rules else None,
            "digest": outcome.rules.digest,
            "files": outcome.rules.files,
            "error": outcome.rules.error,
        },
        "latency_ms": outcome.latency_ms,
        "usage": vars(outcome.usage),
    }
