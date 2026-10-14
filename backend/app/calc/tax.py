"""이자소득 원천징수 계산."""

from decimal import Decimal

from app.calc.common import TaxType
from app.calc.rounding import RoundingMode, round_won


def interest_tax(
    pre_tax_interest: Decimal,
    tax_type: TaxType,
    tax_rate: Decimal,
    rounding: RoundingMode,
) -> Decimal:
    """세액 = 세전이자 × 세율 (원 단위 반올림 정책 적용). 비과세면 0.

    단순화: 실무의 소득세/지방소득세 분리 절사(10원 단위)는 적용하지 않는다.
    """
    if tax_type is TaxType.TAX_FREE:
        return Decimal("0")
    return round_won(pre_tax_interest * tax_rate, rounding)
