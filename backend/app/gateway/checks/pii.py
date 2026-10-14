"""개인정보 검사: 답변에 포함된 주민등록번호·카드·전화·계좌번호를 마스킹한다."""

from typing import TYPE_CHECKING

from app.gateway.types import Action, CheckResult, Finding, GatewayInput, Outcome
from app.privacy.pii import mask_pii

if TYPE_CHECKING:
    from app.gateway.checks import CheckContext
    from app.gateway.rules import Rules

ID = "pii"


def run(inp: GatewayInput, text: str, rules: "Rules", ctx: "CheckContext") -> CheckResult:
    types = rules.pii.types
    out = mask_pii(text, types)
    findings = [
        Finding(
            code=f"output_{t.value}", message=f"답변에서 {t.value} {n}건을 탐지해 마스킹했습니다"
        )
        for t, n in out.counts.items()
    ]
    findings += [
        Finding(
            code=f"input_{t.value}",
            message=f"고객 입력에서 {t.value} {n}건 탐지(마스킹 후 처리)",
            severity="info",
        )
        for t, n in mask_pii(inp.user_message, types).counts.items()
    ]
    if out.found:
        return CheckResult(
            check=ID,
            outcome=Outcome.FIXED,
            action=Action.MASK,
            findings=findings,
            text_after=out.text,
        )
    return CheckResult(check=ID, outcome=Outcome.PASS, findings=findings)
