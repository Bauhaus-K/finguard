import pytest

from app.agent.loop import ESCALATION_MESSAGE, AgentStatus, run_agent
from app.agent.trace import mask_deep
from app.compliance.provenance import check_provenance
from app.llm.base import AssistantTurn, LLMError, StopKind, ToolResultsTurn, UserTurn
from app.llm.fake import FakeLLM, call, say, stop

DEPOSIT_CALL = (
    "calculate_deposit",
    dict(
        product_code="HB-DEP-001",
        principal=10_000_000,
        months=12,
        include_preferential=False,
        tax_type="GENERAL",
        early_termination_after_months=None,
    ),
)


def _run(
    llm, tool_ctx, conversation, message="1,000만 원을 12개월 예금하면 이자가 얼마예요?", steps=8
):
    return run_agent(
        llm=llm, ctx=tool_ctx, conversation=conversation, user_message=message, max_steps=steps
    )


def test_tool_then_answer(tool_ctx, conversation):
    answer = "한빛 정기예금(가상)(HB-DEP-001) 기준 세후 이자는 279,180원입니다(세전 330,000원, 연 3.30%)."
    llm = FakeLLM([call(DEPOSIT_CALL), say(answer)])
    r = _run(llm, tool_ctx, conversation)

    assert r.status is AgentStatus.ANSWERED
    assert r.answer == answer
    assert r.llm_calls == 2
    assert r.tool_names == ["calculate_deposit"]
    assert r.citations == [
        {"type": "product", "product_code": "HB-DEP-001", "name": "한빛 정기예금(가상)"}
    ]
    assert check_provenance(r.answer, r.source_figures).ok
    # 두 번째 호출에는 assistant tool_use turn 과 tool 결과가 이어진다
    turns = llm.calls[1][1]
    assert isinstance(turns[-2], AssistantTurn) and isinstance(turns[-1], ToolResultsTurn)
    assert "279180" in turns[-1].results[0].content
    kinds = [e.kind for e in r.trace.events]
    assert kinds == ["input", "llm_call", "tool_call", "llm_call", "final"]
    assert r.usage.input_tokens == 200


def test_hallucinated_number_detected_by_provenance(tool_ctx, conversation):
    llm = FakeLLM([call(DEPOSIT_CALL), say("세후 이자는 약 30만 원입니다.")])
    r = _run(llm, tool_ctx, conversation)
    report = check_provenance(r.answer, r.source_figures)
    assert [n.text for n in report.unsourced] == ["30만 원"]


def test_user_numbers_count_as_sources(tool_ctx, conversation):
    llm = FakeLLM(
        [say("1,000만 원을 12개월 맡기시는 경우를 안내해 드릴게요. 상품을 먼저 골라 주세요.")]
    )
    r = _run(llm, tool_ctx, conversation)
    assert check_provenance(r.answer, r.source_figures).ok


def test_pii_masked_before_llm(tool_ctx, conversation):
    llm = FakeLLM([say("개인정보는 입력하지 않으셔도 됩니다.")])
    r = _run(llm, tool_ctx, conversation, message="제 주민번호 900101-1234567 로 조회해 주세요")
    sent = llm.calls[0][1][-1]
    assert isinstance(sent, UserTurn)
    assert "900101" not in sent.text and "[주민등록번호]" in sent.text
    assert r.pii_detected == {"RRN": 1}
    assert "900101" not in str(mask_deep(r.trace.model_dump(mode="json")))


def test_history_is_replayed_as_text(tool_ctx, conversation):
    conversation.append("user", "안녕하세요")
    conversation.append("assistant", "무엇을 도와드릴까요?")
    llm = FakeLLM([say("네")])
    _run(llm, tool_ctx, conversation, message="예금 상품 알려주세요")
    turns = llm.calls[0][1]
    assert [type(t).__name__ for t in turns] == ["UserTurn", "AssistantTurn", "UserTurn"]
    assert turns[1].raw is None


def test_escalate_tool(tool_ctx, conversation):
    llm = FakeLLM(
        [call(("escalate_to_human", {"category": "OUT_OF_SCOPE", "summary": "주식 추천 요청"}))]
    )
    r = _run(llm, tool_ctx, conversation, message="삼성전자 주식 사도 돼요?")
    assert r.status is AgentStatus.ESCALATED
    assert r.answer == ESCALATION_MESSAGE
    assert r.escalation == {"category": "OUT_OF_SCOPE", "reason": "주식 추천 요청"}


def test_tool_error_is_fed_back(tool_ctx, conversation):
    bad = ("get_product_detail", {"product_code": "NOPE"})
    llm = FakeLLM([call(bad), say("상품을 찾지 못했습니다.")])
    r = _run(llm, tool_ctx, conversation)
    result = llm.calls[1][1][-1].results[0]
    assert result.is_error
    assert r.status is AgentStatus.ANSWERED
    assert r.citations == []


@pytest.mark.parametrize(
    ("response", "category"),
    [
        (stop(StopKind.REFUSAL, "general_harms"), "MODEL_REFUSAL"),
        (stop(StopKind.MAX_TOKENS), "SYSTEM_ERROR"),
        (stop(StopKind.OTHER), "SYSTEM_ERROR"),
        (stop(StopKind.TOOL_USE), "SYSTEM_ERROR"),  # tool_use 인데 호출 없음
        (say("   "), "SYSTEM_ERROR"),
    ],
)
def test_fail_safe_stops(tool_ctx, conversation, response, category):
    r = _run(FakeLLM([response]), tool_ctx, conversation)
    assert r.status is AgentStatus.ESCALATED
    assert r.escalation["category"] == category
    assert r.answer == ESCALATION_MESSAGE


def test_llm_error_escalates(tool_ctx, conversation):
    def boom(*_):
        raise LLMError("LLM API 오류(status=500)")

    r = _run(FakeLLM(boom), tool_ctx, conversation)
    assert r.status is AgentStatus.ESCALATED
    assert r.trace.events[-2].kind == "error"


def test_unexpected_llm_exception_escalates(tool_ctx, conversation):
    def boom(*_):
        raise TypeError("Could not resolve authentication method")

    r = _run(FakeLLM(boom), tool_ctx, conversation)
    assert r.status is AgentStatus.ESCALATED
    assert r.escalation["reason"] == "LLM 호출 오류: TypeError"


def test_max_steps(tool_ctx, conversation):
    llm = FakeLLM(lambda *_: call(("search_products", {"product_type": None, "keyword": None})))
    r = _run(llm, tool_ctx, conversation, steps=3)
    assert r.status is AgentStatus.ESCALATED
    assert "최대 단계" in r.escalation["reason"]
    assert r.llm_calls == 3


def test_unexpected_tool_exception_escalates(tool_ctx, conversation, monkeypatch):
    from app.agent import tools

    def explode(ctx, args):
        raise RuntimeError("db down")

    monkeypatch.setitem(tools.EXECUTORS, "search_products", explode)
    llm = FakeLLM([call(("search_products", {"product_type": None, "keyword": None}))])
    r = _run(llm, tool_ctx, conversation)
    assert r.status is AgentStatus.ESCALATED
    assert "search_products" in r.escalation["reason"]


def test_citations_deduped(tool_ctx, conversation):
    llm = FakeLLM([call(DEPOSIT_CALL, DEPOSIT_CALL), say("279,180원")])
    r = _run(llm, tool_ctx, conversation)
    assert len(r.citations) == 1


def test_conversation_store_eviction_and_history_cap():
    from app.agent.state import MAX_HISTORY_MESSAGES, ConversationStore

    store = ConversationStore(max_size=2)
    a = store.get_or_create("demo", None)
    assert store.get_or_create("demo", a.conversation_id) is a
    assert store.get_or_create("other", a.conversation_id) is not a  # 테넌트 분리
    store.get_or_create("demo", None)
    assert store.get_or_create("demo", a.conversation_id) is not a  # 가장 오래된 대화 제거됨
    for i in range(MAX_HISTORY_MESSAGES + 5):
        a.append("user", str(i))
    assert len(a.history) == MAX_HISTORY_MESSAGES


def test_system_note_appended_after_user_turn(tool_ctx, conversation):
    from app.llm.base import SystemNoteTurn

    llm = FakeLLM([say("네")])
    r = run_agent(
        llm=llm,
        ctx=tool_ctx,
        conversation=conversation,
        user_message="질문",
        max_steps=3,
        system_note="다시 작성하세요",
    )
    turns = llm.calls[0][1]
    assert isinstance(turns[-2], UserTurn) and turns[-1] == SystemNoteTurn("다시 작성하세요")
    assert r.trace.events[1].kind == "system_note"
