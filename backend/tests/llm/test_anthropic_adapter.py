from types import SimpleNamespace as NS

import anthropic
import httpx2
import pytest

from app.config import Settings
from app.llm.anthropic_adapter import FALLBACK_BETA, AnthropicAdapter
from app.llm.base import (
    AssistantTurn,
    LLMError,
    StopKind,
    ToolCall,
    ToolResult,
    ToolResultsTurn,
    ToolSpec,
    UserTurn,
)
from app.llm.factory import build_llm

TOOL = ToolSpec(
    "t", "desc", {"type": "object", "properties": {}, "required": [], "additionalProperties": False}
)


def _response(content, stop_reason="end_turn", stop_details=None):
    return NS(
        content=content,
        stop_reason=stop_reason,
        stop_details=stop_details,
        model="claude-sonnet-5-5",
        usage=NS(
            input_tokens=10,
            output_tokens=5,
            cache_read_input_tokens=3,
            cache_creation_input_tokens=None,
        ),
    )


class FakeMessages:
    def __init__(self, response=None, error=None):
        self.response, self.error, self.kwargs = response, error, None

    def create(self, **kwargs):
        self.kwargs = kwargs
        if self.error:
            raise self.error
        return self.response


def _client(messages):
    return NS(messages=messages, beta=NS(messages=messages))


def test_request_shape_with_fallback():
    thinking = NS(type="thinking", thinking="")
    msgs = FakeMessages(
        _response(
            [
                thinking,
                NS(type="text", text="계산할게요"),
                NS(type="tool_use", id="tu1", name="t", input={"a": 1}),
            ],
            stop_reason="tool_use",
        )
    )
    adapter = AnthropicAdapter(model="claude-sonnet-5-5", api_key="k", client=_client(msgs))
    prior = AssistantTurn(text="x", tool_calls=[ToolCall("tu0", "t", {})], raw=["RAW-BLOCKS"])
    resp = adapter.complete(
        system="SYS",
        turns=[UserTurn("질문"), prior, ToolResultsTurn([ToolResult("tu0", "{}", is_error=True)])],
        tools=[TOOL],
    )
    kw = msgs.kwargs
    assert kw["model"] == "claude-sonnet-5-5"
    assert kw["system"] == "SYS"
    assert kw["tools"][0]["strict"] is True
    assert kw["output_config"] == {"effort": "medium"}
    assert kw["cache_control"] == {"type": "ephemeral"}
    assert kw["betas"] == [FALLBACK_BETA] and kw["fallbacks"] == "default"
    assert "thinking" not in kw  # adaptive 기본값 사용
    assert kw["messages"][1] == {"role": "assistant", "content": ["RAW-BLOCKS"]}
    assert kw["messages"][2]["content"][0] == {
        "type": "tool_result",
        "tool_use_id": "tu0",
        "content": "{}",
        "is_error": True,
    }

    assert resp.stop is StopKind.TOOL_USE
    assert resp.assistant.text == "계산할게요"
    assert resp.assistant.tool_calls == [ToolCall("tu1", "t", {"a": 1})]
    assert resp.assistant.raw[0] is thinking  # 원본 블록 보존
    assert resp.usage.cache_read_input_tokens == 3
    assert resp.usage.cache_creation_input_tokens == 0


def test_without_fallback_uses_plain_endpoint():
    msgs = FakeMessages(_response([NS(type="text", text="답")]))
    adapter = AnthropicAdapter(model="m", api_key="k", refusal_fallback=False, client=_client(msgs))
    resp = adapter.complete(system="S", turns=[UserTurn("q")], tools=[])
    assert "betas" not in msgs.kwargs
    assert resp.stop is StopKind.END


def test_refusal_and_unknown_stop():
    msgs = FakeMessages(_response([], "refusal", NS(category="cyber")))
    adapter = AnthropicAdapter(model="m", api_key="k", client=_client(msgs))
    resp = adapter.complete(system="S", turns=[UserTurn("q")], tools=[])
    assert resp.stop is StopKind.REFUSAL and resp.stop_detail == "cyber"
    msgs.response = _response([], "pause_turn")
    assert adapter.complete(system="S", turns=[UserTurn("q")], tools=[]).stop is StopKind.OTHER


_REQ = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (anthropic.APIConnectionError(request=_REQ), "연결 실패"),
        (
            anthropic.RateLimitError("rl", response=httpx2.Response(429, request=_REQ), body=None),
            "429",
        ),
        (
            anthropic.InternalServerError(
                "secret prompt", response=httpx2.Response(500, request=_REQ), body=None
            ),
            "status=500",
        ),
    ],
)
def test_errors_mapped(error, message):
    adapter = AnthropicAdapter(model="m", api_key="k", client=_client(FakeMessages(error=error)))
    with pytest.raises(LLMError, match=message) as exc:
        adapter.complete(system="S", turns=[UserTurn("q")], tools=[])
    assert "secret prompt" not in str(exc.value)


def test_factory():
    llm = build_llm(Settings(_env_file=None, anthropic_api_key="sk-test", llm_effort="low"))
    assert isinstance(llm, AnthropicAdapter)
    assert llm.model == "claude-sonnet-5-5" and llm.effort == "low"
    with pytest.raises(ValueError):
        build_llm(Settings(_env_file=None, llm_provider="other"))
