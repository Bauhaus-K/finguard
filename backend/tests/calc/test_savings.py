from decimal import Decimal as D

import pytest
from pydantic import ValidationError

from app.calc import InterestMethod, SavingsInput, TaxType, calculate_savings
from app.calc.common import MAX_AMOUNT, MAX_TERM_MONTHS


def test_simple_100k_12m():
    # 100,000 × 3.8%/12 × (12·13/2 = 78) = 24,700
    r = calculate_savings(SavingsInput(monthly_payment=D(100_000), annual_rate=D("3.8"), months=12))
    assert r.formula_id == "savings.simple.v1"
    assert r.total_payment == D(1_200_000)
    assert r.pre_tax_interest == D("24700")
    assert r.tax == D("3803")
    assert r.after_tax_interest == D("20897")
    assert r.maturity_amount == D("1220897")


def test_monthly_compound():
    r = calculate_savings(
        SavingsInput(
            monthly_payment=D(100_000),
            annual_rate=D("3.8"),
            months=12,
            method=InterestMethod.MONTHLY_COMPOUND,
        )
    )
    assert r.formula_id == "savings.monthly_compound.v1"
    # 정확값 24,989.077... (분수 연산으로 별도 검산)
    assert r.pre_tax_interest == D("24989")
    assert r.tax == D("3848")


def test_one_month_simple_equals_compound():
    kw = dict(monthly_payment=D(300_000), annual_rate=D("4.0"), months=1)
    a = calculate_savings(SavingsInput(**kw))
    b = calculate_savings(SavingsInput(**kw, method=InterestMethod.MONTHLY_COMPOUND))
    assert a.pre_tax_interest == b.pre_tax_interest == D("1000")


def test_tax_free():
    r = calculate_savings(
        SavingsInput(
            monthly_payment=D(100_000),
            annual_rate=D("3.8"),
            months=12,
            tax_type=TaxType.TAX_FREE,
        )
    )
    assert r.tax == 0
    assert r.maturity_amount == D("1224700")


def test_zero_payment_and_zero_rate():
    assert (
        calculate_savings(
            SavingsInput(monthly_payment=D(0), annual_rate=D("3.8"), months=12)
        ).maturity_amount
        == 0
    )
    r = calculate_savings(SavingsInput(monthly_payment=D(10_000), annual_rate=D(0), months=24))
    assert r.pre_tax_interest == 0
    assert r.maturity_amount == D(240_000)


def test_max_bounds_accepted():
    for method in InterestMethod:
        r = calculate_savings(
            SavingsInput(
                monthly_payment=MAX_AMOUNT,
                annual_rate=D("2"),
                months=MAX_TERM_MONTHS,
                method=method,
            )
        )
        assert r.total_payment == MAX_AMOUNT * MAX_TERM_MONTHS


def test_figures_have_total_payment():
    r = calculate_savings(SavingsInput(monthly_payment=D(100_000), annual_rate=D("3.8"), months=12))
    assert {f.name for f in r.figures} >= {"total_payment", "maturity_amount", "tax"}


@pytest.mark.parametrize(
    "bad",
    [
        {"monthly_payment": -1, "annual_rate": 3, "months": 12},
        {"monthly_payment": "0.1", "annual_rate": 3, "months": 12},
        {"monthly_payment": 1000, "annual_rate": 3, "months": 0},
        {"monthly_payment": 1000, "annual_rate": 101, "months": 12},
    ],
)
def test_invalid_input(bad):
    with pytest.raises(ValidationError):
        SavingsInput.model_validate(bad)
