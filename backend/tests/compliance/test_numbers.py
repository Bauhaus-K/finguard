from decimal import Decimal as D

import pytest

from app.calc.common import Figure, FigureUnit, krw, months, pct
from app.compliance.numbers import extract_numbers, parse_korean_amount
from app.compliance.provenance import check_provenance

K, P, M, DY = FigureUnit.KRW, FigureUnit.PERCENT, FigureUnit.MONTHS, FigureUnit.DAYS


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("279,180원", [(K, D(279180))]),
        ("1,000만 원", [(K, D(10_000_000))]),
        ("1000만원", [(K, D(10_000_000))]),
        ("1억 2,000만원", [(K, D(120_000_000))]),
        ("1억원", [(K, D(100_000_000))]),
        ("5천만 원", [(K, D(50_000_000))]),
        ("1백만 원", [(K, D(1_000_000))]),
        ("10만 원", [(K, D(100_000))]),
        ("2.5억 원", [(K, D(250_000_000))]),
        ("연 3.30%", [(P, D("3.30"))]),
        ("연 0.10%p", [(P, D("0.10"))]),
        ("5 퍼센트", [(P, D(5))]),
        ("12개월", [(M, D(12))]),
        ("3년", [(M, D(36))]),
        ("1,095일", [(DY, D(1095))]),
        ("2026년 10월 기준", []),
        ("제6조 제2항, 3회차", []),
        ("매월 1일부터", [(DY, D(1))]),
    ],
)
def test_extract(text, expected):
    assert [(n.unit, n.value) for n in extract_numbers(text)] == expected


def test_extract_sentence_order_and_spans():
    text = "1,000만 원을 연 3.3%로 12개월 맡기면 세후 279,180원입니다."
    nums = extract_numbers(text)
    assert [n.text for n in nums] == ["1,000만 원", "3.3%", "12개월", "279,180원"]
    assert all(text[n.start : n.end] == n.text for n in nums)


def test_parse_amount_invalid():
    assert parse_korean_amount("원") is None


def test_provenance_ok_with_equal_decimal_forms():
    sources = [krw("x", D(279180)), pct("r", D("3.30")), months("m", 12), krw("p", D(10_000_000))]
    report = check_provenance("1,000만 원, 연 3.3%, 12개월, 세후 279,180원", sources)
    assert report.ok
    assert len(report.checked) == 4


def test_provenance_flags_unsourced_and_rounded():
    sources = [krw("x", D(279180))]
    report = check_provenance("세후 약 28만 원, 정확히는 279,180원, 금리 연 3.5%", sources)
    assert [n.text for n in report.unsourced] == ["28만 원", "3.5%"]
    assert not report.ok


def test_provenance_unit_must_match():
    report = check_provenance("12%", [Figure(name="m", value=D(12), unit=FigureUnit.MONTHS)])
    assert not report.ok
