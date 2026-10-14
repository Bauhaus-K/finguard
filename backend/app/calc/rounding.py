"""반올림 정책. 기본값은 원 단위 절사."""

from decimal import ROUND_CEILING, ROUND_DOWN, ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal, localcontext
from enum import StrEnum


class RoundingMode(StrEnum):
    TRUNCATE = "TRUNCATE"  # 원 단위 절사 (기본)
    HALF_UP = "HALF_UP"  # 원 단위 사사오입
    CEILING = "CEILING"  # 원 단위 절상


_DECIMAL_ROUNDING = {
    RoundingMode.TRUNCATE: ROUND_DOWN,
    RoundingMode.HALF_UP: ROUND_HALF_UP,
    RoundingMode.CEILING: ROUND_CEILING,
}

_ONE_WON = Decimal("1")
# 순환소수(예: 0.04/12) 연산에서 생기는 999.999…9 같은 정밀도 잡음을 제거하는 보호 자릿수.
# 정밀도 잡음은 1e-25 수준이므로 소수 12자리로 정규화해도 실제 값에는 영향이 없다.
_GUARD = Decimal("1e-12")


def round_won(amount: Decimal, mode: RoundingMode = RoundingMode.TRUNCATE) -> Decimal:
    """금액을 원 단위 정수로 맞춘다."""
    with localcontext() as ctx:
        ctx.prec = 60
        normalized = amount.quantize(_GUARD, rounding=ROUND_HALF_EVEN)
        return normalized.quantize(_ONE_WON, rounding=_DECIMAL_ROUNDING[mode])
