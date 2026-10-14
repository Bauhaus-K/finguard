"""정기적금(정액적립식) 만기 수령액 계산.

매월 같은 금액을 1회차부터 n회차까지 납입한다고 가정한다.
k회차 납입금의 예치 개월 수 = n − k + 1.
- 단리: 회차별 이자 = 월납입액 × 연이율 × 예치개월 / 12
  → 합계 = 월납입액 × 연이율/12 × n(n+1)/2
- 월복리: 회차별 이자 = 월납입액 × ((1 + 연이율/12)^예치개월 − 1)
"""

from decimal import Decimal, localcontext

from pydantic import Field

from app.calc.common import (
    DEFAULT_TAX_RATE,
    HUNDRED,
    MAX_AMOUNT,
    MAX_RATE_PERCENT,
    MAX_TERM_MONTHS,
    TWELVE,
    CalcModel,
    Figure,
    InterestMethod,
    TaxType,
    krw,
    months,
    pct,
)
from app.calc.rounding import RoundingMode, round_won
from app.calc.tax import interest_tax

FORMULA_SIMPLE = "savings.simple.v1"
FORMULA_COMPOUND = "savings.monthly_compound.v1"


class SavingsInput(CalcModel):
    monthly_payment: Decimal = Field(
        ge=0, le=MAX_AMOUNT, decimal_places=0, description="월 납입액(원)"
    )
    annual_rate: Decimal = Field(ge=0, le=MAX_RATE_PERCENT, description="연 금리(%)")
    months: int = Field(ge=1, le=MAX_TERM_MONTHS, description="적립 기간(개월)")
    method: InterestMethod = InterestMethod.SIMPLE
    tax_type: TaxType = TaxType.GENERAL
    tax_rate: Decimal = Field(default=DEFAULT_TAX_RATE, ge=0, le=1)
    rounding: RoundingMode = RoundingMode.TRUNCATE


class SavingsResult(CalcModel):
    formula_id: str
    inputs: SavingsInput
    total_payment: Decimal
    pre_tax_interest: Decimal
    tax: Decimal
    after_tax_interest: Decimal
    maturity_amount: Decimal
    figures: list[Figure]


def raw_savings_interest(
    monthly_payment: Decimal, annual_rate: Decimal, n_months: int, method: InterestMethod
) -> Decimal:
    """반올림 전 세전이자."""
    rate = annual_rate / HUNDRED
    with localcontext() as ctx:
        ctx.prec = 40
        if method is InterestMethod.SIMPLE:
            month_sum = Decimal(n_months * (n_months + 1) // 2)
            return monthly_payment * rate / TWELVE * month_sum
        growth = 1 + rate / TWELVE
        return sum(
            (monthly_payment * (growth**m - 1) for m in range(1, n_months + 1)),
            start=Decimal("0"),
        )


def calculate_savings(inp: SavingsInput) -> SavingsResult:
    raw = raw_savings_interest(inp.monthly_payment, inp.annual_rate, inp.months, inp.method)
    pre_tax = round_won(raw, inp.rounding)
    tax = interest_tax(pre_tax, inp.tax_type, inp.tax_rate, inp.rounding)
    after_tax = pre_tax - tax
    total_payment = inp.monthly_payment * inp.months
    maturity = total_payment + after_tax
    formula = FORMULA_SIMPLE if inp.method is InterestMethod.SIMPLE else FORMULA_COMPOUND
    return SavingsResult(
        formula_id=formula,
        inputs=inp,
        total_payment=total_payment,
        pre_tax_interest=pre_tax,
        tax=tax,
        after_tax_interest=after_tax,
        maturity_amount=maturity,
        figures=[
            krw("monthly_payment", inp.monthly_payment),
            pct("annual_rate", inp.annual_rate),
            months("months", inp.months),
            krw("total_payment", total_payment),
            krw("pre_tax_interest", pre_tax),
            krw("tax", tax),
            krw("after_tax_interest", after_tax),
            krw("maturity_amount", maturity),
        ],
    )
