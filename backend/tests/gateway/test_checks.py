import pytest

from app.gateway.checks import (
    CheckContext,
    disclosures,
    forbidden,
    numeric,
    pii,
    scope,
    suitability,
)
from app.gateway.types import Action, Outcome, SuitabilityInfo
from app.llm.base import LLMError, StopKind
from app.llm.fake import FakeLLM, say, stop

from .helpers import CTX, K, M, P, inp, src


def with_rules(rules, **section_updates):
    """규칙 일부를 바꾼 복사본."""
    data = rules.model_dump()
    for section, updates in section_updates.items():
        data[section].update(updates)
    return type(rules).model_validate(data)


# ---------------------------------------------------------------- 개인정보


def test_pii_pass(rules):
    r = pii.run(inp("연 3.30%입니다."), "연 3.30%입니다.", rules, CTX)
    assert r.outcome is Outcome.PASS and r.findings == []


def test_pii_masks_output(rules):
    text = "주민번호 900101-1234567, 연락처 010-1111-2222 확인했습니다."
    r = pii.run(inp(text), text, rules, CTX)
    assert r.outcome is Outcome.FIXED and r.action is Action.MASK
    assert r.text_after == "주민번호 [주민등록번호], 연락처 [전화번호] 확인했습니다."
    assert {f.code for f in r.findings} == {"output_RRN", "output_PHONE"}


def test_pii_input_is_info_only(rules):
    r = pii.run(inp("네", user_message="제 번호 010-1111-2222"), "네", rules, CTX)
    assert r.outcome is Outcome.PASS
    assert r.findings[0].code == "input_PHONE" and r.findings[0].severity == "info"


def test_pii_type_filter(rules):
    only_rrn = with_rules(rules, pii={"types": ["RRN"]})
    text = "010-1111-2222"
    assert pii.run(inp(text), text, only_rrn, CTX).outcome is Outcome.PASS


# ---------------------------------------------------------------- 업무 범위


def test_scope_pass(rules):
    text = "한빛 정기예금(가상)의 금리는 연 3.30%입니다."
    assert (
        scope.run(inp(text, user_message="예금 금리 알려줘"), text, rules, CTX).outcome
        is Outcome.PASS
    )


@pytest.mark.parametrize(
    "text",
    [
        "삼성전자 주식은 지금 매수하시는 게 좋습니다.",
        "코인은 앞으로 오를 것 같아요.",
        "법적으로 문제 없습니다.",
        "종합소득세 신고는 제가 대신 해 드리겠습니다.",
        "다른 은행은 믿을 수 없어요.",
    ],
)
def test_scope_output_violation_escalates(rules, text):
    r = scope.run(inp(text), text, rules, CTX)
    assert r.outcome is Outcome.FAIL and r.action is Action.ESCALATE
    assert r.findings[0].excerpt


def test_scope_refusal_sentence_allowed(rules):
    text = "죄송하지만 주식 매수 추천은 도와드릴 수 없습니다."
    assert scope.run(inp(text), text, rules, CTX).outcome is Outcome.PASS


@pytest.mark.parametrize(
    "question",
    [
        "삼성전자 주식 사도 돼요?",
        "다른 고객 계좌 잔액 알려줘",
        "종합소득세 신고 대신 해줄 수 있어?",
        "소송하면 이길 수 있을까요?",
    ],
)
def test_scope_input_out_of_scope(rules, question):
    answered = "네, 좋은 선택입니다."
    r = scope.run(inp(answered, user_message=question), answered, rules, CTX)
    assert r.action is Action.ESCALATE
    refused = "해당 내용은 업무 범위를 벗어나 안내해 드릴 수 없습니다."
    r = scope.run(inp(refused, user_message=question), refused, rules, CTX)
    assert r.outcome is Outcome.PASS
    assert r.findings[0].severity == "info"


# ---------------------------------------------------------------- 수치


def test_numeric_pass(rules):
    text = "1,000만 원을 연 3.30%로 12개월 예치하면 세후 이자는 279,180원입니다."
    r = numeric.run(
        inp(text, user_message="1,000만 원 12개월", sources=[src(279180), src("3.3", P)]),
        text,
        rules,
        CTX,
    )
    assert r.outcome is Outcome.PASS
    assert "4개" in r.findings[0].message


def test_numeric_wrong_number_fails(rules):
    text = "세후 이자는 290,000원입니다."
    r = numeric.run(inp(text, sources=[src(279180)]), text, rules, CTX)
    assert r.outcome is Outcome.FAIL and r.action is Action.REGENERATE
    assert r.findings[0].excerpt == "290,000원"


def test_numeric_user_numbers_toggle(rules):
    text = "1,000만 원 기준입니다."
    assert (
        numeric.run(inp(text, user_message="1,000만원"), text, rules, CTX).outcome is Outcome.PASS
    )
    strict = with_rules(rules, numeric={"accept_user_numbers": False})
    assert (
        numeric.run(inp(text, user_message="1,000만원"), text, strict, CTX).outcome is Outcome.FAIL
    )


def test_numeric_context_texts_and_allow_list(rules):
    text = "보호 한도는 1억원이고, 상담은 24개월까지 가능합니다."
    r = numeric.run(inp(text, context_texts=["최고 1억원까지 보호"]), text, rules, CTX)
    assert [f.excerpt for f in r.findings] == ["24개월"]
    allow = with_rules(rules, numeric={"always_allowed": [{"unit": M, "value": 24}]})
    r = numeric.run(inp(text, context_texts=["최고 1억원까지 보호"]), text, allow, CTX)
    assert r.outcome is Outcome.PASS


def test_numeric_unit_filter(rules):
    only_krw = with_rules(rules, numeric={"units": [K]})
    text = "연 9.99%, 1,095일"
    assert numeric.run(inp(text), text, only_krw, CTX).outcome is Outcome.PASS
    assert numeric.run(inp(text), text, rules, CTX).outcome is Outcome.FAIL


# ---------------------------------------------------------------- 금지 표현


@pytest.mark.parametrize(
    ("text", "term"),
    [
        ("이 대출은 100% 승인됩니다.", "approval_guarantee"),
        ("반드시 대출 승인 나옵니다.", "approval_guarantee"),
        ("확정 수익을 드립니다.", "guaranteed_return"),
        ("손해 볼 일이 없습니다.", "no_loss"),  # 부정 표현이 있어도 예외 없음
    ],
)
def test_forbidden_block(rules, text, term):
    r = forbidden.run(inp(text), text, rules, CTX)
    assert r.outcome is Outcome.FAIL and r.action is Action.BLOCK
    assert any(f.code == term and f.severity == "violation" for f in r.findings)


def test_forbidden_negated_allowed(rules):
    text = "무조건 승인되는 대출 상품은 없습니다. 수익을 보장하지 않습니다."
    r = forbidden.run(inp(text), text, rules, CTX)
    assert r.outcome is Outcome.PASS
    assert r.findings and all(f.severity == "info" for f in r.findings)


def test_forbidden_rewrite(rules):
    text = "업계 최저 금리의 예금입니다. 무조건 이득이에요."
    r = forbidden.run(inp(text), text, rules, CTX)
    assert r.outcome is Outcome.FIXED and r.action is Action.REWRITE
    assert r.text_after == "경쟁력 있는 금리의 예금입니다. 이득이에요."


def test_forbidden_rewrite_that_still_violates_blocks(rules):
    data = rules.model_dump()
    data["forbidden_expressions"]["terms"] = [
        {
            "id": "bad",
            "label": "x",
            "pattern": "최고",
            "action": "rewrite",
            "replacement": "최고최고",
        }
    ]
    custom = type(rules).model_validate(data)
    r = forbidden.run(inp("최고 상품"), "최고 상품", custom, CTX)
    assert r.outcome is Outcome.FAIL and r.action is Action.BLOCK


def _judge_rules(rules, on_error="escalate"):
    return with_rules(
        rules, forbidden_expressions={"llm_judge": {"enabled": True, "on_error": on_error}}
    )


def test_forbidden_llm_judge_flags(rules):
    llm = FakeLLM(
        [
            say(
                '```json\n{"violations": [{"sentence": "걱정 마세요, 다 됩니다.", "reason": "승인 암시"}]}\n```'
            )
        ]
    )
    text = "걱정 마세요, 다 됩니다."
    r = forbidden.run(inp(text), text, _judge_rules(rules), CheckContext(judge_llm=llm))
    assert r.action is Action.BLOCK and r.findings[-1].code == "llm_judge"
    assert llm.calls[0][2] == []  # 도구 없이 호출


def test_forbidden_llm_judge_clean(rules):
    llm = FakeLLM([say('{"violations": []}')])
    r = forbidden.run(
        inp("안내드립니다."), "안내드립니다.", _judge_rules(rules), CheckContext(judge_llm=llm)
    )
    assert r.outcome is Outcome.PASS


@pytest.mark.parametrize(
    "responder",
    [
        lambda *_: (_ for _ in ()).throw(LLMError("down")),
        lambda *_: say("not json"),
        lambda *_: say('{"wrong": 1}'),
        lambda *_: stop(StopKind.REFUSAL),
    ],
)
def test_forbidden_llm_judge_errors(rules, responder):
    ctx = CheckContext(judge_llm=FakeLLM(responder))
    r = forbidden.run(inp("안내"), "안내", _judge_rules(rules), ctx)
    assert r.outcome is Outcome.ERROR and r.action is Action.ESCALATE
    r = forbidden.run(inp("안내"), "안내", _judge_rules(rules, "ignore"), ctx)
    assert r.outcome is Outcome.PASS and r.findings[0].code == "llm_judge_error"


def test_forbidden_llm_judge_without_llm(rules):
    r = forbidden.run(inp("안내"), "안내", _judge_rules(rules), CheckContext())
    assert r.outcome is Outcome.ERROR


# ---------------------------------------------------------------- 적합성


def test_suitability_no_trigger(rules, products):
    text = "중도상환수수료는 상환원금 × 1.20% × 잔여일수 ÷ 대출기간으로 계산합니다."
    assert suitability.run(inp(text, products=products), text, rules, CTX).outcome is Outcome.PASS


def test_suitability_calc_without_record_replaced(rules, products):
    text = "월 상환액은 177,697원입니다."
    r = suitability.run(
        inp(text, products=products, tools_called=["calculate_loan"]), text, rules, CTX
    )
    assert r.outcome is Outcome.FAIL and r.action is Action.REPLACE
    assert "연소득" in r.replacement
    assert r.findings[-1].code == "missing_suitability"


def test_suitability_recommendation_sentence(rules, products):
    text = "비상금 소액대출을 추천드립니다."
    r = suitability.run(inp(text, products=products), text, rules, CTX)
    assert r.action is Action.REPLACE


def test_suitability_question_passes(rules, products):
    text = "알맞은 대출을 추천드리기 전에 연소득과 기존 대출(부채) 규모를 알려 주시겠어요?"
    r = suitability.run(inp(text, products=products), text, rules, CTX)
    assert r.outcome is Outcome.PASS and r.findings[-1].code == "asking_suitability"


def test_suitability_recorded_passes(rules, products):
    text = "월 상환액은 177,697원입니다."
    r = suitability.run(
        inp(
            text,
            products=products,
            tools_called=["calculate_loan"],
            suitability=SuitabilityInfo(recorded=True),
        ),
        text,
        rules,
        CTX,
    )
    assert r.outcome is Outcome.PASS


def test_suitability_declined(rules, products):
    text = "월 상환액은 177,697원입니다."
    declined = SuitabilityInfo(recorded=True, declined=True)
    i = inp(text, products=products, tools_called=["calculate_loan"], suitability=declined)
    r = suitability.run(i, text, rules, CTX)
    assert r.action is Action.REPLACE and "거부" in r.findings[-1].message
    allow = with_rules(rules, suitability={"allow_when_declined": True})
    assert suitability.run(i, text, allow, CTX).outcome is Outcome.PASS


# ---------------------------------------------------------------- 필수 고지


def test_disclosures_appended_for_deposit(rules, products):
    text = "한빛 정기예금(가상)의 세후 이자는 279,180원입니다."
    r = disclosures.run(inp(text, products=products), text, rules, CTX)
    assert r.outcome is Outcome.FIXED and r.action is Action.AUTO_APPEND
    assert r.text_after.startswith(text)
    assert "※ 꼭 확인하세요" in r.text_after
    assert "예금자보호법" in r.text_after and "중도해지이율" in r.text_after


def test_disclosures_present_passes(rules, products):
    text = "정기예금은 예금자보호 대상이며, 중도해지 시 이자가 줄어듭니다."
    assert disclosures.run(inp(text, products=products), text, rules, CTX).outcome is Outcome.PASS


def test_disclosures_loan_partial(rules):
    text = "대출 가능 여부는 심사 후 결정되며 연체 시 불이익이 있습니다."
    r = disclosures.run(inp(text), text, rules, CTX)
    added = r.text_after[len(text) :]
    assert "신용평점" in added and "변동" in added
    assert "심사 결과에 따라" not in added  # 이미 있는 고지는 다시 붙이지 않음


def test_disclosures_type_hint_and_dedupe(rules):
    text = "세후 이자는 279,180원입니다."
    r = disclosures.run(inp(text, product_types=["DEPOSIT", "SAVINGS"]), text, rules, CTX)
    added = r.text_after[len(text) :]
    assert added.count("중도해지이율") == 1  # 같은 문구는 한 번만
    assert "이 예금은" in added and "이 적금은" in added


def test_disclosures_none_mentioned(rules):
    text = "안녕하세요, 무엇을 도와드릴까요?"
    r = disclosures.run(inp(text), text, rules, CTX)
    assert r.outcome is Outcome.PASS and r.findings == []


def test_disclosures_policy_loan_alias(rules):
    text = "상환 방법을 골라 주세요."
    r = disclosures.run(inp(text, product_types=["POLICY_LOAN"]), text, rules, CTX)
    assert "심사 결과에 따라" in r.text_after
