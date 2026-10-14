"""필수 고지 검사: 답변이 다루는 상품 유형별 필수 문구가 없으면 자동으로 첨부한다."""

import re
from typing import TYPE_CHECKING

from app.gateway.types import Action, CheckResult, Finding, GatewayInput, Outcome

if TYPE_CHECKING:
    from app.gateway.checks import CheckContext
    from app.gateway.rules import Rules

ID = "disclosures"

# 카탈로그 상품 유형 → 고지 규칙 유형
TYPE_ALIASES = {"CREDIT_LOAN": "LOAN", "POLICY_LOAN": "LOAN"}


def _norm(t: str) -> str:
    return TYPE_ALIASES.get(t, t)


def mentioned_types(inp: GatewayInput, text: str, rules: "Rules") -> list[str]:
    found: list[str] = [_norm(t) for t in inp.product_types]
    for p in inp.products:
        short = p.name.replace("(가상)", "").strip()
        if p.code in text or p.name in text or (short and short in text):
            found.append(_norm(p.product_type))
    for t, keywords in rules.disclosures.product_type_keywords.items():
        if any(k in text for k in keywords):
            found.append(t)
    order = list(rules.disclosures.required)
    return sorted({t for t in found if t in rules.disclosures.required}, key=order.index)


def run(inp: GatewayInput, text: str, rules: "Rules", ctx: "CheckContext") -> CheckResult:
    cfg = rules.disclosures
    types = mentioned_types(inp, text, rules)
    missing: list[str] = []
    findings: list[Finding] = []
    for t in types:
        for d in cfg.required[t]:
            if any(re.search(p, text) for p in d.present_patterns):
                findings.append(
                    Finding(code=f"{t}.{d.id}", message="필수 고지 포함", severity="info")
                )
                continue
            if d.text not in missing:
                missing.append(d.text)
            findings.append(Finding(code=f"{t}.{d.id}", message="필수 고지 누락 → 자동 첨부"))
    if not missing:
        return CheckResult(check=ID, outcome=Outcome.PASS, findings=findings)
    appended = text.rstrip() + "\n\n" + cfg.header + "\n" + "\n".join(f"- {m}" for m in missing)
    return CheckResult(
        check=ID,
        outcome=Outcome.FIXED,
        action=Action.AUTO_APPEND,
        findings=findings,
        text_after=appended,
    )
