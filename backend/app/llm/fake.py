"""테스트·오프라인 데모용 스크립트 LLM.

정해진 응답 목록을 순서대로 반환하거나, 대화 상태를 보고 응답을 만드는 함수를 받는다.
"""

from collections.abc import Callable, Iterable

from app.llm.base import (
    AssistantTurn,
    LLMResponse,
    LLMUsage,
    StopKind,
    ToolCall,
    ToolSpec,
    Turn,
)

Responder = Callable[[str, list[Turn], list[ToolSpec]], LLMResponse]


def say(text: str) -> LLMResponse:
    return LLMResponse(
        stop=StopKind.END,
        assistant=AssistantTurn(text=text),
        usage=LLMUsage(input_tokens=100, output_tokens=50),
        model="fake",
    )


def call(*calls: tuple[str, dict], text: str = "") -> LLMResponse:
    tool_calls = [
        ToolCall(id=f"call_{i}_{name}", name=name, input=args)
        for i, (name, args) in enumerate(calls)
    ]
    return LLMResponse(
        stop=StopKind.TOOL_USE,
        assistant=AssistantTurn(text=text, tool_calls=tool_calls),
        usage=LLMUsage(input_tokens=100, output_tokens=30),
        model="fake",
    )


def stop(kind: StopKind, detail: str | None = None) -> LLMResponse:
    return LLMResponse(
        stop=kind,
        assistant=AssistantTurn(text=""),
        usage=LLMUsage(input_tokens=100, output_tokens=0),
        model="fake",
        stop_detail=detail,
    )


class FakeLLM:
    name = "fake"

    def __init__(self, script: Iterable[LLMResponse] | Responder) -> None:
        self._responder = script if callable(script) else None
        self._queue = None if callable(script) else list(script)
        self.calls: list[tuple[str, list[Turn], list[ToolSpec]]] = []

    def complete(self, *, system: str, turns: list[Turn], tools: list[ToolSpec]) -> LLMResponse:
        self.calls.append((system, list(turns), list(tools)))
        if self._responder is not None:
            return self._responder(system, turns, tools)
        if not self._queue:
            raise AssertionError("FakeLLM script exhausted")
        return self._queue.pop(0)
