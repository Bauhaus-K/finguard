"""수치 검증: 답변의 모든 단위 수치가 같은 요청 안의 출처(도구 결과·고객 입력·제공 문서)에 있어야 한다."""

from decimal import Decimal
from typing import TYPE_CHECKING

from app.calc.common import Figure
from app.compliance.numbers import extract_numbers, find_hangul_numerals
from app.compliance.provenance import figure_keys
from app.gateway.types import Action, CheckResult, Finding, GatewayInput, Outcome

if TYPE_CHECKING:
    from app.gateway.checks import CheckContext
    from app.gateway.rules import Rules

ID = "numeric"


def allowed_keys(inp: GatewayInput, rules: "Rules") -> set:
    cfg = rules.numeric
    keys = figure_keys(inp.sources)
    for t in inp.context_texts:
        keys |= {n.key for n in extract_numbers(t)}
    user_units = set(cfg.accept_user_number_units)
    keys |= {n.key for n in extract_numbers(inp.user_message) if n.unit in user_units}
    keys |= figure_keys(
        Figure(name="always_allowed", value=Decimal(str(a.value)), unit=a.unit)
        for a in cfg.always_allowed
    )
    return keys


def run(inp: GatewayInput, text: str, rules: "Rules", ctx: "CheckContext") -> CheckResult:
    units = set(rules.numeric.units)
    numbers = [n for n in extract_numbers(text) if n.unit in units]
    allowed = allowed_keys(inp, rules)
    unsourced = [n for n in numbers if n.key not in allowed]
    hangul = find_hangul_numerals(text)
    if unsourced or hangul:
        return CheckResult(
            check=ID,
            outcome=Outcome.FAIL,
            action=Action.REGENERATE,
            findings=[
                Finding(
                    code="unsourced_number",
                    message=f"출처 없는 수치: {n.text} ({n.unit} {n.value})",
                    excerpt=n.text,
                )
                for n in unsourced
            ]
            + [
                Finding(
                    code="unverifiable_number",
                    message=f"한글 수사 표기라 검증할 수 없는 수치: {h} (숫자로 표기해야 함)",
                    excerpt=h,
                )
                for h in hangul
            ],
        )
    return CheckResult(
        check=ID,
        outcome=Outcome.PASS,
        findings=[
            Finding(
                code="verified",
                message=f"수치 {len(numbers)}개 모두 출처 확인",
                severity="info",
            )
        ],
    )
