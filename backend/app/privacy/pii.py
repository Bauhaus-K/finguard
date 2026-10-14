"""개인정보 탐지·마스킹.

입력(고객 메시지)과 출력(답변), 그리고 로그에 저장되는 모든 텍스트에 적용한다.
원문은 어디에도 저장하지 않고, 마스킹된 값과 탐지 유형별 건수만 남긴다.
"""

import re
from dataclasses import dataclass, field
from enum import StrEnum


class PIIType(StrEnum):
    RRN = "RRN"  # 주민등록번호 / 외국인등록번호
    CARD = "CARD"  # 카드번호
    PHONE = "PHONE"  # 전화번호
    ACCOUNT = "ACCOUNT"  # 계좌번호


PLACEHOLDER = {
    PIIType.RRN: "[주민등록번호]",
    PIIType.CARD: "[카드번호]",
    PIIType.PHONE: "[전화번호]",
    PIIType.ACCOUNT: "[계좌번호]",
}

_D = r"(?<!\d)"  # 앞에 숫자가 붙어 있지 않음
_E = r"(?!\d)"  # 뒤에 숫자가 붙어 있지 않음

# 탐지 순서가 중요하다: 더 구체적인 패턴부터.
_PATTERNS: list[tuple[PIIType, re.Pattern[str]]] = [
    (
        PIIType.RRN,
        re.compile(_D + r"\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\s?-?\s?[1-8]\d{6}" + _E),
    ),
    (PIIType.CARD, re.compile(_D + r"\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}" + _E)),
    (
        PIIType.PHONE,
        re.compile(_D + r"(?:01[016789]|0[2-6]\d?|070)[- ]?\d{3,4}[- ]?\d{4}" + _E),
    ),
    (PIIType.ACCOUNT, re.compile(_D + r"\d{2,6}-\d{2,6}-\d{2,8}(?:-\d{1,3})?" + _E)),
]

_MIN_ACCOUNT_DIGITS = 10  # 날짜(2026-10-14) 등 짧은 숫자열 오탐 방지


@dataclass
class MaskResult:
    text: str
    counts: dict[PIIType, int] = field(default_factory=dict)

    @property
    def found(self) -> bool:
        return bool(self.counts)


def mask_pii(text: str) -> MaskResult:
    counts: dict[PIIType, int] = {}

    for pii_type, pattern in _PATTERNS:

        def _replace(m: re.Match[str], pii_type: PIIType = pii_type) -> str:
            digits = sum(ch.isdigit() for ch in m.group(0))
            if pii_type is PIIType.ACCOUNT and digits < _MIN_ACCOUNT_DIGITS:
                return m.group(0)
            counts[pii_type] = counts.get(pii_type, 0) + 1
            return PLACEHOLDER[pii_type]

        text = pattern.sub(_replace, text)
    return MaskResult(text=text, counts=counts)
