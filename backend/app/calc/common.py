"""계산 엔진 공통 타입과 상수."""

from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

# 입력 한도 (경계값 테스트 대상)
MAX_AMOUNT = Decimal("100000000000")  # 1,000억 원
MAX_RATE_PERCENT = Decimal("100")
MAX_TERM_MONTHS = 600  # 50년
MAX_TERM_DAYS = MAX_TERM_MONTHS * 31

DEFAULT_TAX_RATE = Decimal("0.154")  # 이자소득세 14% + 지방소득세 1.4%
HUNDRED = Decimal("100")
TWELVE = Decimal("12")


class InterestMethod(StrEnum):
    SIMPLE = "SIMPLE"  # 단리
    MONTHLY_COMPOUND = "MONTHLY_COMPOUND"  # 월복리


class TaxType(StrEnum):
    GENERAL = "GENERAL"  # 일반과세 (기본 15.4%)
    TAX_FREE = "TAX_FREE"  # 비과세


class RepaymentMethod(StrEnum):
    EQUAL_PAYMENT = "EQUAL_PAYMENT"  # 원리금균등
    EQUAL_PRINCIPAL = "EQUAL_PRINCIPAL"  # 원금균등
    BULLET = "BULLET"  # 만기일시


class FigureUnit(StrEnum):
    KRW = "KRW"
    PERCENT = "PERCENT"
    MONTHS = "MONTHS"
    DAYS = "DAYS"


class Figure(BaseModel):
    """게이트웨이 수치 검증에서 '출처'로 사용되는 정규화된 수치."""

    model_config = ConfigDict(frozen=True)

    name: str
    value: Decimal
    unit: FigureUnit


class CalcModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


def krw(name: str, value: Decimal) -> Figure:
    return Figure(name=name, value=value, unit=FigureUnit.KRW)


def pct(name: str, value: Decimal) -> Figure:
    return Figure(name=name, value=value, unit=FigureUnit.PERCENT)


def months(name: str, value: int) -> Figure:
    return Figure(name=name, value=Decimal(value), unit=FigureUnit.MONTHS)
