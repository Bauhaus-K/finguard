import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DatabaseError

from app.audit.hashchain import (
    GENESIS_HASH,
    append_audit,
    compute_hash,
    normalize_payload,
    verify_chain,
)
from app.db.audit_guards import AuditTamperError
from app.db.models import AuditRecord


@pytest.fixture
def chain(seeded_session):
    for i in range(5):
        append_audit(
            seeded_session,
            tenant_id="demo",
            request_id=f"req_{i}",
            status="PASS",
            payload={"final": {"answer": f"답변 {i}"}, "n": i},
        )
    return seeded_session


def _drop_triggers(session):
    session.execute(text("DROP TRIGGER audit_records_no_update"))
    session.execute(text("DROP TRIGGER audit_records_no_delete"))
    session.commit()


def test_chain_links(chain):
    rows = list(chain.scalars(select(AuditRecord).order_by(AuditRecord.seq)))
    assert [r.seq for r in rows] == [1, 2, 3, 4, 5]
    assert rows[0].prev_hash == GENESIS_HASH
    assert all(rows[i].prev_hash == rows[i - 1].record_hash for i in range(1, 5))
    assert "recorded_at" in rows[0].payload
    result = verify_chain(chain, "demo")
    assert result.ok and result.checked == 5 and result.last_hash == rows[-1].record_hash


def test_empty_chain_ok(seeded_session):
    r = verify_chain(seeded_session, "demo")
    assert r.ok and r.checked == 0 and r.last_hash is None


def test_orm_update_and_delete_blocked(chain):
    rec = chain.scalar(select(AuditRecord).where(AuditRecord.seq == 2))
    rec.status = "BLOCKED"
    with pytest.raises(AuditTamperError):
        chain.commit()
    chain.rollback()
    chain.delete(chain.scalar(select(AuditRecord).where(AuditRecord.seq == 2)))
    with pytest.raises(AuditTamperError):
        chain.commit()
    chain.rollback()


def test_db_trigger_blocks_raw_sql(chain):
    with pytest.raises(DatabaseError, match="append-only"):
        chain.execute(text("UPDATE audit_records SET status='X' WHERE seq=1"))
    chain.rollback()
    with pytest.raises(DatabaseError, match="append-only"):
        chain.execute(text("DELETE FROM audit_records WHERE seq=1"))
    chain.rollback()


def test_tampered_payload_detected(chain):
    """수용 기준: DB 관리자 권한으로 트리거를 우회해 내용을 바꿔도 해시 체인이 탐지한다."""
    _drop_triggers(chain)
    chain.execute(
        text("UPDATE audit_records SET payload = :p WHERE seq = 3"),
        {"p": '{"final": {"answer": "조작된 답변"}, "n": 2}'},
    )
    chain.commit()
    chain.expire_all()
    r = verify_chain(chain, "demo")
    assert not r.ok
    assert r.broken_seq == 3 and r.checked == 2
    assert "위변조" in r.reason


def test_tampered_status_detected(chain):
    _drop_triggers(chain)
    chain.execute(text("UPDATE audit_records SET status='PASS_FAKE' WHERE seq=5"))
    chain.commit()
    chain.expire_all()
    assert verify_chain(chain, "demo").broken_seq == 5


def test_recomputed_hash_breaks_next_link(chain):
    """레코드 해시까지 다시 계산해 넣어도 다음 레코드의 prev_hash 가 맞지 않는다."""
    _drop_triggers(chain)
    rec = chain.scalar(select(AuditRecord).where(AuditRecord.seq == 2))
    forged_payload = {**rec.payload, "final": {"answer": "조작"}}
    forged_hash = compute_hash(
        tenant_id="demo",
        seq=2,
        request_id=rec.request_id,
        status=rec.status,
        prev_hash=rec.prev_hash,
        payload=forged_payload,
    )
    chain.execute(
        text("UPDATE audit_records SET payload = :p, record_hash = :h WHERE seq = 2"),
        {"p": __import__("json").dumps(forged_payload, ensure_ascii=False), "h": forged_hash},
    )
    chain.commit()
    chain.expire_all()
    r = verify_chain(chain, "demo")
    assert r.broken_seq == 3 and "prev_hash" in r.reason


def test_deleted_record_detected(chain):
    _drop_triggers(chain)
    chain.execute(text("DELETE FROM audit_records WHERE seq = 2"))
    chain.commit()
    chain.expire_all()
    r = verify_chain(chain, "demo")
    assert r.broken_seq == 2 and "삭제" in r.reason


def test_tenants_have_independent_chains(chain):
    from app.db.models import Tenant

    chain.add(Tenant(id="other", name="다른 테넌트(가상)", api_key_hash="x" * 64))
    chain.commit()
    rec = append_audit(chain, tenant_id="other", request_id="r", status="PASS", payload={})
    assert rec.seq == 1 and rec.prev_hash == GENESIS_HASH
    assert verify_chain(chain, "demo").ok and verify_chain(chain, "other").ok


def test_payload_normalized_and_masked(seeded_session):
    from decimal import Decimal

    rec = append_audit(
        seeded_session,
        tenant_id="demo",
        request_id="r",
        status="PASS",
        payload={"input": {"user_message": "주민번호 900101-1234567"}, "amount": Decimal("1.50")},
    )
    assert rec.payload["input"]["user_message"] == "주민번호 [주민등록번호]"
    assert rec.payload["amount"] == "1.50"
    assert normalize_payload({"a": [1, "010-1234-5678"]}) == {"a": [1, "[전화번호]"]}


def test_seq_conflict_retry(seeded_session, monkeypatch):
    from sqlalchemy.exc import IntegrityError

    calls = {"n": 0}
    original = seeded_session.commit

    def flaky_commit():
        calls["n"] += 1
        if calls["n"] == 1:
            raise IntegrityError("stmt", {}, Exception("unique"))
        return original()

    monkeypatch.setattr(seeded_session, "commit", flaky_commit)
    rec = append_audit(seeded_session, tenant_id="demo", request_id="r", status="PASS", payload={})
    assert rec.seq == 1 and calls["n"] == 2


def test_seq_conflict_gives_up(seeded_session, monkeypatch):
    from sqlalchemy.exc import IntegrityError

    def always_conflict():
        raise IntegrityError("stmt", {}, Exception("unique"))

    monkeypatch.setattr(seeded_session, "commit", always_conflict)
    with pytest.raises(RuntimeError, match="seq"):
        append_audit(seeded_session, tenant_id="demo", request_id="r", status="PASS", payload={})
