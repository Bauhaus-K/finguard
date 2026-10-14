"""금지 표현 검사: 사전·정규식(규칙 기반) + 선택적 LLM 판별(보조).

- block 항목: 부정 문맥이 아니면 차단
- rewrite 항목: 해당 표현을 대체어로 바꾼 뒤 재검사. 여전히 위반이면 차단
- 같은 문장에 부정 표현(negation_markers)이 있으면 허용 ("무조건 승인되는 상품은 없습니다")
"""

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.gateway.judge import JudgeError, judge_forbidden
from app.gateway.text import contains_any, sentence_at
from app.gateway.types import Action, CheckResult, Finding, GatewayInput, Outcome

if TYPE_CHECKING:
    from app.gateway.checks import CheckContext
    from app.gateway.rules import ForbiddenTerm, Rules

ID = "forbidden_expressions"


@dataclass
class Hit:
    term: "ForbiddenTerm"
    match: re.Match[str]
    sentence: str
    negated: bool


def scan(text: str, rules: "Rules") -> list[Hit]:
    cfg = rules.forbidden_expressions
    hits = []
    for term in cfg.terms:
        for m in re.finditer(term.pattern, text):
            sentence = sentence_at(text, m.start())
            negated = term.negation_allowed and contains_any(sentence, cfg.negation_markers)
            hits.append(Hit(term, m, sentence.strip(), negated))
    return hits


def _tidy(text: str) -> str:
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r" +([.,!?])", r"\1", text)
    return re.sub(r"(^|\n) +", r"\1", text)


def _rewrite(text: str, rules: "Rules") -> str:
    cfg = rules.forbidden_expressions
    for term in cfg.terms:
        if term.action != "rewrite":
            continue

        def _sub(m: re.Match[str], term: "ForbiddenTerm" = term, src: str = text) -> str:
            sentence = sentence_at(src, m.start())
            if term.negation_allowed and contains_any(sentence, cfg.negation_markers):
                return m.group(0)
            return term.replacement

        text = re.sub(term.pattern, _sub, text)
    return _tidy(text)


def _finding(h: Hit, message: str, severity: str = "violation") -> Finding:
    return Finding(code=h.term.id, message=message, excerpt=h.sentence, severity=severity)


def run(inp: GatewayInput, text: str, rules: "Rules", ctx: "CheckContext") -> CheckResult:
    cfg = rules.forbidden_expressions
    hits = scan(text, rules)
    findings = [
        _finding(h, f"부정 문맥의 '{h.term.label}' 표현(허용)", "info") for h in hits if h.negated
    ]
    violations = [h for h in hits if not h.negated]

    blocking = [h for h in violations if h.term.action == "block"]
    if blocking:
        findings += [
            _finding(h, f"금지 표현({h.term.label}): {h.match.group(0)}") for h in blocking
        ]
        return CheckResult(check=ID, outcome=Outcome.FAIL, action=Action.BLOCK, findings=findings)

    new_text = text
    if violations:
        new_text = _rewrite(text, rules)
        findings += [
            _finding(h, f"금지 표현({h.term.label}) '{h.match.group(0)}' 을(를) 수정했습니다")
            for h in violations
        ]
        remaining = [h for h in scan(new_text, rules) if not h.negated]
        if remaining:
            findings += [
                _finding(h, f"수정 후에도 금지 표현이 남았습니다: {h.match.group(0)}")
                for h in remaining
            ]
            return CheckResult(
                check=ID, outcome=Outcome.FAIL, action=Action.BLOCK, findings=findings
            )

    if cfg.llm_judge.enabled:
        try:
            judged = judge_forbidden(ctx.judge_llm, new_text)
        except JudgeError as e:
            if cfg.llm_judge.on_error == "escalate":
                findings.append(Finding(code="llm_judge_error", message=f"LLM 판별 실패: {e}"))
                return CheckResult(
                    check=ID, outcome=Outcome.ERROR, action=Action.ESCALATE, findings=findings
                )
            findings.append(
                Finding(
                    code="llm_judge_error", message=f"LLM 판별 실패(무시): {e}", severity="info"
                )
            )
            judged = []
        if judged:
            findings += [
                Finding(code="llm_judge", message=f"LLM 판별: {v['reason']}", excerpt=v["sentence"])
                for v in judged
            ]
            return CheckResult(
                check=ID, outcome=Outcome.FAIL, action=Action.BLOCK, findings=findings
            )

    if new_text != text:
        return CheckResult(
            check=ID,
            outcome=Outcome.FIXED,
            action=Action.REWRITE,
            findings=findings,
            text_after=new_text,
        )
    return CheckResult(check=ID, outcome=Outcome.PASS, findings=findings)
