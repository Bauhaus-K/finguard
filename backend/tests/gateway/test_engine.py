import pytest

from app.gateway import engine
from app.gateway.checks import REGISTRY
from app.gateway.engine import run_gateway
from app.gateway.rules import LoadedRules
from app.gateway.types import Action, GatewayStatus, Outcome

from .helpers import P, inp, src


def loaded(rules):
    return LoadedRules(rules=rules, digest="d" * 64, files=["default.yaml"])


def by_check(decision):
    return {c.check: c for c in decision.checks}


def test_pass(rules):
    d = run_gateway(inp("무엇을 도와드릴까요?"), loaded(rules))
    assert d.status is GatewayStatus.PASS
    assert d.final_answer == "무엇을 도와드릴까요?"
    assert d.rules_version == rules.version and d.rules_digest == "d" * 64
    assert [c.check for c in d.checks] == rules.order


def test_auto_fixed_with_disclosure(rules, products):
    answer = "한빛 정기예금(가상) 기준 연 3.30%, 세후 이자는 279,180원입니다."
    d = run_gateway(
        inp(answer, products=products, sources=[src(279180), src("3.30", P)]), loaded(rules)
    )
    assert d.status is GatewayStatus.AUTO_FIXED
    assert d.final_answer.startswith(answer) and "예금자보호법" in d.final_answer


def test_wrong_number_is_blocked(rules, products):
    """수용 기준: 의도적으로 틀린 수치를 넣은 답변은 BLOCKED."""
    answer = "한빛 정기예금(가상) 기준 세후 이자는 297,180원입니다."  # 정답 279,180원
    d = run_gateway(inp(answer, products=products, sources=[src(279180)]), loaded(rules))
    assert d.status is GatewayStatus.BLOCKED
    assert d.retryable is True
    assert d.final_answer == rules.messages.blocked
    assert "297,180원" not in d.final_answer
    numeric = by_check(d)["numeric"]
    assert numeric.outcome is Outcome.FAIL and numeric.findings[0].excerpt == "297,180원"


def test_rate_not_in_sources_is_blocked(rules):
    d = run_gateway(inp("금리는 연 4.10%입니다.", sources=[src("3.30", P)]), loaded(rules))
    assert d.status is GatewayStatus.BLOCKED


def test_forbidden_block_is_not_retryable(rules):
    d = run_gateway(inp("확정 수익 상품입니다."), loaded(rules))
    assert d.status is GatewayStatus.BLOCKED and not d.retryable


def test_suitability_replacement(rules, products):
    d = run_gateway(
        inp("한빛 비상금 소액대출(가상)을 추천드립니다.", products=products), loaded(rules)
    )
    assert d.status is GatewayStatus.BLOCKED
    assert d.final_answer == rules.suitability.replacement_message
    assert not d.retryable


def test_scope_escalation_short_circuits(rules):
    d = run_gateway(inp("이 주식을 매수하시는 게 좋습니다. 290,000원 이득이에요."), loaded(rules))
    assert d.status is GatewayStatus.ESCALATED
    assert d.final_answer == rules.messages.escalation
    assert [c.check for c in d.checks] == ["pii", "scope"] + [
        c
        for c in ("numeric", "forbidden_expressions", "suitability", "disclosures")
        if c not in rules.order
    ]


def test_pii_masked_in_final(rules):
    d = run_gateway(
        inp("연락처 010-1234-5678 로 안내드릴게요.", user_message="제 번호 010-9999-8888"),
        loaded(rules),
    )
    assert d.status is GatewayStatus.AUTO_FIXED
    assert "010-1234-5678" not in d.final_answer
    assert d.masked_user_message == "제 번호 [전화번호]"


def test_rules_load_error_escalates():
    d = run_gateway(
        inp("안녕하세요"), LoadedRules(rules=None, digest="", files=[], error="ParserError: x")
    )
    assert d.status is GatewayStatus.ESCALATED
    assert d.checks[0].findings[0].code == "rules_load_error"


def test_check_exception_escalates(rules, monkeypatch):
    def boom(*_):
        raise RuntimeError("bug")

    monkeypatch.setitem(REGISTRY, "numeric", boom)
    d = run_gateway(inp("안녕하세요"), loaded(rules))
    assert d.status is GatewayStatus.ESCALATED
    numeric = by_check(d)["numeric"]
    assert numeric.outcome is Outcome.ERROR and numeric.action is Action.ESCALATE


def test_disabled_and_missing_checks_skipped(rules):
    data = rules.model_dump()
    data["numeric"]["enabled"] = False
    data["order"] = ["pii", "numeric", "disclosures"]
    custom = type(rules).model_validate(data)
    d = run_gateway(inp("이자는 999,999원입니다."), loaded(custom))
    assert d.status is GatewayStatus.PASS
    checks = by_check(d)
    assert checks["numeric"].outcome is Outcome.SKIPPED
    assert checks["forbidden_expressions"].outcome is Outcome.SKIPPED


def test_failed_helper(rules):
    d = run_gateway(inp("확정 수익, 이자 1원"), loaded(rules))
    assert {c.check for c in d.failed()} == {"numeric", "forbidden_expressions"}
    assert engine.FALLBACK_ESCALATION


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        ("죄송하지만 투자 종목 추천은 도와드릴 수 없습니다.", GatewayStatus.PASS),
        (
            "무조건 승인되는 대출 상품은 없습니다. 대출 가능 여부와 금리·한도는 신청 후 심사 결과로 결정됩니다. "
            "신용평점, 금리 변동, 연체 불이익도 확인해 주세요.",
            GatewayStatus.PASS,
        ),
    ],
)
def test_demo_like_answers(rules, products, answer, expected):
    assert run_gateway(inp(answer, products=products), loaded(rules)).status is expected
