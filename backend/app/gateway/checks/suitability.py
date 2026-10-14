"""적합성 검사: 대출을 권유(또는 개인별 상환액 안내)했는데 적합성 확인 기록이 없으면 차단하고
적합성 질문으로 대체한다. 답변 자체가 적합성 질문이면 통과."""

import re
from typing import TYPE_CHECKING

from app.gateway.text import sentences
from app.gateway.types import Action, CheckResult, Finding, GatewayInput, Outcome

if TYPE_CHECKING:
    from app.gateway.checks import CheckContext
    from app.gateway.rules import Rules

ID = "suitability"


def _loan_terms(inp: GatewayInput, rules: "Rules") -> list[str]:
    types = set(rules.suitability.loan_product_types)
    terms = ["대출"]
    for p in inp.products:
        if p.product_type in types:
            terms += [p.code, p.name, p.name.replace("(가상)", "").strip()]
    return terms


def _is_suitability_question(text: str, rules: "Rules") -> bool:
    groups = rules.suitability.question_marker_groups
    return bool(groups) and "?" in text and all(any(m in text for m in g) for g in groups)


def run(inp: GatewayInput, text: str, rules: "Rules", ctx: "CheckContext") -> CheckResult:
    cfg = rules.suitability
    triggers: list[Finding] = []
    for tool in cfg.trigger_tools:
        if tool in inp.tools_called:
            triggers.append(
                Finding(
                    code="trigger_tool",
                    message=f"{tool} 호출(개인별 대출 상환액 안내)",
                    severity="info",
                )
            )
    terms = _loan_terms(inp, rules)
    for s in sentences(text):
        if any(t in s for t in terms) and any(re.search(p, s) for p in cfg.recommendation_patterns):
            triggers.append(
                Finding(code="recommendation", message="대출 권유 문장", excerpt=s, severity="info")
            )

    if not triggers:
        return CheckResult(check=ID, outcome=Outcome.PASS)
    if _is_suitability_question(text, rules):
        triggers.append(
            Finding(
                code="asking_suitability", message="답변이 적합성 확인 질문입니다", severity="info"
            )
        )
        return CheckResult(check=ID, outcome=Outcome.PASS, findings=triggers)
    s = inp.suitability
    if s.recorded and (not s.declined or cfg.allow_when_declined):
        triggers.append(
            Finding(code="suitability_recorded", message="적합성 확인 기록 있음", severity="info")
        )
        return CheckResult(check=ID, outcome=Outcome.PASS, findings=triggers)

    reason = (
        "고객이 적합성 정보 제공을 거부했는데 대출을 권유했습니다"
        if s.recorded
        else "적합성 확인 기록 없이 대출을 권유했습니다"
    )
    triggers.append(Finding(code="missing_suitability", message=reason))
    return CheckResult(
        check=ID,
        outcome=Outcome.FAIL,
        action=Action.REPLACE,
        findings=triggers,
        replacement=cfg.replacement_message,
    )
