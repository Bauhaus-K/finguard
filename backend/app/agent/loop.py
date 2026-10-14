"""tool use 에이전트 루프.

LLM 은 답변을 쓰고 필요한 수치·정보는 도구로만 얻는다. 루프는 다음 경우 상담원 이관(fail-safe)으로 끝난다:
LLM 호출 오류, 안전 정책 거절, 출력 길이 초과, 빈 답변, 최대 단계 초과, 도구 실행 중 예기치 못한 오류,
그리고 LLM 이 escalate_to_human 을 호출한 경우.
"""

import logging
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from app.agent.prompts import SYSTEM_PROMPT
from app.agent.state import ConversationState
from app.agent.tools import ESCALATE_TOOL, TOOL_SPECS, ToolContext, execute_tool
from app.agent.trace import Trace
from app.calc.common import Figure
from app.compliance.numbers import extract_numbers
from app.llm.base import (
    AssistantTurn,
    LLMAdapter,
    LLMError,
    LLMUsage,
    StopKind,
    ToolResult,
    ToolResultsTurn,
    Turn,
    UserTurn,
)
from app.privacy.pii import mask_pii

log = logging.getLogger(__name__)

ESCALATION_MESSAGE = "문의하신 내용은 전문 상담원이 정확하게 도와드리겠습니다. 상담원에게 연결해 드릴게요. 잠시만 기다려 주세요."


class AgentStatus(StrEnum):
    ANSWERED = "ANSWERED"
    ESCALATED = "ESCALATED"


@dataclass(frozen=True)
class SourcedFigure:
    origin: str  # "tool:<name>#<call_id>" 또는 "user"
    figure: Figure


@dataclass
class AgentResult:
    request_id: str
    conversation_id: str
    status: AgentStatus
    answer: str  # LLM 원본 답변(게이트웨이 적용 전) 또는 이관 안내문
    trace: Trace
    escalation: dict[str, str] | None = None
    citations: list[dict[str, str]] = field(default_factory=list)
    figures: list[SourcedFigure] = field(default_factory=list)
    tool_names: list[str] = field(default_factory=list)
    usage: LLMUsage = field(default_factory=LLMUsage)
    llm_calls: int = 0
    masked_input: str = ""
    pii_detected: dict[str, int] = field(default_factory=dict)

    @property
    def source_figures(self) -> list[Figure]:
        return [s.figure for s in self.figures]


def _dedupe(citations: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[tuple[str, str], ...]] = set()
    out = []
    for c in citations:
        key = tuple(sorted(c.items()))
        if key not in seen:
            seen.add(key)
            out.append(c)
    return out


def run_agent(
    *,
    llm: LLMAdapter,
    ctx: ToolContext,
    conversation: ConversationState,
    user_message: str,
    max_steps: int,
    request_id: str | None = None,
) -> AgentResult:
    request_id = request_id or f"req_{uuid.uuid4().hex}"
    trace = Trace(
        request_id=request_id,
        tenant_id=conversation.tenant_id,
        conversation_id=conversation.conversation_id,
    )
    masked = mask_pii(user_message)
    pii_counts = {k.value: v for k, v in masked.counts.items()}
    trace.add(
        "input", text=masked.text, pii_detected=pii_counts, history_len=len(conversation.history)
    )

    result = AgentResult(
        request_id=request_id,
        conversation_id=conversation.conversation_id,
        status=AgentStatus.ANSWERED,
        answer="",
        trace=trace,
        masked_input=masked.text,
        pii_detected=pii_counts,
    )
    # 고객이 직접 말한 수치(예: "1,000만 원", "12개월")는 출처로 인정한다.
    result.figures += [
        SourcedFigure("user", Figure(name="user_input", value=n.value, unit=n.unit))
        for n in extract_numbers(masked.text)
    ]

    turns: list[Turn] = [
        UserTurn(text) if role == "user" else AssistantTurn(text)
        for role, text in conversation.history
    ]
    turns.append(UserTurn(masked.text))

    def escalate(category: str, reason: str) -> AgentResult:
        result.status = AgentStatus.ESCALATED
        result.answer = ESCALATION_MESSAGE
        result.escalation = {"category": category, "reason": reason}
        trace.add("final", status=result.status, answer=result.answer, escalation=result.escalation)
        return result

    for step in range(max_steps):
        try:
            resp = llm.complete(system=SYSTEM_PROMPT, turns=turns, tools=TOOL_SPECS)
        except LLMError as e:
            trace.add("error", step=step, error=str(e))
            return escalate("SYSTEM_ERROR", str(e))
        except Exception as e:  # 자격 증명 누락 등 SDK 의 예기치 못한 오류도 fail-safe 로 처리
            log.exception("LLM call failed")
            trace.add("error", step=step, error=type(e).__name__)
            return escalate("SYSTEM_ERROR", f"LLM 호출 오류: {type(e).__name__}")
        result.llm_calls += 1
        result.usage = result.usage + resp.usage
        trace.add(
            "llm_call",
            step=step,
            model=resp.model,
            stop=resp.stop,
            stop_detail=resp.stop_detail,
            text=resp.assistant.text,
            tool_calls=[
                {"id": c.id, "name": c.name, "input": c.input} for c in resp.assistant.tool_calls
            ],
            usage=vars(resp.usage),
        )
        turns.append(resp.assistant)

        if resp.stop is StopKind.END:
            if not resp.assistant.text.strip():
                return escalate("SYSTEM_ERROR", "빈 답변")
            result.answer = resp.assistant.text
            result.citations = _dedupe(result.citations)
            trace.add("final", status=result.status, answer=result.answer)
            return result
        if resp.stop is StopKind.REFUSAL:
            return escalate("MODEL_REFUSAL", f"모델 거절({resp.stop_detail})")
        if resp.stop is not StopKind.TOOL_USE or not resp.assistant.tool_calls:
            return escalate("SYSTEM_ERROR", f"비정상 종료({resp.stop})")

        tool_results: list[ToolResult] = []
        for call in resp.assistant.tool_calls:
            result.tool_names.append(call.name)
            try:
                out = execute_tool(ctx, call.name, call.input)
            except Exception as e:  # 예기치 못한 오류 → fail-safe
                log.exception("tool %s failed", call.name)
                trace.add("error", step=step, tool=call.name, error=type(e).__name__)
                return escalate("SYSTEM_ERROR", f"도구 실행 오류: {call.name}")
            trace.add(
                "tool_call",
                step=step,
                call_id=call.id,
                name=call.name,
                input=call.input,
                output=out.payload,
                is_error=out.is_error,
                figures=[
                    {"name": f.name, "unit": f.unit, "value": str(f.value)} for f in out.figures
                ],
            )
            if call.name == ESCALATE_TOOL:
                return escalate(call.input.get("category", "OTHER"), call.input.get("summary", ""))
            if not out.is_error:
                origin = f"tool:{call.name}#{call.id}"
                result.figures += [SourcedFigure(origin, f) for f in out.figures]
                result.citations += out.citations
            tool_results.append(ToolResult(call.id, out.to_llm_content(), out.is_error))
        turns.append(ToolResultsTurn(tool_results))

    return escalate("SYSTEM_ERROR", f"최대 단계({max_steps}) 초과")


def trace_record(result: AgentResult, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        **result.trace.model_dump(mode="json"),
        "status": result.status,
        "answer": result.answer,
        "escalation": result.escalation,
        "citations": result.citations,
        "usage": vars(result.usage),
        "llm_calls": result.llm_calls,
        **(extra or {}),
    }
