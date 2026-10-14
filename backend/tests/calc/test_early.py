from decimal import Decimal as D

import pytest
from pydantic import ValidationError

from app.calc import (
    EarlyTerminationInput,
    EarlyTerminationTier,
    PrepaymentFeeInput,
    TaxType,
    calculate_early_termination,
    calculate_prepayment_fee,
)
from app.calc.early import EarlyTerminationKind, select_tier

TIERS = [
    EarlyTerminationTier(min_elapsed_months=6, rate_ratio=D("0.5")),
    EarlyTerminationTier(min_elapsed_months=0, rate_ratio=D("0.1")),
    EarlyTerminationTier(min_elapsed_months=3, rate_ratio=D("0.3")),
]


def _early(**kw):
    base = dict(
        kind=EarlyTerminationKind.DEPOSIT,
        amount=D(10_000_000),
        contracted_rate=D("3.3"),
        term_months=12,
        elapsed_months=6,
        tiers=TIERS,
    )
    base.update(kw)
    return calculate_early_termination(EarlyTerminationInput(**base))


def test_deposit_early_termination():
    r = _early()
    assert r.formula_id == "early_termination.deposit.simple.v1"
    assert r.applied_tier.min_elapsed_months == 6
    assert r.applied_rate == D("1.65")
    # 10,000,000 × 1.65% × 6/12 = 82,500
    assert r.pre_tax_interest == D("82500")
    assert r.tax == D("12705")
    assert r.after_tax_interest == D("69795")
    assert r.payout == D("10069795")


def test_savings_early_termination():
    r = _early(kind=EarlyTerminationKind.SAVINGS, amount=D(100_000), contracted_rate=D("3.8"))
    assert r.formula_id == "early_termination.savings.simple.v1"
    assert r.principal_returned == D(600_000)
    # 100,000 × 1.9%/12 × (6·7/2 = 21) = 3,325
    assert r.pre_tax_interest == D("3325")
    assert r.tax == D("512")
    assert r.payout == D("602813")


def test_elapsed_zero_gives_no_interest():
    r = _early(elapsed_months=0)
    assert r.applied_tier.rate_ratio == D("0.1")
    assert r.pre_tax_interest == 0
    assert r.payout == D(10_000_000)


def test_last_month_before_maturity():
    r = _early(elapsed_months=11)
    assert r.applied_tier.min_elapsed_months == 6


def test_tax_free():
    r = _early(tax_type=TaxType.TAX_FREE)
    assert r.tax == 0
    assert r.after_tax_interest == D("82500")


@pytest.mark.parametrize(("elapsed", "expected"), [(0, 0), (2, 0), (3, 3), (5, 3), (6, 6)])
def test_select_tier_boundaries(elapsed, expected):
    assert select_tier(TIERS, elapsed).min_elapsed_months == expected


def test_figures():
    names = {f.name for f in _early().figures}
    assert {"applied_rate", "payout", "elapsed_months"} <= names


@pytest.mark.parametrize(
    "override",
    [
        {"elapsed_months": 12},  # 만기 = 중도해지 아님
        {"elapsed_months": 13},
        {"tiers": []},
        {"tiers": [EarlyTerminationTier(min_elapsed_months=1, rate_ratio=D("0.5"))]},
        {"amount": D("-1")},
    ],
)
def test_early_invalid(override):
    with pytest.raises(ValidationError):
        _early(**override)


def test_tier_ratio_bounds():
    with pytest.raises(ValidationError):
        EarlyTerminationTier(min_elapsed_months=0, rate_ratio=D("1.1"))


# ---- 중도상환수수료 ----


def _fee(**kw):
    base = dict(prepay_amount=D(10_000_000), fee_rate=D("1.2"), loan_days=1095, elapsed_days=365)
    base.update(kw)
    return calculate_prepayment_fee(PrepaymentFeeInput(**base))


def test_prepayment_fee():
    r = _fee()
    assert r.remaining_days == 730
    assert not r.exempted
    # 10,000,000 × 1.2% × 730/1095 = 80,000
    assert r.fee == D("80000")
    assert {f.name for f in r.figures} == {"prepay_amount", "fee_rate", "remaining_days", "fee"}


def test_prepayment_fee_truncates():
    # 10,000,000 × 1.2% × 325/1825 = 21,369.86
    r = _fee(loan_days=1825, elapsed_days=1500, exemption_days=None)
    assert r.fee == D("21369")


def test_prepayment_exempt_after_3_years():
    r = _fee(loan_days=1825, elapsed_days=1095)
    assert r.exempted
    assert r.fee == 0


def test_prepayment_one_day_before_exemption():
    r = _fee(loan_days=1825, elapsed_days=1094)
    assert not r.exempted
    assert r.fee > 0


def test_prepayment_at_maturity_without_exemption():
    r = _fee(elapsed_days=1095, exemption_days=None)
    assert r.fee == 0
    assert not r.exempted


def test_prepayment_zero_rate_and_amount():
    assert _fee(fee_rate=D(0)).fee == 0
    assert _fee(prepay_amount=D(0)).fee == 0


@pytest.mark.parametrize(
    "override",
    [
        {"elapsed_days": 1096},
        {"loan_days": 0},
        {"prepay_amount": D("0.5")},
        {"fee_rate": D("-1")},
        {"exemption_days": -1},
    ],
)
def test_prepayment_invalid(override):
    with pytest.raises(ValidationError):
        _fee(**override)
