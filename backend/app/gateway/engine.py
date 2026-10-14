"""게이트웨이 엔진: 규칙 순서대로 검사 플러그인을 실행하고 최종 판정을 내린다.

판정
- 어떤 검사든 ESCALATE(또는 검사 오류, 규칙 로딩 실패) → ESCALATED (이관 안내문)
- 그 외 FAIL 이 있으면 → BLOCKED
    · 적합성 REPLACE 가 있으면 지정 문구로 대체
    · 아니면 차단 안내문. 실패가 모두 REGENERATE(수치 검증)면 retryable=True
- FIXED 만 있으면 → AUTO_FIXED (수정된 답변)
- 모두 통과 → PASS
"""

import logging

from app.gateway.checks import REGISTRY, CheckContext
from app.gateway.rules import CHECK_IDS, LoadedRules
from app.gateway.types import (
    Action,
    CheckResult,
    Finding,
    GatewayDecision,
    GatewayInput,
    GatewayStatus,
    Outcome,
)
from app.privacy.pii import mask_pii

log = logging.getLogger(__name__)

FALLBACK_ESCALATION = "문의하신 내용은 상담원이 도와드리겠습니다. 잠시만 기다려 주세요."


def run_gateway(
    inp: GatewayInput, loaded: LoadedRules, ctx: CheckContext | None = None
) -> GatewayDecision:
    ctx = ctx or CheckContext()
    masked_user = mask_pii(inp.user_message).text
    rules = loaded.rules
    if rules is None:
        return GatewayDecision(
            status=GatewayStatus.ESCALATED,
            final_answer=FALLBACK_ESCALATION,
            checks=[
                CheckResult(
                    check="rules",
                    outcome=Outcome.ERROR,
                    action=Action.ESCALATE,
                    findings=[
                        Finding(code="rules_load_error", message=loaded.error or "규칙 없음")
                    ],
                )
            ],
            masked_user_message=masked_user,
        )

    text = inp.answer
    results: list[CheckResult] = []
    for check_id in rules.order:
        if not rules.check_enabled(check_id):
            results.append(CheckResult(check=check_id, outcome=Outcome.SKIPPED))
            continue
        try:
            result = REGISTRY[check_id](inp, text, rules, ctx)
        except Exception as e:  # 검사 오류 → fail-safe 이관
            log.exception("gateway check %s failed", check_id)
            result = CheckResult(
                check=check_id,
                outcome=Outcome.ERROR,
                action=Action.ESCALATE,
                findings=[Finding(code="check_error", message=f"검사 오류: {type(e).__name__}")],
            )
        results.append(result)
        if result.text_after is not None:
            text = result.text_after
        if result.action is Action.ESCALATE:
            break
    for check_id in CHECK_IDS:
        if check_id not in rules.order:
            results.append(CheckResult(check=check_id, outcome=Outcome.SKIPPED))

    common = dict(
        checks=results,
        rules_version=rules.version,
        rules_digest=loaded.digest,
        masked_user_message=masked_user,
    )
    if any(r.action is Action.ESCALATE for r in results):
        return GatewayDecision(
            status=GatewayStatus.ESCALATED, final_answer=rules.messages.escalation, **common
        )
    failed = [r for r in results if r.outcome is Outcome.FAIL]
    if failed:
        replace = next((r for r in failed if r.action is Action.REPLACE), None)
        return GatewayDecision(
            status=GatewayStatus.BLOCKED,
            final_answer=replace.replacement if replace else rules.messages.blocked,
            retryable=replace is None and all(r.action is Action.REGENERATE for r in failed),
            **common,
        )
    if any(r.outcome is Outcome.FIXED for r in results):
        return GatewayDecision(status=GatewayStatus.AUTO_FIXED, final_answer=text, **common)
    return GatewayDecision(status=GatewayStatus.PASS, final_answer=text, **common)
