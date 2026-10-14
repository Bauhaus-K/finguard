"""관리 화면용 조회 API: 지표, 가이드라인 매핑, 시스템 정보."""

import statistics
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo

import yaml
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select

from app.api.deps import AdminTenant, CurrentTenant, DbSession
from app.db.models import AuditRecord
from app.services import Services, get_services

router = APIRouter(prefix="/v1", tags=["admin"])

KST = ZoneInfo("Asia/Seoul")
STATUSES = ["PASS", "AUTO_FIXED", "BLOCKED", "ESCALATED"]
MAX_RECORDS = 20_000  # MVP: 최근 레코드만 메모리에서 집계


def _recorded_at(rec: AuditRecord) -> datetime:
    raw = rec.payload.get("recorded_at")
    if raw:
        return datetime.fromisoformat(raw)
    return rec.created_at.replace(tzinfo=UTC) if rec.created_at.tzinfo is None else rec.created_at


@router.get("/metrics")
def metrics(
    tenant: AdminTenant,
    session: DbSession,
    days: Annotated[int, Query(ge=1, le=90)] = 7,
    mode: Annotated[Literal["all", "standard", "gateway_only", "debug"], Query()] = "all",
) -> dict[str, Any]:
    today = datetime.now(KST).date()
    start_day = today - timedelta(days=days - 1)
    since = datetime.combine(start_day, datetime.min.time(), KST)
    rows = session.scalars(
        select(AuditRecord)
        .where(AuditRecord.tenant_id == tenant.id)
        .order_by(AuditRecord.seq.desc())
        .limit(MAX_RECORDS)
    )
    daily: dict[str, Counter[str]] = {
        (start_day + timedelta(days=i)).isoformat(): Counter() for i in range(days)
    }
    by_status: Counter[str] = Counter()
    checks: dict[str, Counter[str]] = defaultdict(Counter)
    escalations: Counter[str] = Counter()
    latencies: list[int] = []
    tokens_in = tokens_out = chat_requests = regenerated = 0

    for rec in rows:
        at = _recorded_at(rec)
        if at < since:
            break
        p = rec.payload
        if mode != "all" and p.get("mode") != mode:
            continue
        by_status[rec.status] += 1
        daily[at.astimezone(KST).date().isoformat()][rec.status] += 1
        for c in (p.get("gateway") or {}).get("checks", []):
            checks[c["check"]][c["outcome"]] += 1
        esc = (p.get("final") or {}).get("escalation")
        if rec.status == "ESCALATED":
            escalations[(esc or {}).get("category", "GATEWAY")] += 1
        if (lat := p.get("latency_ms")) is not None:
            latencies.append(int(lat))
        if usage := p.get("usage"):
            chat_requests += 1
            tokens_in += usage.get("input_tokens", 0)
            tokens_out += usage.get("output_tokens", 0)
        if len(p.get("attempts") or []) > 1:
            regenerated += 1

    total = sum(by_status.values())
    lat_sorted = sorted(latencies)
    return {
        "period": {
            "from": start_day.isoformat(),
            "to": today.isoformat(),
            "days": days,
            "timezone": "Asia/Seoul",
        },
        "mode": mode,
        "total": total,
        "by_status": {s: by_status.get(s, 0) for s in STATUSES},
        "daily": [{"date": d, **{s: c.get(s, 0) for s in STATUSES}} for d, c in daily.items()],
        "checks": [
            {
                "check": name,
                **{o: c.get(o, 0) for o in ("PASS", "FIXED", "FAIL", "ERROR", "SKIPPED")},
            }
            for name, c in sorted(checks.items())
        ],
        "escalation_categories": dict(escalations.most_common()),
        "regenerated": regenerated,
        "latency_ms": {
            "avg": round(statistics.fmean(latencies)) if latencies else None,
            "p95": lat_sorted[int(0.95 * (len(lat_sorted) - 1))] if lat_sorted else None,
        },
        "tokens": {
            "requests": chat_requests,
            "input_total": tokens_in,
            "output_total": tokens_out,
            "avg_per_request": round((tokens_in + tokens_out) / chat_requests)
            if chat_requests
            else None,
        },
    }


@router.get("/guidelines")
def guidelines(
    tenant: AdminTenant, services: Annotated[Services, Depends(get_services)]
) -> dict[str, Any]:
    path = services.settings.data_dir / "guideline_mapping.yaml"
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as e:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, f"매핑 파일 오류: {type(e).__name__}"
        ) from e
    features = {f["id"]: f for f in data.get("system_features", [])}
    principles = []
    for p in data.get("principles", []):
        principles.append(
            {
                **p,
                "needs_review": any(
                    str(p.get(k, "")).startswith("TODO") for k in ("name", "summary")
                ),
                "unknown_features": [f for f in p.get("features", []) if f not in features],
            }
        )
    return {
        "source": data.get("source", {}),
        "principles": principles,
        "system_features": list(features.values()),
        "file": "data/guideline_mapping.yaml",
    }


@router.get("/meta")
def meta(
    tenant: CurrentTenant, services: Annotated[Services, Depends(get_services)]
) -> dict[str, Any]:
    s = services.settings
    return {
        "tenant_id": tenant.id,
        "tenant_name": tenant.name,
        "llm_provider": s.llm_provider,
        "llm_model": s.llm_model if s.llm_provider == "anthropic" else None,
        "scripted": s.llm_provider == "scripted",
        "debug_mode_allowed": s.allow_debug_mode,
    }
