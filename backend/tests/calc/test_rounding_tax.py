from decimal import Decimal as D

import pytest

from app.calc.common import TaxType
from app.calc.rounding import RoundingMode, round_won
from app.calc.tax import interest_tax


@pytest.mark.parametrize(
    ("amount", "mode", "expected"),
    [
        (D("1.9"), RoundingMode.TRUNCATE, D("1")),
        (D("1.5"), RoundingMode.HALF_UP, D("2")),
        (D("1.4999"), RoundingMode.HALF_UP, D("1")),
        (D("1.0001"), RoundingMode.CEILING, D("2")),
        (D("0"), RoundingMode.TRUNCATE, D("0")),
        (D("0"), RoundingMode.CEILING, D("0")),
        (D("12345"), RoundingMode.CEILING, D("12345")),
    ],
)
def test_round_won(amount, mode, expected):
    assert round_won(amount, mode) == expected


def test_round_won_default_is_truncate():
    assert round_won(D("999.999")) == D("999")


def test_interest_tax_general():
    assert interest_tax(D("330000"), TaxType.GENERAL, D("0.154"), RoundingMode.TRUNCATE) == D(
        "50820"
    )


def test_interest_tax_truncates_fraction():
    # 3803.8 → 3803
    assert interest_tax(D("24700"), TaxType.GENERAL, D("0.154"), RoundingMode.TRUNCATE) == D("3803")


def test_interest_tax_free():
    assert interest_tax(D("330000"), TaxType.TAX_FREE, D("0.154"), RoundingMode.TRUNCATE) == 0


def test_round_won_removes_repeating_decimal_noise():
    # 300,000 × (0.04/12) 를 40자리 정밀도로 계산하면 999.999…9 가 된다. 정확값은 1,000.
    noisy = D("999.9999999999999999999999999999999999999")
    assert round_won(noisy, RoundingMode.TRUNCATE) == D("1000")
    # 보호 자릿수보다 큰 실제 소수는 그대로 절사된다
    assert round_won(D("999.999999"), RoundingMode.TRUNCATE) == D("999")
