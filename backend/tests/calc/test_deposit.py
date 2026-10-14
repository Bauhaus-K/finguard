from decimal import Decimal as D

import pytest
from pydantic import ValidationError

from app.calc import DepositInput, InterestMethod, RoundingMode, TaxType, calculate_deposit
from app.calc.common import MAX_AMOUNT, MAX_TERM_MONTHS, FigureUnit


def test_simple_10m_12m_demo_scenario():
    """데모 시나리오 1: 1,000만 원 12개월 연 3.3% 단리."""
    r = calculate_deposit(DepositInput(principal=D(10_000_000), annual_rate=D("3.3"), months=12))
    assert r.formula_id == "deposit.simple.v1"
    assert r.pre_tax_interest == D("330000")
    assert r.tax == D("50820")
    assert r.after_tax_interest == D("279180")
    assert r.maturity_amount == D("10279180")


def test_monthly_compound():
    r = calculate_deposit(
        DepositInput(
            principal=D(10_000_000),
            annual_rate=D("3.2"),
            months=12,
            method=InterestMethod.MONTHLY_COMPOUND,
        )
    )
    assert r.formula_id == "deposit.monthly_compound.v1"
    # 정확값 324,735.303... (분수 연산으로 별도 검산)
    assert r.pre_tax_interest == D("324735")
    assert r.tax == D("50009")
    assert r.after_tax_interest == D("274726")


def test_compound_one_month_equals_simple():
    kwargs = dict(principal=D(5_000_000), annual_rate=D("4.8"), months=1)
    simple = calculate_deposit(DepositInput(**kwargs))
    compound = calculate_deposit(DepositInput(**kwargs, method=InterestMethod.MONTHLY_COMPOUND))
    assert simple.pre_tax_interest == compound.pre_tax_interest == D("20000")


@pytest.mark.parametrize(
    ("mode", "pre_tax", "tax"),
    [
        # 1,234,567 × 3.3% × 7/12 = 23,765.41475
        (RoundingMode.TRUNCATE, D("23765"), D("3659")),
        (RoundingMode.HALF_UP, D("23765"), D("3660")),
        (RoundingMode.CEILING, D("23766"), D("3660")),
    ],
)
def test_rounding_modes(mode, pre_tax, tax):
    r = calculate_deposit(
        DepositInput(principal=D(1_234_567), annual_rate=D("3.3"), months=7, rounding=mode)
    )
    assert r.pre_tax_interest == pre_tax
    assert r.tax == tax
    assert r.after_tax_interest == pre_tax - tax


def test_tax_free():
    r = calculate_deposit(
        DepositInput(
            principal=D(10_000_000), annual_rate=D("3.3"), months=12, tax_type=TaxType.TAX_FREE
        )
    )
    assert r.tax == 0
    assert r.after_tax_interest == r.pre_tax_interest == D("330000")


def test_custom_tax_rate():
    r = calculate_deposit(
        DepositInput(principal=D(10_000_000), annual_rate=D("3.3"), months=12, tax_rate=D("0.095"))
    )
    assert r.tax == D("31350")


def test_zero_principal():
    r = calculate_deposit(DepositInput(principal=D(0), annual_rate=D("3.3"), months=12))
    assert r.pre_tax_interest == r.tax == r.maturity_amount == 0


def test_zero_rate():
    r = calculate_deposit(DepositInput(principal=D(1_000_000), annual_rate=D(0), months=12))
    assert r.pre_tax_interest == 0
    assert r.maturity_amount == D(1_000_000)


def test_max_bounds_accepted():
    for method in InterestMethod:
        r = calculate_deposit(
            DepositInput(
                principal=MAX_AMOUNT, annual_rate=D("3"), months=MAX_TERM_MONTHS, method=method
            )
        )
        assert r.pre_tax_interest > 0
        assert r.pre_tax_interest == r.pre_tax_interest.to_integral_value()


def test_float_rate_input_is_exact():
    # LLM tool call 은 JSON 숫자로 들어온다
    inp = DepositInput.model_validate({"principal": 10_000_000, "annual_rate": 3.3, "months": 12})
    assert calculate_deposit(inp).pre_tax_interest == D("330000")


def test_figures():
    r = calculate_deposit(DepositInput(principal=D(10_000_000), annual_rate=D("3.3"), months=12))
    figs = {f.name: f for f in r.figures}
    assert figs["after_tax_interest"].value == D("279180")
    assert figs["after_tax_interest"].unit is FigureUnit.KRW
    assert figs["annual_rate"].unit is FigureUnit.PERCENT
    assert figs["months"].value == 12


@pytest.mark.parametrize(
    "bad",
    [
        {"principal": -1, "annual_rate": 3, "months": 12},
        {"principal": "100.5", "annual_rate": 3, "months": 12},
        {"principal": MAX_AMOUNT + 1, "annual_rate": 3, "months": 12},
        {"principal": 100, "annual_rate": -0.1, "months": 12},
        {"principal": 100, "annual_rate": 100.01, "months": 12},
        {"principal": 100, "annual_rate": 3, "months": 0},
        {"principal": 100, "annual_rate": 3, "months": MAX_TERM_MONTHS + 1},
        {"principal": 100, "annual_rate": 3, "months": 12, "tax_rate": 1.5},
        {"principal": 100, "annual_rate": 3, "months": 12, "unknown": 1},
    ],
)
def test_invalid_input(bad):
    with pytest.raises(ValidationError):
        DepositInput.model_validate(bad)
