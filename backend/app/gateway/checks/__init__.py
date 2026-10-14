"""검사 플러그인. 각 모듈은 run(inp, text, rules, ctx) -> CheckResult 를 제공한다.

- inp: 원래 검사 입력(GatewayInput)
- text: 앞선 검사가 수정한 현재 답변
- rules: 병합된 규칙
- ctx: 보조 수단(LLM judge 등) 컨텍스트
"""

from collections.abc import Callable
from dataclasses import dataclass

from app.gateway.checks import disclosures, forbidden, numeric, pii, scope, suitability
from app.gateway.rules import Rules
from app.gateway.types import CheckResult, GatewayInput
from app.llm.base import LLMAdapter


@dataclass
class CheckContext:
    judge_llm: LLMAdapter | None = None


CheckFn = Callable[[GatewayInput, str, Rules, CheckContext], CheckResult]

REGISTRY: dict[str, CheckFn] = {
    "pii": pii.run,
    "scope": scope.run,
    "numeric": numeric.run,
    "forbidden_expressions": forbidden.run,
    "suitability": suitability.run,
    "disclosures": disclosures.run,
}
