"""정기예금 만기 이자 계산.

- 단리: 이자 = 원금 × 연이율 × 개월 / 12 (월할)
- 월복리: 이자 = 원금 × (1 + 연이율/12)^개월 − 원금
- 세전이자를 먼저 원 단위로 맞춘 뒤 세액을 계산한다.
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

FORMULA_SIMPLE = "deposit.simple.v1"
FORMULA_COMPOUND = "deposit.monthly_compound.v1"


class DepositInput(CalcModel):
    principal: Decimal = Field(ge=0, le=MAX_AMOUNT, decimal_places=0, description="예치 원금(원)")
    annual_rate: Decimal = Field(ge=0, le=MAX_RATE_PERCENT, description="연 금리(%)")
    months: int = Field(ge=1, le=MAX_TERM_MONTHS, description="예치 기간(개월)")
    method: InterestMethod = InterestMethod.SIMPLE
    tax_type: TaxType = TaxType.GENERAL
    tax_rate: Decimal = Field(default=DEFAULT_TAX_RATE, ge=0, le=1)
    rounding: RoundingMode = RoundingMode.TRUNCATE


class DepositResult(CalcModel):
    formula_id: str
    inputs: DepositInput
    principal: Decimal
    pre_tax_interest: Decimal
    tax: Decimal
    after_tax_interest: Decimal
    maturity_amount: Decimal
    figures: list[Figure]


def raw_deposit_interest(
    principal: Decimal, annual_rate: Decimal, n_months: int, method: InterestMethod
) -> Decimal:
    """반올림 전 세전이자."""
    rate = annual_rate / HUNDRED
    with localcontext() as ctx:
        ctx.prec = 40
        if method is InterestMethod.SIMPLE:
            return principal * rate * Decimal(n_months) / TWELVE
        return principal * (1 + rate / TWELVE) ** n_months - principal


def calculate_deposit(inp: DepositInput) -> DepositResult:
    raw = raw_deposit_interest(inp.principal, inp.annual_rate, inp.months, inp.method)
    pre_tax = round_won(raw, inp.rounding)
    tax = interest_tax(pre_tax, inp.tax_type, inp.tax_rate, inp.rounding)
    after_tax = pre_tax - tax
    maturity = inp.principal + after_tax
    formula = FORMULA_SIMPLE if inp.method is InterestMethod.SIMPLE else FORMULA_COMPOUND
    return DepositResult(
        formula_id=formula,
        inputs=inp,
        principal=inp.principal,
        pre_tax_interest=pre_tax,
        tax=tax,
        after_tax_interest=after_tax,
        maturity_amount=maturity,
        figures=[
            krw("principal", inp.principal),
            pct("annual_rate", inp.annual_rate),
            months("months", inp.months),
            krw("pre_tax_interest", pre_tax),
            krw("tax", tax),
            krw("after_tax_interest", after_tax),
            krw("maturity_amount", maturity),
        ],
    )
