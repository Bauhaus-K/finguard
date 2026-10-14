import pytest

from app.privacy.pii import PIIType, mask_pii


@pytest.mark.parametrize(
    ("text", "pii_type"),
    [
        ("주민번호 900101-1234567 입니다", PIIType.RRN),
        ("주민번호 9001011234567", PIIType.RRN),
        ("외국인 900101-5234567", PIIType.RRN),
        ("카드 1234-5678-9012-3456", PIIType.CARD),
        ("카드 1234 5678 9012 3456", PIIType.CARD),
        ("카드 1234567890123456", PIIType.CARD),
        ("전화 010-1234-5678", PIIType.PHONE),
        ("전화 01012345678", PIIType.PHONE),
        ("전화 02-123-4567", PIIType.PHONE),
        ("계좌 110-123-456789", PIIType.ACCOUNT),
        ("계좌 3333-01-1234567", PIIType.ACCOUNT),
    ],
)
def test_detects_and_masks(text, pii_type):
    r = mask_pii(text)
    assert r.counts == {pii_type: 1}
    assert not any(ch.isdigit() for ch in r.text)


@pytest.mark.parametrize(
    "text",
    [
        "1,000만 원을 12개월 예치하면 279,180원",
        "10,000,000원",
        "2026-10-14 기준",
        "연 3.30%, 1,095일",
        "상품코드 HB-DEP-001",
        "1234567",  # 짧은 숫자열
    ],
)
def test_no_false_positive(text):
    r = mask_pii(text)
    assert not r.found
    assert r.text == text


def test_multiple():
    r = mask_pii("900101-1234567 / 010-1111-2222 / 010-3333-4444")
    assert r.counts == {PIIType.RRN: 1, PIIType.PHONE: 2}
    assert r.text == "[주민등록번호] / [전화번호] / [전화번호]"
