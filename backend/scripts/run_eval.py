"""평가 실행: `make eval` (실제 LLM) / `make eval-offline` (스크립트 LLM, 파이프라인 점검용).

- 격리된 SQLite DB(eval/.work/eval.db)를 새로 만들어 실행한다(개발 DB·감사 로그를 건드리지 않음).
- 리포트: eval/reports/{timestamp}.md, 원자료: eval/reports/{timestamp}.json
- --strict: 수용 기준 미달이면 종료 코드 1
"""

import argparse
import json
import os
import sys
import time
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.audit.hashchain import verify_chain
from app.catalog import load_catalog
from app.chat_service import product_refs
from app.config import REPO_ROOT, Settings, get_settings  # noqa: F401
from app.db.models import Base
from app.db.seed import seed
from app.db.session import make_engine
from app.eval.datasets import load_golden, load_redteam
from app.eval.grader import grade_attack, grade_golden, grade_redteam
from app.eval.report import TARGETS, EvalRun, render, results_json, summarize
from app.eval.runner import run_attack, run_conversation
from app.services import build_services

EVAL_DIR = REPO_ROOT / "eval"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", help="LLM_PROVIDER 덮어쓰기 (anthropic | scripted)")
    ap.add_argument("--limit", type=int, help="데이터셋별 앞에서 N 문항만")
    ap.add_argument("--only", choices=["golden", "redteam", "attack"], action="append")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()

    settings = get_settings()
    if args.provider:
        settings = settings.model_copy(update={"llm_provider": args.provider})
    scripted = settings.llm_provider == "scripted"
    if settings.llm_provider == "anthropic" and not (
        settings.anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY")
    ):
        print(
            "ANTHROPIC_API_KEY 가 없습니다. .env 에 키를 넣거나, 파이프라인만 점검하려면 `make eval-offline` 을 쓰세요.",
            file=sys.stderr,
        )
        return 2
    only = set(args.only or ["golden", "redteam", "attack"])

    work = EVAL_DIR / ".work"
    work.mkdir(parents=True, exist_ok=True)
    db = work / "eval.db"
    db.unlink(missing_ok=True)
    engine = make_engine(f"sqlite:///{db}")
    Base.metadata.create_all(engine)

    golden = load_golden(EVAL_DIR / "golden.jsonl")[: args.limit]
    redteam = load_redteam(EVAL_DIR / "redteam.jsonl")[: args.limit]
    services = build_services(settings)
    tenant = settings.demo_tenant_id
    loaded = services.rules.get(tenant)
    if loaded.rules is None:
        print(f"규칙 로딩 실패: {loaded.error}", file=sys.stderr)
        return 2

    started = datetime.now(UTC)
    t0 = time.perf_counter()
    with Session(engine) as session:
        seed(session, load_catalog(settings.data_dir / "products" / "catalog.yaml"), settings)
        products = product_refs(session, tenant)
        by_code = {p.code: p for p in products}

        g_results = []
        if "golden" in only:
            for i, case in enumerate(golden, 1):
                turns = run_conversation(services, session, tenant, case.turns)
                grade = grade_golden(case, turns, by_code)
                g_results.append((grade, turns))
                print(
                    f"[golden {i}/{len(golden)}] {case.id} {'PASS' if grade.passed else 'FAIL'} {turns[-1].status}"
                )
        r_results = []
        if "redteam" in only:
            for i, case in enumerate(redteam, 1):
                turns = run_conversation(services, session, tenant, case.turns)
                grade = grade_redteam(case, turns, loaded.rules)
                r_results.append((grade, turns))
                print(
                    f"[redteam {i}/{len(redteam)}] {case.id} {'DEFENDED' if grade.defended else 'FAIL'} {turns[-1].status}"
                )
        a_results = []
        if "attack" in only:
            for case in redteam:
                decision = run_attack(
                    services, tenant, case.turns[-1], case.attack_answer, products
                )
                a_results.append(grade_attack(case, decision, loaded.rules))
        chain = verify_chain(session, tenant)

    run = EvalRun(
        started_at=started.strftime("%Y-%m-%d %H:%M UTC"),
        provider=settings.llm_provider,
        model=settings.llm_model if not scripted else "scripted",
        scripted=scripted,
        rules_version=loaded.rules.version,
        rules_digest=loaded.digest,
        golden=g_results,
        redteam=r_results,
        attacks=a_results,
        chain_ok=chain.ok,
        chain_checked=chain.checked,
    )
    stamp = started.strftime("%Y%m%dT%H%M%SZ") + ("_offline" if scripted else "")
    out_dir = EVAL_DIR / "reports"
    out_dir.mkdir(exist_ok=True)
    (out_dir / f"{stamp}.md").write_text(render(run), encoding="utf-8")
    (out_dir / f"{stamp}.json").write_text(
        json.dumps(results_json(run), ensure_ascii=False, indent=1, default=str), encoding="utf-8"
    )
    s = summarize(run)
    print(f"\n완료 ({time.perf_counter() - t0:.1f}s) → eval/reports/{stamp}.md")
    print(
        f"수치 불일치 {s['final_unsourced']}건 | 레드팀 방어 {s['redteam_defended']}/{s['redteam_total']} | "
        f"과잉 차단 {s['over_blocked']}/{s['golden_total']} | 게이트웨이 단독 {s['attack_passed']}/{s['attack_total']}"
    )
    met = (
        s["final_unsourced"] <= TARGETS["numeric_mismatch"]
        and (
            not s["redteam_total"]
            or s["redteam_defended"] / s["redteam_total"] >= TARGETS["redteam_defense"]
        )
        and (
            not s["golden_total"] or s["over_blocked"] / s["golden_total"] <= TARGETS["over_block"]
        )
    )
    return 1 if args.strict and not met else 0


if __name__ == "__main__":
    sys.exit(main())
