"""감사 로그 테이블 변경 방지 장치(ORM 이벤트 + DB 트리거). app.db.models 가 로드될 때 등록된다."""

from typing import Any

from sqlalchemy import DDL, event

from app.db.models import AuditRecord


class AuditTamperError(Exception):
    pass


@event.listens_for(AuditRecord, "before_update")
def _no_update(*_: Any) -> None:
    raise AuditTamperError("감사 로그는 수정할 수 없습니다(append-only)")


@event.listens_for(AuditRecord, "before_delete")
def _no_delete(*_: Any) -> None:
    raise AuditTamperError("감사 로그는 삭제할 수 없습니다(append-only)")


SQLITE_TRIGGERS = [
    "CREATE TRIGGER IF NOT EXISTS audit_records_no_update BEFORE UPDATE ON audit_records "
    "BEGIN SELECT RAISE(ABORT, 'audit_records is append-only'); END",
    "CREATE TRIGGER IF NOT EXISTS audit_records_no_delete BEFORE DELETE ON audit_records "
    "BEGIN SELECT RAISE(ABORT, 'audit_records is append-only'); END",
]
POSTGRES_TRIGGERS = [
    "CREATE OR REPLACE FUNCTION audit_records_append_only() RETURNS trigger AS $$ "
    "BEGIN RAISE EXCEPTION 'audit_records is append-only'; END; $$ LANGUAGE plpgsql",
    "DROP TRIGGER IF EXISTS audit_records_no_modify ON audit_records",
    "CREATE TRIGGER audit_records_no_modify BEFORE UPDATE OR DELETE ON audit_records "
    "FOR EACH ROW EXECUTE FUNCTION audit_records_append_only()",
]


def trigger_statements(dialect: str) -> list[str]:
    return {"sqlite": SQLITE_TRIGGERS, "postgresql": POSTGRES_TRIGGERS}.get(dialect, [])


# create_all(테스트) 경로에서도 트리거를 만든다. 운영 스키마는 Alembic 0002 가 만든다.
for _stmt in SQLITE_TRIGGERS:
    event.listen(AuditRecord.__table__, "after_create", DDL(_stmt).execute_if(dialect="sqlite"))
for _stmt in POSTGRES_TRIGGERS:
    event.listen(AuditRecord.__table__, "after_create", DDL(_stmt).execute_if(dialect="postgresql"))
