"""결정론적 계산 엔진.

원칙: 모든 수치는 이 패키지의 순수 함수가 계산한다. LLM은 결과를 설명만 한다.
- 모든 금액·금리는 Decimal 로 다룬다(float 금지).
- 금리 입력은 연 % 단위(예: 3.5 → 연 3.5%).
- 반올림은 계산 마지막 단계에서 rounding.round_won 으로만 수행한다.
"""

from app.calc.common import Figure, FigureUnit, InterestMethod, RepaymentMethod, TaxType
from app.calc.deposit import DepositInput, DepositResult, calculate_deposit
from app.calc.early import (
    EarlyTerminationInput,
    EarlyTerminationResult,
    EarlyTerminationTier,
    PrepaymentFeeInput,
    PrepaymentFeeResult,
    calculate_early_termination,
    calculate_prepayment_fee,
)
from app.calc.loan import LoanInput, LoanResult, calculate_loan
from app.calc.rounding import RoundingMode, round_won
from app.calc.savings import SavingsInput, SavingsResult, calculate_savings

__all__ = [
    "DepositInput",
    "DepositResult",
    "EarlyTerminationInput",
    "EarlyTerminationResult",
    "EarlyTerminationTier",
    "Figure",
    "FigureUnit",
    "InterestMethod",
    "LoanInput",
    "LoanResult",
    "PrepaymentFeeInput",
    "PrepaymentFeeResult",
    "RepaymentMethod",
    "RoundingMode",
    "SavingsInput",
    "SavingsResult",
    "TaxType",
    "calculate_deposit",
    "calculate_early_termination",
    "calculate_loan",
    "calculate_prepayment_fee",
    "calculate_savings",
    "round_won",
]
