"""감사 로그 조회·내보내기(CSV / JSON)."""

import csv
import io
from typing import Any

from app.db.models import AuditRecord

CSV_COLUMNS = [
    "seq",
    "created_at",
    "request_id",
    "status",
    "mode",
    "conversation_id",
    "user_message",
    "final_answer",
    "checks",
    "prev_hash",
    "record_hash",
]


def summarize(rec: AuditRecord) -> dict[str, Any]:
    p = rec.payload
    gateway = p.get("gateway") or {}
    return {
        "seq": rec.seq,
        "created_at": rec.created_at.isoformat() if rec.created_at else None,
        "request_id": rec.request_id,
        "status": rec.status,
        "mode": p.get("mode"),
        "conversation_id": p.get("conversation_id"),
        "user_message": (p.get("input") or {}).get("user_message", ""),
        "final_answer": (p.get("final") or {}).get("answer", ""),
        "checks": ";".join(f"{c['check']}:{c['outcome']}" for c in gateway.get("checks", [])),
        "prev_hash": rec.prev_hash,
        "record_hash": rec.record_hash,
    }


def full(rec: AuditRecord) -> dict[str, Any]:
    return {**summarize(rec), "tenant_id": rec.tenant_id, "payload": rec.payload}


def to_csv(records: list[AuditRecord]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=CSV_COLUMNS)
    writer.writeheader()
    for rec in records:
        writer.writerow(summarize(rec))
    # 엑셀에서 한글이 깨지지 않도록 BOM
    return "﻿" + buf.getvalue()
