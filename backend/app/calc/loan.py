"""대출 상환 스케줄 계산.

월 이율 = 연이율 / 12 (월할). 회차별 이자 = round(잔액 × 월 이율).
- 원리금균등: 월 상환액 = round(P·i·(1+i)^n / ((1+i)^n − 1)), 금리 0%면 round(P/n)
- 원금균등: 월 원금 = round(P/n), 이자는 잔액 기준
- 만기일시: 매월 이자만, 마지막 회차에 원금 전액
반올림 잔차는 마지막 회차가 흡수한다(마지막 회차 원금 = 남은 잔액).
"""

from decimal import Decimal, localcontext

from pydantic import Field

from app.calc.common import (
    HUNDRED,
    MAX_AMOUNT,
    MAX_RATE_PERCENT,
    MAX_TERM_MONTHS,
    TWELVE,
    CalcModel,
    Figure,
    RepaymentMethod,
    krw,
    months,
    pct,
)
from app.calc.rounding import RoundingMode, round_won

FORMULA_IDS = {
    RepaymentMethod.EQUAL_PAYMENT: "loan.equal_payment.v1",
    RepaymentMethod.EQUAL_PRINCIPAL: "loan.equal_principal.v1",
    RepaymentMethod.BULLET: "loan.bullet.v1",
}


class LoanInput(CalcModel):
    principal: Decimal = Field(ge=0, le=MAX_AMOUNT, decimal_places=0, description="대출 원금(원)")
    annual_rate: Decimal = Field(ge=0, le=MAX_RATE_PERCENT, description="연 금리(%)")
    months: int = Field(ge=1, le=MAX_TERM_MONTHS, description="대출 기간(개월)")
    method: RepaymentMethod = RepaymentMethod.EQUAL_PAYMENT
    rounding: RoundingMode = RoundingMode.TRUNCATE


class Installment(CalcModel):
    no: int
    payment: Decimal
    principal: Decimal
    interest: Decimal
    balance: Decimal  # 상환 후 잔액


class LoanResult(CalcModel):
    formula_id: str
    inputs: LoanInput
    schedule: list[Installment]
    first_payment: Decimal
    last_payment: Decimal
    total_payment: Decimal
    total_interest: Decimal
    figures: list[Figure]


def equal_payment_amount(
    principal: Decimal, monthly_rate: Decimal, n_months: int, rounding: RoundingMode
) -> Decimal:
    """원리금균등 월 상환액(원 단위)."""
    with localcontext() as ctx:
        ctx.prec = 40
        if monthly_rate == 0:
            raw = principal / Decimal(n_months)
        else:
            growth = (1 + monthly_rate) ** n_months
            raw = principal * monthly_rate * growth / (growth - 1)
    return round_won(raw, rounding)


def _principal_part(inp: LoanInput, monthly_rate: Decimal, interest: Decimal) -> Decimal:
    """마지막 회차가 아닐 때의 정기 원금 상환분(잔액 상한 적용 전)."""
    if inp.method is RepaymentMethod.EQUAL_PAYMENT:
        pmt = equal_payment_amount(inp.principal, monthly_rate, inp.months, inp.rounding)
        return pmt - interest
    if inp.method is RepaymentMethod.EQUAL_PRINCIPAL:
        return round_won(inp.principal / Decimal(inp.months), inp.rounding)
    return Decimal("0")  # BULLET


def calculate_loan(inp: LoanInput) -> LoanResult:
    monthly_rate = inp.annual_rate / HUNDRED / TWELVE
    balance = inp.principal
    schedule: list[Installment] = []
    for no in range(1, inp.months + 1):
        interest = round_won(balance * monthly_rate, inp.rounding)
        if no == inp.months:
            principal_part = balance
        else:
            principal_part = min(_principal_part(inp, monthly_rate, interest), balance)
        balance -= principal_part
        schedule.append(
            Installment(
                no=no,
                payment=principal_part + interest,
                principal=principal_part,
                interest=interest,
                balance=balance,
            )
        )

    total_payment = sum((row.payment for row in schedule), start=Decimal("0"))
    total_interest = sum((row.interest for row in schedule), start=Decimal("0"))
    first, last = schedule[0].payment, schedule[-1].payment
    return LoanResult(
        formula_id=FORMULA_IDS[inp.method],
        inputs=inp,
        schedule=schedule,
        first_payment=first,
        last_payment=last,
        total_payment=total_payment,
        total_interest=total_interest,
        figures=[
            krw("principal", inp.principal),
            pct("annual_rate", inp.annual_rate),
            months("months", inp.months),
            krw("first_payment", first),
            krw("last_payment", last),
            krw("total_payment", total_payment),
            krw("total_interest", total_interest),
        ],
    )
