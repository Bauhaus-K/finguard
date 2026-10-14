"""Anthropic Claude 어댑터.

- 모델은 설정값 LLM_MODEL (기본 claude-sonnet-5-5).
- 사고(thinking)는 adaptive(기본값), 노력 수준은 LLM_EFFORT.
- 도구는 strict 스키마로 정의하고 tool_choice 는 auto(기본)를 쓴다.
- system + tools 는 요청마다 바이트 단위로 동일하게 유지해 prompt caching 을 활용한다.
- 안전 정책 거절(refusal) 시 서버측 fallback 을 선택적으로 사용한다(LLM_REFUSAL_FALLBACK).
"""

import logging
from typing import Any

import anthropic

from app.llm.base import (
    AssistantTurn,
    LLMError,
    LLMResponse,
    LLMUsage,
    StopKind,
    SystemNoteTurn,
    ToolCall,
    ToolResultsTurn,
    ToolSpec,
    Turn,
    UserTurn,
)

log = logging.getLogger(__name__)

FALLBACK_BETA = "server-side-fallback-2026-07-01"

_STOP_MAP = {
    "end_turn": StopKind.END,
    "tool_use": StopKind.TOOL_USE,
    "max_tokens": StopKind.MAX_TOKENS,
    "refusal": StopKind.REFUSAL,
}


def _to_messages(turns: list[Turn]) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for turn in turns:
        if isinstance(turn, UserTurn):
            messages.append({"role": "user", "content": turn.text})
        elif isinstance(turn, AssistantTurn):
            # 같은 요청 안의 assistant turn 은 원본 블록(thinking 포함)을 그대로 재전송한다.
            content = turn.raw if turn.raw is not None else turn.text
            messages.append({"role": "assistant", "content": content})
        elif isinstance(turn, SystemNoteTurn):
            # 대화 중간 system 메시지: 사용자 turn 뒤에 오며 캐시된 앞부분을 바꾸지 않는다
            messages.append({"role": "system", "content": turn.text})
        elif isinstance(turn, ToolResultsTurn):
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": r.tool_call_id,
                            "content": r.content,
                            "is_error": r.is_error,
                        }
                        for r in turn.results
                    ],
                }
            )
    return messages


def _to_tools(tools: list[ToolSpec]) -> list[dict[str, Any]]:
    return [
        {
            "name": t.name,
            "description": t.description,
            "input_schema": t.input_schema,
            "strict": True,
        }
        for t in tools
    ]


class AnthropicAdapter:
    name = "anthropic"

    def __init__(
        self,
        *,
        model: str,
        api_key: str | None,
        effort: str = "medium",
        max_tokens: int = 16000,
        timeout: float = 120.0,
        refusal_fallback: bool = True,
        client: anthropic.Anthropic | None = None,
    ) -> None:
        self.model = model
        self.effort = effort
        self.max_tokens = max_tokens
        self.refusal_fallback = refusal_fallback
        # api_key 가 None 이면 SDK 가 환경(ANTHROPIC_API_KEY 등)에서 자격 증명을 찾는다.
        self._client = client or anthropic.Anthropic(api_key=api_key, timeout=timeout)

    def complete(self, *, system: str, turns: list[Turn], tools: list[ToolSpec]) -> LLMResponse:
        params: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": system,
            "tools": _to_tools(tools),
            "messages": _to_messages(turns),
            "output_config": {"effort": self.effort},
            "cache_control": {"type": "ephemeral"},
        }
        try:
            if self.refusal_fallback:
                response = self._client.beta.messages.create(
                    **params, betas=[FALLBACK_BETA], fallbacks="default"
                )
            else:
                response = self._client.messages.create(**params)
        except anthropic.APIConnectionError as e:
            raise LLMError(f"LLM 연결 실패: {type(e).__name__}") from e
        except anthropic.RateLimitError as e:
            raise LLMError("LLM 호출 한도 초과(429)") from e
        except anthropic.APIStatusError as e:
            # 메시지 본문에 요청 내용이 섞일 수 있으므로 상태 코드만 남긴다
            raise LLMError(f"LLM API 오류(status={e.status_code})") from e

        text_parts = [b.text for b in response.content if b.type == "text"]
        tool_calls = [
            ToolCall(id=b.id, name=b.name, input=dict(b.input))
            for b in response.content
            if b.type == "tool_use"
        ]
        usage = response.usage
        stop_detail = None
        if response.stop_reason == "refusal" and getattr(response, "stop_details", None):
            stop_detail = response.stop_details.category
        return LLMResponse(
            stop=_STOP_MAP.get(response.stop_reason or "", StopKind.OTHER),
            assistant=AssistantTurn(
                text="\n".join(text_parts), tool_calls=tool_calls, raw=response.content
            ),
            usage=LLMUsage(
                input_tokens=usage.input_tokens or 0,
                output_tokens=usage.output_tokens or 0,
                cache_read_input_tokens=usage.cache_read_input_tokens or 0,
                cache_creation_input_tokens=usage.cache_creation_input_tokens or 0,
            ),
            model=response.model,
            stop_detail=stop_detail,
        )
