from decimal import Decimal as D

import pytest
from pydantic import ValidationError

from app.calc import LoanInput, RepaymentMethod, RoundingMode, calculate_loan
from app.calc.common import MAX_AMOUNT, MAX_TERM_MONTHS
from app.calc.loan import equal_payment_amount


def _assert_invariants(r):
    p = r.inputs.principal
    assert len(r.schedule) == r.inputs.months
    assert sum(row.principal for row in r.schedule) == p
    assert r.schedule[-1].balance == 0
    assert all(row.balance >= 0 and row.principal >= 0 for row in r.schedule)
    assert all(row.payment == row.principal + row.interest for row in r.schedule)
    assert r.total_payment == p + r.total_interest


def test_equal_payment_10m_12pct_12m():
    r = calculate_loan(LoanInput(principal=D(10_000_000), annual_rate=D("12"), months=12))
    assert r.formula_id == "loan.equal_payment.v1"
    # 정확값 888,487.88 → 절사
    assert r.first_payment == D("888487")
    assert r.schedule[0].interest == D("100000")
    assert r.schedule[0].principal == D("788487")
    assert r.last_payment == D("888494")  # 반올림 잔차를 마지막 회차가 흡수
    assert r.total_interest == D("661851")
    _assert_invariants(r)


def test_equal_payment_zero_rate():
    r = calculate_loan(LoanInput(principal=D(1_000_000), annual_rate=D(0), months=3))
    assert [row.payment for row in r.schedule] == [D("333333"), D("333333"), D("333334")]
    assert r.total_interest == 0
    _assert_invariants(r)


def test_equal_principal():
    r = calculate_loan(
        LoanInput(
            principal=D(12_000_000),
            annual_rate=D("6"),
            months=12,
            method=RepaymentMethod.EQUAL_PRINCIPAL,
        )
    )
    assert r.formula_id == "loan.equal_principal.v1"
    assert r.first_payment == D("1060000")
    assert r.last_payment == D("1005000")
    assert r.total_interest == D("390000")  # 0.5% × 1,000,000 × 78
    _assert_invariants(r)


def test_bullet():
    r = calculate_loan(
        LoanInput(
            principal=D(10_000_000), annual_rate=D("6"), months=12, method=RepaymentMethod.BULLET
        )
    )
    assert r.formula_id == "loan.bullet.v1"
    assert all(row.payment == D("50000") for row in r.schedule[:-1])
    assert r.last_payment == D("10050000")
    assert r.total_interest == D("600000")
    _assert_invariants(r)


@pytest.mark.parametrize("method", list(RepaymentMethod))
def test_single_month(method):
    r = calculate_loan(
        LoanInput(principal=D(1_000_000), annual_rate=D("12"), months=1, method=method)
    )
    assert r.schedule[0].payment == D("1010000")
    _assert_invariants(r)


@pytest.mark.parametrize("method", list(RepaymentMethod))
def test_zero_principal(method):
    r = calculate_loan(LoanInput(principal=D(0), annual_rate=D("12"), months=6, method=method))
    assert r.total_payment == 0
    _assert_invariants(r)


@pytest.mark.parametrize("method", [RepaymentMethod.EQUAL_PAYMENT, RepaymentMethod.EQUAL_PRINCIPAL])
def test_ceiling_rounding_never_overpays(method):
    # 6원 / 10개월 = 0.6 → 절상 시 회차당 1원. 잔액을 넘겨 상환하지 않아야 한다.
    r = calculate_loan(
        LoanInput(
            principal=D(6),
            annual_rate=D(0),
            months=10,
            method=method,
            rounding=RoundingMode.CEILING,
        )
    )
    assert [row.principal for row in r.schedule] == [D(1)] * 6 + [D(0)] * 4
    _assert_invariants(r)


@pytest.mark.parametrize("method", list(RepaymentMethod))
@pytest.mark.parametrize("rounding", list(RoundingMode))
@pytest.mark.parametrize(
    ("principal", "rate", "months"),
    [(D(1), D("19.9"), 12), (D(3_000_000), D("7.9"), 36), (D(49_999_999), D("15.9"), 60)],
)
def test_schedule_invariants(method, rounding, principal, rate, months):
    r = calculate_loan(
        LoanInput(
            principal=principal, annual_rate=rate, months=months, method=method, rounding=rounding
        )
    )
    _assert_invariants(r)


@pytest.mark.parametrize("method", list(RepaymentMethod))
def test_max_bounds(method):
    r = calculate_loan(
        LoanInput(principal=MAX_AMOUNT, annual_rate=D("5"), months=MAX_TERM_MONTHS, method=method)
    )
    _assert_invariants(r)


def test_equal_payment_amount_helper():
    assert equal_payment_amount(D(1_200_000), D(0), 12, RoundingMode.TRUNCATE) == D("100000")


def test_figures():
    r = calculate_loan(LoanInput(principal=D(10_000_000), annual_rate=D("12"), months=12))
    figs = {f.name: f.value for f in r.figures}
    assert figs["first_payment"] == D("888487")
    assert figs["total_interest"] == D("661851")


@pytest.mark.parametrize(
    "bad",
    [
        {"principal": -1, "annual_rate": 5, "months": 12},
        {"principal": "1.5", "annual_rate": 5, "months": 12},
        {"principal": 100, "annual_rate": 5, "months": 0},
        {"principal": 100, "annual_rate": 5, "months": 601},
        {"principal": 100, "annual_rate": 5, "months": 12, "method": "BALLOON"},
    ],
)
def test_invalid_input(bad):
    with pytest.raises(ValidationError):
        LoanInput.model_validate(bad)
