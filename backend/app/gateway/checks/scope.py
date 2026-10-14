"""업무 범위 검사.

- 답변에 범위 밖 조언(투자 추천, 세무 대리, 법률 판단, 타사 비방)이 있으면 이관.
  단, 그 문장이 거절 표현을 포함하면 허용.
- 고객이 범위 밖 요청을 했는데 답변이 거절·이관 안내가 아니면 이관.
"""

import re
from typing import TYPE_CHECKING

from app.gateway.text import contains_any, search_any, sentence_at
from app.gateway.types import Action, CheckResult, Finding, GatewayInput, Outcome

if TYPE_CHECKING:
    from app.gateway.checks import CheckContext
    from app.gateway.rules import Rules

ID = "scope"


def run(inp: GatewayInput, text: str, rules: "Rules", ctx: "CheckContext") -> CheckResult:
    cfg = rules.scope
    answer_refuses = contains_any(text, cfg.refusal_markers)
    findings: list[Finding] = []
    violated = False

    for cat in cfg.categories:
        for pattern in cat.output_patterns:
            for m in re.finditer(pattern, text):
                sentence = sentence_at(text, m.start())
                if contains_any(sentence, cfg.refusal_markers):
                    continue
                violated = True
                findings.append(
                    Finding(
                        code=f"output_{cat.id}",
                        message=f"답변에 업무 범위 밖 내용({cat.label})이 있습니다",
                        excerpt=sentence.strip(),
                    )
                )
        if inp.user_message and (m := search_any(inp.user_message, cat.input_patterns)):
            if answer_refuses:
                findings.append(
                    Finding(
                        code=f"input_{cat.id}",
                        message=f"범위 밖 요청({cat.label})에 거절·이관으로 답했습니다",
                        excerpt=m.group(0),
                        severity="info",
                    )
                )
            else:
                violated = True
                findings.append(
                    Finding(
                        code=f"input_{cat.id}",
                        message=f"범위 밖 요청({cat.label})에 거절 없이 답했습니다",
                        excerpt=m.group(0),
                    )
                )

    if violated:
        return CheckResult(
            check=ID, outcome=Outcome.FAIL, action=Action.ESCALATE, findings=findings
        )
    return CheckResult(check=ID, outcome=Outcome.PASS, findings=findings)
