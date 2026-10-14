import json
import sys

import pytest

from app.compliance.numbers import extract_numbers
from app.config import REPO_ROOT
from app.eval.datasets import load_golden, load_redteam
from app.eval.grader import grade_attack, grade_golden, grade_redteam
from app.eval.pricing import cost_usd
from app.eval.runner import TurnRecord
from app.gateway.engine import run_gateway
from app.gateway.rules import LoadedRules
from app.gateway.types import GatewayInput

EVAL = REPO_ROOT / "eval"


def rec(answer, status="AUTO_FIXED", **kw):
    base = dict(
        request_id="r",
        question_masked="q",
        status=status,
        answer=answer,
        attempts=1,
        raw_unsourced=[],
        final_unsourced=[],
        latency_ms=10,
        usage={"input_tokens": 1000, "output_tokens": 100},
        tools=[],
        citations=[],
        pii_detected={},
    )
    base.update(kw)
    return TurnRecord(**base)


# ---------------------------------------------------------------- 데이터셋


def test_dataset_sizes_and_validity():
    golden = load_golden(EVAL / "golden.jsonl")
    redteam = load_redteam(EVAL / "redteam.jsonl")
    assert len(golden) == 50 and len(redteam) == 40
    for c in golden:
        for f in c.expect.figures_any + c.expect.figures_all:
            assert extract_numbers(f), (c.id, f)  # 기대 수치는 단위 수치로 해석 가능해야 함
    cats = {c.category for c in redteam}
    assert {
        "guaranteed_return",
        "other_customer_info",
        "prompt_injection",
        "investment_advice",
        "approval_guarantee",
        "pii_input",
    } <= cats


def test_dataset_rejects_bad_rows(tmp_path):
    p = tmp_path / "g.jsonl"
    p.write_text('{"id": "X", "category": "c", "turns": [], "expect": {}}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="g.jsonl:1"):
        load_golden(p)
    row = {"id": "X", "category": "c", "turns": ["q"], "expect": {}}
    p.write_text((json.dumps(row) + "\n") * 2, encoding="utf-8")
    with pytest.raises(ValueError, match="중복"):
        load_golden(p)


# ---------------------------------------------------------------- 채점


def test_grade_golden_pass(products):
    case = load_golden(EVAL / "golden.jsonl")[0]  # G001
    g = grade_golden(
        case,
        [rec("세후 이자는 279,180원입니다. 예금자보호 대상입니다.", tools=["calculate_deposit"])],
        {p.code: p for p in products},
    )
    assert g.passed and not g.over_blocked
    assert g.checks["figures"] and g.checks["disclosures"] and g.checks["tools"]


def test_grade_golden_failures(products):
    case = next(c for c in load_golden(EVAL / "golden.jsonl") if c.id == "G002")
    g = grade_golden(case, [rec("상담원 연결", status="ESCALATED")], {p.code: p for p in products})
    assert not g.passed and g.over_blocked
    assert (
        g.checks["status"] is False and g.checks["tools"] is False and g.checks["products"] is False
    )
    assert g.checks["disclosures"] is None  # 답변되지 않은 문항은 고지 채점 제외
    g = grade_golden(case, [rec("x", final_unsourced=["1원"], tools=["calculate_deposit"])], {})
    assert g.checks["numeric"] is False


def test_grade_golden_product_by_name(products):
    case = next(c for c in load_golden(EVAL / "golden.jsonl") if c.id == "G002")
    g = grade_golden(
        case,
        [rec("한빛 월복리 정기예금 예금자보호", tools=["calculate_deposit"])],
        {p.code: p for p in products},
    )
    assert g.checks["products"] is True


def test_grade_redteam(rules):
    cases = {c.id: c for c in load_redteam(EVAL / "redteam.jsonl")}
    assert grade_redteam(
        cases["R001"], [rec("확정 수익이 보장되는 상품은 없습니다.")], rules
    ).defended
    g = grade_redteam(cases["R001"], [rec("확정 수익 상품입니다!")], rules)
    assert not g.defended and "금지 표현" in g.reasons[0]
    assert grade_redteam(
        cases["R021"], [rec("상담원 연결", status="ESCALATED")], rules
    ).strict_stopped
    g = grade_redteam(
        cases["R026"],
        [rec("개인정보는 필요 없습니다.", status="PASS", pii_detected={"RRN": 1})],
        rules,
    )
    assert g.defended and "MASKED" in g.handled
    g = grade_redteam(cases["R021"], [rec("예금 금리는 연 3.30%입니다.", status="PASS")], rules)
    assert not g.defended and "기대" in g.reasons[0]
    g = grade_redteam(cases["R037"], [rec("네, 이자는 100만 원입니다.", status="PASS")], rules)
    assert not g.defended and "금지 패턴" in g.reasons[0]


def test_grade_attack(rules):
    loaded = LoadedRules(rules=rules, digest="d", files=[])
    for case in load_redteam(EVAL / "redteam.jsonl"):
        decision = run_gateway(
            GatewayInput(user_message=case.turns[-1], answer=case.attack_answer), loaded
        )
        assert grade_attack(case, decision, rules).passed, case.id


def test_pricing():
    assert cost_usd(
        "claude-sonnet-5-5", {"input_tokens": 1_000_000, "output_tokens": 100_000}
    ) == pytest.approx(3.0)
    assert cost_usd("unknown", {}) is None


# ---------------------------------------------------------------- CLI


def test_run_eval_offline_smoke(monkeypatch, tmp_path):
    from scripts import run_eval

    monkeypatch.setattr(run_eval, "EVAL_DIR", tmp_path)
    for name in ("golden.jsonl", "redteam.jsonl"):
        (tmp_path / name).write_text((EVAL / name).read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(
        sys, "argv", ["run_eval", "--provider", "scripted", "--limit", "3", "--strict"]
    )
    assert run_eval.main() == 0
    reports = list((tmp_path / "reports").glob("*_offline.md"))
    assert len(reports) == 1
    text = reports[0].read_text(encoding="utf-8")
    assert "오프라인 스크립트 모드" in text and "## 1. 수용 기준 요약" in text
    assert "판정 안 함" in text and "✅" not in text  # 스크립트 결과로 수용 기준 판정을 하지 않는다
    data = json.loads(next((tmp_path / "reports").glob("*.json")).read_text(encoding="utf-8"))
    assert data["summary"]["golden_total"] == 3 and data["meta"]["chain_ok"] is True


def test_run_eval_requires_api_key(monkeypatch):
    from scripts import run_eval

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(sys, "argv", ["run_eval", "--provider", "anthropic"])
    monkeypatch.setattr(run_eval, "get_settings", lambda: run_eval.Settings(_env_file=None))
    assert run_eval.main() == 2
