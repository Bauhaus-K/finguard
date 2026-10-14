"""감사 로그 조회·검증·내보내기 API (테넌트 범위)."""

import json
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy import func, select

from app.api.deps import AdminTenant, DbSession
from app.audit.export import full, summarize, to_csv
from app.audit.hashchain import verify_chain
from app.db.models import AuditRecord

router = APIRouter(prefix="/v1/audit", tags=["audit"])


@router.get("/records")
def list_records(
    tenant: AdminTenant,
    session: DbSession,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    stmt = select(AuditRecord).where(AuditRecord.tenant_id == tenant.id)
    count = select(func.count()).select_from(AuditRecord).where(AuditRecord.tenant_id == tenant.id)
    if status_filter:
        stmt = stmt.where(AuditRecord.status == status_filter)
        count = count.where(AuditRecord.status == status_filter)
    rows = session.scalars(stmt.order_by(AuditRecord.seq.desc()).limit(limit).offset(offset))
    return {"total": session.scalar(count), "items": [summarize(r) for r in rows]}


@router.get("/records/{request_id}")
def get_record(request_id: str, tenant: AdminTenant, session: DbSession) -> dict[str, Any]:
    rec = session.scalar(
        select(AuditRecord).where(
            AuditRecord.tenant_id == tenant.id, AuditRecord.request_id == request_id
        )
    )
    if rec is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "감사 기록이 없습니다")
    return full(rec)


@router.get("/verify")
def verify(tenant: AdminTenant, session: DbSession) -> dict[str, Any]:
    r = verify_chain(session, tenant.id)
    return {
        "ok": r.ok,
        "checked": r.checked,
        "broken_seq": r.broken_seq,
        "reason": r.reason,
        "last_hash": r.last_hash,
    }


@router.get("/export")
def export(
    tenant: AdminTenant,
    session: DbSession,
    fmt: Annotated[Literal["csv", "json"], Query(alias="format")] = "json",
) -> Response:
    rows = list(
        session.scalars(
            select(AuditRecord).where(AuditRecord.tenant_id == tenant.id).order_by(AuditRecord.seq)
        )
    )
    if fmt == "csv":
        return Response(
            to_csv(rows),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="audit_{tenant.id}.csv"'},
        )
    body = json.dumps([full(r) for r in rows], ensure_ascii=False, indent=2)
    return Response(
        body,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="audit_{tenant.id}.json"'},
    )
