"""공급자 중립 LLM 인터페이스.

대화는 세 종류의 turn 으로 표현한다.
- UserTurn: 사용자 텍스트
- AssistantTurn: 모델 응답. `raw` 에 공급자 원본 블록을 보관해 같은 요청의 다음 호출에
  변경 없이 되돌려 보낸다(예: Anthropic thinking 블록은 원본 그대로 재전송해야 한다).
- ToolResultsTurn: 한 assistant turn 의 모든 도구 호출 결과(한 메시지로 묶어서 반환)
- SystemNoteTurn: 운영자(시스템) 메모. 공급자가 지원하는 대화 중간 system 메시지로 전달
"""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol


class StopKind(StrEnum):
    END = "END"  # 최종 답변 완료
    TOOL_USE = "TOOL_USE"  # 도구 호출 요청
    MAX_TOKENS = "MAX_TOKENS"  # 출력 길이 초과 (불완전)
    REFUSAL = "REFUSAL"  # 모델 안전 정책상 거절
    OTHER = "OTHER"


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    input: dict[str, Any]


@dataclass(frozen=True)
class ToolResult:
    tool_call_id: str
    content: str
    is_error: bool = False


@dataclass(frozen=True)
class UserTurn:
    text: str


@dataclass(frozen=True)
class AssistantTurn:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw: Any = None  # 공급자 원본 content (재전송용, 불투명 값)


@dataclass(frozen=True)
class ToolResultsTurn:
    results: list[ToolResult]


@dataclass(frozen=True)
class SystemNoteTurn:
    """대화 중간의 운영자 지시(예: 게이트웨이 차단 후 재생성 피드백). 사용자 turn 바로 뒤에 둔다."""

    text: str


Turn = UserTurn | AssistantTurn | ToolResultsTurn | SystemNoteTurn


@dataclass(frozen=True)
class LLMUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0

    def __add__(self, other: "LLMUsage") -> "LLMUsage":
        return LLMUsage(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
            self.cache_read_input_tokens + other.cache_read_input_tokens,
            self.cache_creation_input_tokens + other.cache_creation_input_tokens,
        )


@dataclass(frozen=True)
class LLMResponse:
    stop: StopKind
    assistant: AssistantTurn
    usage: LLMUsage
    model: str
    stop_detail: str | None = None  # 거절 카테고리 등


class LLMError(Exception):
    """LLM 호출 실패. 에이전트는 이를 받으면 상담원 이관(fail-safe)으로 처리한다."""


class LLMAdapter(Protocol):
    name: str

    def complete(self, *, system: str, turns: list[Turn], tools: list[ToolSpec]) -> LLMResponse: ...
