"""감사 로그: append-only + 해시 체인.

각 레코드의 record_hash = SHA-256(정규화 JSON{tenant_id, seq, request_id, status, prev_hash, payload}).
prev_hash 는 같은 테넌트의 직전 레코드 record_hash(첫 레코드는 0 x 64).
레코드 하나라도 바뀌거나 삭제·삽입되면 verify_chain 이 첫 위치를 찾아낸다.

변경 방지 3중 장치
1) 애플리케이션: 수정·삭제 API 없음 + ORM before_update/before_delete 이벤트에서 예외
2) DB: UPDATE/DELETE 를 거부하는 트리거(SQLite·PostgreSQL)
3) 해시 체인: 위 장치를 우회한 변경(DB 관리자 권한 등)도 검증 시 탐지
(1·2 는 app/db/audit_guards.py)
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.agent.trace import mask_deep
from app.db.audit_guards import AuditTamperError, trigger_statements  # noqa: F401
from app.db.models import AuditRecord

GENESIS_HASH = "0" * 64
MAX_APPEND_RETRIES = 5


def canonical_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def normalize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """저장 전 정규화: 개인정보 재마스킹 + JSON 왕복(Decimal·datetime 등을 문자열로)."""
    return json.loads(json.dumps(mask_deep(payload), ensure_ascii=False, default=str))


def compute_hash(
    *,
    tenant_id: str,
    seq: int,
    request_id: str,
    status: str,
    prev_hash: str,
    payload: dict[str, Any],
) -> str:
    material = canonical_json(
        {
            "tenant_id": tenant_id,
            "seq": seq,
            "request_id": request_id,
            "status": status,
            "prev_hash": prev_hash,
            "payload": payload,
        }
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def append_audit(
    session: Session, *, tenant_id: str, request_id: str, status: str, payload: dict[str, Any]
) -> AuditRecord:
    payload = normalize_payload({**payload, "recorded_at": datetime.now(UTC).isoformat()})
    for _ in range(MAX_APPEND_RETRIES):
        last = session.scalar(
            select(AuditRecord)
            .where(AuditRecord.tenant_id == tenant_id)
            .order_by(AuditRecord.seq.desc())
            .limit(1)
        )
        seq = (last.seq + 1) if last else 1
        prev_hash = last.record_hash if last else GENESIS_HASH
        record = AuditRecord(
            tenant_id=tenant_id,
            seq=seq,
            request_id=request_id,
            status=status,
            payload=payload,
            prev_hash=prev_hash,
            record_hash=compute_hash(
                tenant_id=tenant_id,
                seq=seq,
                request_id=request_id,
                status=status,
                prev_hash=prev_hash,
                payload=payload,
            ),
        )
        session.add(record)
        try:
            session.commit()
            return record
        except IntegrityError:  # 동시 기록으로 seq 충돌 → 다시 시도
            session.rollback()
    raise RuntimeError("감사 로그 기록 실패(seq 충돌 반복)")


@dataclass(frozen=True)
class VerifyResult:
    ok: bool
    checked: int
    broken_seq: int | None = None
    reason: str | None = None
    last_hash: str | None = None


def verify_chain(session: Session, tenant_id: str) -> VerifyResult:
    prev_hash = GENESIS_HASH
    expected_seq = 1
    checked = 0
    rows = session.scalars(
        select(AuditRecord).where(AuditRecord.tenant_id == tenant_id).order_by(AuditRecord.seq)
    )
    for rec in rows:
        if rec.seq != expected_seq:
            return VerifyResult(
                False,
                checked,
                expected_seq,
                f"seq {expected_seq} 레코드가 없습니다(삭제 또는 삽입 의심)",
            )
        if rec.prev_hash != prev_hash:
            return VerifyResult(False, checked, rec.seq, "prev_hash 가 직전 레코드 해시와 다릅니다")
        actual = compute_hash(
            tenant_id=rec.tenant_id,
            seq=rec.seq,
            request_id=rec.request_id,
            status=rec.status,
            prev_hash=rec.prev_hash,
            payload=rec.payload,
        )
        if actual != rec.record_hash:
            return VerifyResult(
                False, checked, rec.seq, "레코드 내용이 해시와 일치하지 않습니다(위변조 의심)"
            )
        prev_hash = rec.record_hash
        expected_seq += 1
        checked += 1
    return VerifyResult(True, checked, last_hash=prev_hash if checked else None)
