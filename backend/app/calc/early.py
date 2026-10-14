"""중도해지 이자, 중도상환수수료 계산.

중도해지 이자
- 경과 개월 수에 해당하는 구간(tier)을 찾아 적용이율 = 약정이율 × 구간 비율.
- 중도해지 이자는 단리로 계산한다(정기예금: 원금 기준, 적금: 납입 회차별).
- 구간표는 상품 카탈로그(early_termination_tiers)에서 가져온다.

중도상환수수료
- 수수료 = 중도상환원금 × 수수료율 × 잔여일수 / 대출기간(일)
- 경과일수가 면제 기간(기본 3년 = 1,095일) 이상이면 면제.
"""

from decimal import Decimal
from enum import StrEnum
from typing import Self

from pydantic import Field, model_validator

from app.calc.common import (
    DEFAULT_TAX_RATE,
    HUNDRED,
    MAX_AMOUNT,
    MAX_RATE_PERCENT,
    MAX_TERM_DAYS,
    MAX_TERM_MONTHS,
    CalcModel,
    Figure,
    FigureUnit,
    InterestMethod,
    TaxType,
    krw,
    months,
    pct,
)
from app.calc.deposit import raw_deposit_interest
from app.calc.rounding import RoundingMode, round_won
from app.calc.savings import raw_savings_interest
from app.calc.tax import interest_tax

FORMULA_EARLY_DEPOSIT = "early_termination.deposit.simple.v1"
FORMULA_EARLY_SAVINGS = "early_termination.savings.simple.v1"
FORMULA_PREPAYMENT_FEE = "prepayment_fee.remaining_days.v1"
DEFAULT_PREPAYMENT_EXEMPTION_DAYS = 1095


class EarlyTerminationKind(StrEnum):
    DEPOSIT = "DEPOSIT"
    SAVINGS = "SAVINGS"


class EarlyTerminationTier(CalcModel):
    min_elapsed_months: int = Field(ge=0, le=MAX_TERM_MONTHS)
    rate_ratio: Decimal = Field(ge=0, le=1, description="약정이율 대비 적용 비율")


class EarlyTerminationInput(CalcModel):
    kind: EarlyTerminationKind
    amount: Decimal = Field(
        ge=0, le=MAX_AMOUNT, decimal_places=0, description="예금 원금 또는 적금 월 납입액(원)"
    )
    contracted_rate: Decimal = Field(ge=0, le=MAX_RATE_PERCENT, description="약정 연 금리(%)")
    term_months: int = Field(ge=1, le=MAX_TERM_MONTHS)
    elapsed_months: int = Field(ge=0, le=MAX_TERM_MONTHS)
    tiers: list[EarlyTerminationTier] = Field(min_length=1)
    tax_type: TaxType = TaxType.GENERAL
    tax_rate: Decimal = Field(default=DEFAULT_TAX_RATE, ge=0, le=1)
    rounding: RoundingMode = RoundingMode.TRUNCATE

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.elapsed_months >= self.term_months:
            raise ValueError(
                "elapsed_months must be less than term_months (만기 이후는 중도해지가 아님)"
            )
        if not any(t.min_elapsed_months == 0 for t in self.tiers):
            raise ValueError("tiers must include a tier with min_elapsed_months=0")
        return self


class EarlyTerminationResult(CalcModel):
    formula_id: str
    inputs: EarlyTerminationInput
    applied_tier: EarlyTerminationTier
    applied_rate: Decimal
    principal_returned: Decimal
    pre_tax_interest: Decimal
    tax: Decimal
    after_tax_interest: Decimal
    payout: Decimal
    figures: list[Figure]


def select_tier(tiers: list[EarlyTerminationTier], elapsed_months: int) -> EarlyTerminationTier:
    eligible = [t for t in tiers if t.min_elapsed_months <= elapsed_months]
    return max(eligible, key=lambda t: t.min_elapsed_months)


def calculate_early_termination(inp: EarlyTerminationInput) -> EarlyTerminationResult:
    tier = select_tier(inp.tiers, inp.elapsed_months)
    applied_rate = inp.contracted_rate * tier.rate_ratio
    if inp.kind is EarlyTerminationKind.DEPOSIT:
        formula = FORMULA_EARLY_DEPOSIT
        returned = inp.amount
        raw = raw_deposit_interest(
            inp.amount, applied_rate, inp.elapsed_months, InterestMethod.SIMPLE
        )
    else:
        formula = FORMULA_EARLY_SAVINGS
        returned = inp.amount * inp.elapsed_months
        raw = raw_savings_interest(
            inp.amount, applied_rate, inp.elapsed_months, InterestMethod.SIMPLE
        )
    pre_tax = round_won(raw, inp.rounding)
    tax = interest_tax(pre_tax, inp.tax_type, inp.tax_rate, inp.rounding)
    after_tax = pre_tax - tax
    payout = returned + after_tax
    return EarlyTerminationResult(
        formula_id=formula,
        inputs=inp,
        applied_tier=tier,
        applied_rate=applied_rate,
        principal_returned=returned,
        pre_tax_interest=pre_tax,
        tax=tax,
        after_tax_interest=after_tax,
        payout=payout,
        figures=[
            pct("contracted_rate", inp.contracted_rate),
            pct("applied_rate", applied_rate),
            months("elapsed_months", inp.elapsed_months),
            krw("principal_returned", returned),
            krw("pre_tax_interest", pre_tax),
            krw("tax", tax),
            krw("after_tax_interest", after_tax),
            krw("payout", payout),
        ],
    )


class PrepaymentFeeInput(CalcModel):
    prepay_amount: Decimal = Field(
        ge=0, le=MAX_AMOUNT, decimal_places=0, description="중도상환원금(원)"
    )
    fee_rate: Decimal = Field(ge=0, le=MAX_RATE_PERCENT, description="중도상환수수료율(%)")
    loan_days: int = Field(ge=1, le=MAX_TERM_DAYS, description="대출기간(일)")
    elapsed_days: int = Field(ge=0, le=MAX_TERM_DAYS, description="대출 실행 후 경과일수")
    exemption_days: int | None = Field(
        default=DEFAULT_PREPAYMENT_EXEMPTION_DAYS,
        ge=0,
        description="이 일수 이상 경과 시 수수료 면제. None 이면 면제 없음",
    )
    rounding: RoundingMode = RoundingMode.TRUNCATE

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.elapsed_days > self.loan_days:
            raise ValueError("elapsed_days must not exceed loan_days")
        return self


class PrepaymentFeeResult(CalcModel):
    formula_id: str
    inputs: PrepaymentFeeInput
    remaining_days: int
    exempted: bool
    fee: Decimal
    figures: list[Figure]


def calculate_prepayment_fee(inp: PrepaymentFeeInput) -> PrepaymentFeeResult:
    remaining = inp.loan_days - inp.elapsed_days
    exempted = inp.exemption_days is not None and inp.elapsed_days >= inp.exemption_days
    if exempted:
        fee = Decimal("0")
    else:
        raw = (
            inp.prepay_amount * inp.fee_rate / HUNDRED * Decimal(remaining) / Decimal(inp.loan_days)
        )
        fee = round_won(raw, inp.rounding)
    return PrepaymentFeeResult(
        formula_id=FORMULA_PREPAYMENT_FEE,
        inputs=inp,
        remaining_days=remaining,
        exempted=exempted,
        fee=fee,
        figures=[
            krw("prepay_amount", inp.prepay_amount),
            pct("fee_rate", inp.fee_rate),
            Figure(name="remaining_days", value=Decimal(remaining), unit=FigureUnit.DAYS),
            krw("fee", fee),
        ],
    )
