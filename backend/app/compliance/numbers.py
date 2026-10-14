"""한국어 텍스트에서 단위가 붙은 수치를 추출·정규화한다.

게이트웨이 수치 검증(Phase 3)과 Phase 2 수동 검증 스크립트가 공유한다.
단위 없는 숫자(조항 번호, 회차 등)는 추출하지 않는다.

정규화 규칙
- 금액: 원 단위 정수. "1,000만 원" → 10000000, "1억 2,000만원" → 120000000, "5천만 원" → 50000000
- 비율: % / %p → PERCENT. "연 3.30%" → 3.30 (Decimal 비교이므로 3.3 과 같다)
- 기간: "12개월" → MONTHS 12, "3년" → MONTHS 36 (연도 표기 1900~2100 은 제외), "1,095일" → DAYS 1095
"""

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from app.calc.common import FigureUnit

_NUM = r"\d[\d,]*(?:\.\d+)?"
_KR_MULT = {
    "조": 10**12,
    "억": 10**8,
    "천만": 10**7,
    "백만": 10**6,
    "십만": 10**5,
    "만": 10**4,
    "천": 10**3,
}

# 금액: (숫자 + 한글 배수)* + 원
_AMOUNT = re.compile(
    rf"(?<![\d.])((?:{_NUM}\s*(?:조|억|천만|백만|십만|만|천)\s*)*{_NUM}\s*(?:조|억|천만|백만|십만|만|천)?)\s*원"
)
_AMOUNT_PART = re.compile(rf"({_NUM})\s*(조|억|천만|백만|십만|만|천)?")
_PERCENT = re.compile(rf"(?<![\d.])({_NUM})\s*(?:%p|%|퍼센트|％)")
_MONTHS = re.compile(rf"(?<![\d.])({_NUM})\s*개월")
_YEARS = re.compile(rf"(?<![\d.])({_NUM})\s*년(?!도)")
_DAYS = re.compile(rf"(?<![\d.])({_NUM})\s*일(?![반시])")


@dataclass(frozen=True)
class ExtractedNumber:
    unit: FigureUnit
    value: Decimal
    text: str  # 원문 표기
    start: int
    end: int

    @property
    def key(self) -> tuple[FigureUnit, Decimal]:
        return (self.unit, self.value.normalize())


def _dec(raw: str) -> Decimal | None:
    try:
        return Decimal(raw.replace(",", ""))
    except InvalidOperation:
        return None


def parse_korean_amount(expr: str) -> Decimal | None:
    """'1억 2,000만' → 120000000. 배수 없는 마지막 숫자는 1원 단위."""
    total = Decimal(0)
    matched = False
    for m in _AMOUNT_PART.finditer(expr):
        num = _dec(m.group(1))
        if num is None:
            return None
        total += num * _KR_MULT.get(m.group(2) or "", 1)
        matched = True
    return total if matched else None


def extract_numbers(text: str) -> list[ExtractedNumber]:
    found: list[ExtractedNumber] = []
    taken: list[tuple[int, int]] = []

    def _add(unit: FigureUnit, value: Decimal | None, m: re.Match[str]) -> None:
        if value is None:
            return
        if any(s < m.end() and m.start() < e for s, e in taken):
            return
        taken.append((m.start(), m.end()))
        found.append(ExtractedNumber(unit, value, m.group(0), m.start(), m.end()))

    for m in _AMOUNT.finditer(text):
        _add(FigureUnit.KRW, parse_korean_amount(m.group(1)), m)
    for m in _PERCENT.finditer(text):
        _add(FigureUnit.PERCENT, _dec(m.group(1)), m)
    for m in _MONTHS.finditer(text):
        _add(FigureUnit.MONTHS, _dec(m.group(1)), m)
    for m in _YEARS.finditer(text):
        years = _dec(m.group(1))
        if years is not None and not (1900 <= years <= 2100):
            _add(FigureUnit.MONTHS, years * 12, m)
    for m in _DAYS.finditer(text):
        _add(FigureUnit.DAYS, _dec(m.group(1)), m)

    found.sort(key=lambda n: n.start)
    return found
