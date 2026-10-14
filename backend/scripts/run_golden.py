"""골든셋 수동 실행 (Phase 2 수용 기준 확인용, Phase 3 부터 게이트웨이 포함).

실제 LLM 으로 골든셋 질문을 돌리고(에이전트 → 게이트웨이 → 감사 로그), LLM 원본 답변에 나온 모든 단위 수치가
같은 요청 안의 도구 결과(또는 고객 입력)에서 나왔는지 출처를 표시한다. 게이트웨이 판정과 최종 답변도 함께 적는다.
결과는 eval/reports/phase2_manual_{timestamp}.md 에 저장되고, 전체 trace 는 감사 로그(DB)에 남는다.

사용: uv run python -m scripts.run_golden [--limit 10] [--ids G001,G005]
필요: ANTHROPIC_API_KEY(.env), make seed 완료
종료 코드: 출처 없는 수치가 하나라도 있으면 1
"""

import argparse
import json
import sys
from collections import defaultdict
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.agent.loop import AgentResult
from app.agent.state import ConversationStore
from app.chat_service import handle_chat
from app.compliance.numbers import extract_numbers
from app.config import REPO_ROOT, get_settings
from app.db.session import get_engine
from app.services import build_services


def _origins(result: AgentResult) -> dict[tuple, list[str]]:
    index: dict[tuple, list[str]] = defaultdict(list)
    for s in result.figures:
        key = (s.figure.unit, s.figure.value.normalize())
        if s.origin not in index[key]:
            index[key].append(s.origin)
    return index


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--ids", type=str, default="")
    args = parser.parse_args()

    settings = get_settings()
    services = build_services(settings)
    store = ConversationStore()
    cases = [
        json.loads(line)
        for line in (REPO_ROOT / "eval" / "golden.jsonl").read_text().splitlines()
        if line
    ]
    if args.ids:
        wanted = set(args.ids.split(","))
        cases = [c for c in cases if c["id"] in wanted]
    cases = cases[: args.limit]

    lines = [f"# Phase 2 골든셋 수동 실행 — {datetime.now(UTC):%Y-%m-%d %H:%M UTC}", ""]
    lines.append(f"- 모델: `{settings.llm_model}` (effort={settings.llm_effort})")
    lines.append(
        "- 판정: 답변의 모든 단위 수치(원·%·개월·년·일)가 같은 요청의 도구 결과 또는 고객 입력에 있으면 OK"
    )
    lines.append("")
    total_numbers = total_unsourced = 0

    with Session(get_engine()) as session:
        for case in cases:
            conv = store.get_or_create(settings.demo_tenant_id, None)
            lines.append(f"## {case['id']} ({case['category']})")
            for turn_no, message in enumerate(case["turns"], 1):
                outcome = handle_chat(
                    services=services,
                    session=session,
                    tenant_id=settings.demo_tenant_id,
                    conversation=conv,
                    message=message,
                )
                # 재생성 전 첫 원본 답변을 기준으로 수치 출처를 본다
                result = outcome.attempts[0].agent

                origins = _origins(result)
                numbers = extract_numbers(result.answer)
                unsourced = [n for n in numbers if n.key not in origins]
                total_numbers += len(numbers)
                total_unsourced += len(unsourced)

                lines += [
                    f"### 턴 {turn_no}",
                    f"- 질문: {result.masked_input}",
                    f"- request_id: `{result.request_id}` / 상태: **{result.status}**"
                    + (f" ({result.escalation})" if result.escalation else ""),
                    f"- 호출 도구: {', '.join(result.tool_names) or '없음'}",
                    f"- 게이트웨이 최종 판정: **{outcome.status}** (시도 {len(outcome.attempts)}회)",
                    f"- LLM 호출 {result.llm_calls}회, 토큰 in={result.usage.input_tokens} "
                    f"out={result.usage.output_tokens} cache_read={result.usage.cache_read_input_tokens}",
                    "",
                    "**LLM 원본 답변 (첫 시도)**",
                    "",
                    *[f"> {line}" for line in result.answer.splitlines()],
                    "",
                    "| 답변 속 수치 | 정규화 | 출처 |",
                    "|---|---|---|",
                ]
                for n in numbers:
                    src = ", ".join(origins.get(n.key, [])) or "❌ **출처 없음**"
                    lines.append(f"| {n.text} | {n.unit} {n.value} | {src} |")
                if not numbers:
                    lines.append("| (수치 없음) | | |")
                lines += [
                    "",
                    "**고객에게 전달된 최종 답변**",
                    "",
                    *[f"> {x}" for x in outcome.answer.splitlines()],
                    "",
                ]
                print(
                    f"{case['id']} turn {turn_no}: {outcome.status} numbers={len(numbers)} unsourced={len(unsourced)}"
                )

    lines.insert(4, f"- 결과: 수치 {total_numbers}개 중 출처 없음 **{total_unsourced}개**")
    out = REPO_ROOT / "eval" / "reports" / f"phase2_manual_{datetime.now(UTC):%Y%m%dT%H%M%SZ}.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"리포트: {out.relative_to(REPO_ROOT)}")
    return 1 if total_unsourced else 0


if __name__ == "__main__":
    sys.exit(main())
