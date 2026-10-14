import json
from decimal import Decimal as D

import pytest

from app.agent.tools import TOOL_SPECS, execute_tool
from app.calc.common import FigureUnit
from app.compliance.provenance import figure_keys


def run(ctx, name, **args):
    return execute_tool(ctx, name, args)


DEP = dict(include_preferential=False, tax_type="GENERAL", early_termination_after_months=None)


def test_tool_schemas_are_strict():
    for spec in TOOL_SPECS:
        schema = spec.input_schema
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) == set(schema["properties"]), spec.name


def test_search_products_by_type(tool_ctx):
    out = run(tool_ctx, "search_products", product_type="DEPOSIT", keyword=None)
    codes = [p["product_code"] for p in out.payload["products"]]
    assert codes == ["HB-DEP-001", "HB-DEP-002", "HB-DEP-003"]
    assert (FigureUnit.PERCENT, D("3.3")) in figure_keys(out.figures)
    assert {c["product_code"] for c in out.citations} == set(codes)


def test_search_products_keyword(tool_ctx):
    out = run(tool_ctx, "search_products", product_type=None, keyword="청년")
    assert [p["product_code"] for p in out.payload["products"]] == ["HB-SAV-002"]
    # 일치하는 상품이 없으면 전체 목록
    out = run(tool_ctx, "search_products", product_type=None, keyword="없는상품")
    assert len(out.payload["products"]) == 8


def test_get_product_detail_loan(tool_ctx):
    out = run(tool_ctx, "get_product_detail", product_code="HB-LOAN-001")
    p = out.payload
    assert p["rate_range_percent"] == "6.90~15.90"
    assert p["prepayment_fee_rate_percent"] == "1.20"
    assert any("심사" in d for d in p["required_disclosures"])
    keys = figure_keys(out.figures)
    assert (FigureUnit.PERCENT, D("15.9")) in keys
    assert (FigureUnit.PERCENT, D("6.6")) in keys  # 우대 감면 후 최저
    assert (FigureUnit.MONTHS, D(36)) in keys  # 면제 3년
    assert (FigureUnit.DAYS, D(1095)) in keys


def test_get_product_detail_deposit_preferential(tool_ctx):
    out = run(tool_ctx, "get_product_detail", product_code="HB-DEP-003")
    assert out.payload["max_rate_with_preferential_percent"] == "3.70"
    keys = figure_keys(out.figures)
    assert (FigureUnit.PERCENT, D("3.7")) in keys
    assert (FigureUnit.PERCENT, D("1.75")) in keys  # 6개월 경과 중도해지이율 3.50 × 50%
    assert (FigureUnit.PERCENT, D(50)) in keys
    assert (FigureUnit.KRW, D(100_000_000)) in keys  # 예금자보호 고지 1억원


def test_get_product_detail_unknown(tool_ctx):
    out = run(tool_ctx, "get_product_detail", product_code="HB-XXX-999")
    assert out.is_error
    assert "찾을 수 없습니다" in out.payload["error"]


def test_search_terms(tool_ctx):
    out = run(tool_ctx, "search_terms", query="중도상환수수료", product_code="HB-LOAN-001")
    assert out.payload["results"][0]["chunk_id"] == "HB-LOAN-001#제7조"
    assert out.citations[0]["type"] == "terms"
    assert (FigureUnit.PERCENT, D("1.2")) in figure_keys(out.figures)


def test_search_terms_no_result(tool_ctx):
    out = run(tool_ctx, "search_terms", query="zzzz", product_code=None)
    assert out.payload["results"] == "검색 결과 없음"


def test_calculate_deposit(tool_ctx):
    out = run(
        tool_ctx,
        "calculate_deposit",
        product_code="HB-DEP-001",
        principal=10_000_000,
        months=12,
        **DEP,
    )
    p = out.payload
    assert not out.is_error
    assert p["after_tax_interest_krw"] == "279180"
    assert p["tax_krw"] == "50820"
    assert p["tax_rate_percent"] == "15.400"
    keys = figure_keys(out.figures)
    assert (FigureUnit.KRW, D(279180)) in keys
    assert (FigureUnit.PERCENT, D("15.4")) in keys
    assert out.citations == [
        {"type": "product", "product_code": "HB-DEP-001", "name": "한빛 정기예금(가상)"}
    ]


def test_calculate_deposit_preferential_and_tax_free(tool_ctx):
    out = run(
        tool_ctx,
        "calculate_deposit",
        product_code="HB-DEP-003",
        principal=10_000_000,
        months=12,
        include_preferential=True,
        tax_type="TAX_FREE",
        early_termination_after_months=None,
    )
    assert out.payload["applied_annual_rate_percent"] == "3.70"
    assert out.payload["after_tax_interest_krw"] == "370000"
    assert out.payload["tax_rate_percent"] == "0"


def test_calculate_deposit_compound_product(tool_ctx):
    out = run(
        tool_ctx,
        "calculate_deposit",
        product_code="HB-DEP-002",
        principal=10_000_000,
        months=12,
        **DEP,
    )
    assert out.payload["pre_tax_interest_krw"] == "324735"
    assert out.payload["formula_id"] == "deposit.monthly_compound.v1"


def test_calculate_deposit_early_termination(tool_ctx):
    out = run(
        tool_ctx,
        "calculate_deposit",
        product_code="HB-DEP-001",
        principal=10_000_000,
        months=12,
        include_preferential=False,
        tax_type="GENERAL",
        early_termination_after_months=6,
    )
    early = out.payload["early_termination"]
    assert early["applied_rate_percent"] == "1.650"
    assert early["after_tax_interest_krw"] == "69795"
    assert early["payout_krw"] == "10069795"
    assert (FigureUnit.PERCENT, D(50)) in figure_keys(out.figures)


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (dict(product_code="HB-SAV-001", principal=10_000_000, months=12), "SAVINGS"),
        (dict(product_code="HB-DEP-003", principal=10_000_000, months=24), "허용 범위"),
        (dict(product_code="HB-DEP-003", principal=60_000_000, months=12), "허용 범위"),
    ],
)
def test_calculate_deposit_errors(tool_ctx, args, message):
    out = execute_tool(tool_ctx, "calculate_deposit", {**DEP, **args})
    assert out.is_error
    assert message in out.payload["error"]


def test_calculate_deposit_early_termination_at_maturity_is_error(tool_ctx):
    out = execute_tool(
        tool_ctx,
        "calculate_deposit",
        {
            **DEP,
            "product_code": "HB-DEP-001",
            "principal": 10_000_000,
            "months": 12,
            "early_termination_after_months": 12,
        },
    )
    assert out.is_error
    assert "입력값 오류" in out.payload["error"]


def test_calculate_savings(tool_ctx):
    out = run(
        tool_ctx,
        "calculate_savings",
        product_code="HB-SAV-001",
        monthly_payment=100_000,
        months=12,
        **DEP,
    )
    p = out.payload
    assert p["total_payment_krw"] == "1200000"
    assert p["pre_tax_interest_krw"] == "24700"
    assert p["maturity_amount_krw"] == "1220897"


def test_calculate_savings_preferential_early(tool_ctx):
    out = run(
        tool_ctx,
        "calculate_savings",
        product_code="HB-SAV-002",
        monthly_payment=500_000,
        months=12,
        include_preferential=True,
        tax_type="GENERAL",
        early_termination_after_months=6,
    )
    assert out.payload["applied_annual_rate_percent"] == "5.50"
    assert out.payload["pre_tax_interest_krw"] == "178750"
    # 중도해지는 우대 제외 기본금리 4.50% × 50% = 2.25%
    assert out.payload["early_termination"]["applied_rate_percent"] == "2.250"


def test_calculate_savings_wrong_range(tool_ctx):
    out = run(
        tool_ctx,
        "calculate_savings",
        product_code="HB-SAV-002",
        monthly_payment=600_000,
        months=12,
        **DEP,
    )
    assert out.is_error


LOAN = dict(prepayment_after_days=None, prepayment_amount=None)


def test_calculate_loan(tool_ctx):
    out = run(
        tool_ctx,
        "calculate_loan",
        product_code="HB-LOAN-001",
        principal=10_000_000,
        months=12,
        assumed_annual_rate=10,
        repayment_method="EQUAL_PAYMENT",
        **LOAN,
    )
    p = out.payload
    assert p["first_payment_krw"] == "879158"
    assert p["last_payment_krw"] == "879162"
    assert p["total_interest_krw"] == "549900"
    assert "심사" in p["rate_note"]
    assert [r["no"] for r in p["schedule_preview"]] == [1, 2, 3, 12]
    assert (FigureUnit.KRW, D(879158)) in figure_keys(out.figures)


def test_calculate_loan_float_rate(tool_ctx):
    out = run(
        tool_ctx,
        "calculate_loan",
        product_code="HB-POL-001",
        principal=10_000_000,
        months=60,
        assumed_annual_rate=8.5,
        repayment_method="EQUAL_PAYMENT",
        **LOAN,
    )
    assert out.payload["first_payment_krw"] == "205165"
    assert out.payload["assumed_annual_rate_percent"] == "8.5"


def test_calculate_loan_prepayment_fee(tool_ctx):
    out = run(
        tool_ctx,
        "calculate_loan",
        product_code="HB-LOAN-001",
        principal=10_000_000,
        months=36,
        assumed_annual_rate=10,
        repayment_method="EQUAL_PAYMENT",
        prepayment_after_days=365,
        prepayment_amount=10_000_000,
    )
    pre = out.payload["prepayment"]
    assert pre["loan_days"] == 1095
    assert pre["remaining_days"] == 730
    assert pre["fee_krw"] == "80000"
    assert not pre["exempted"]


def test_calculate_loan_prepayment_exempt_and_no_fee_product(tool_ctx):
    out = run(
        tool_ctx,
        "calculate_loan",
        product_code="HB-LOAN-001",
        principal=10_000_000,
        months=60,
        assumed_annual_rate=10,
        repayment_method="EQUAL_PAYMENT",
        prepayment_after_days=1095,
        prepayment_amount=5_000_000,
    )
    assert out.payload["prepayment"]["exempted"] is True
    out = run(
        tool_ctx,
        "calculate_loan",
        product_code="HB-POL-001",
        principal=10_000_000,
        months=60,
        assumed_annual_rate=8.5,
        repayment_method="EQUAL_PRINCIPAL",
        prepayment_after_days=100,
        prepayment_amount=5_000_000,
    )
    assert out.payload["prepayment"]["fee_krw"] == "0"


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        (dict(assumed_annual_rate=6.5), "금리 범위"),
        (dict(assumed_annual_rate=16), "금리 범위"),
        (
            dict(
                repayment_method="BULLET",
                product_code="HB-POL-001",
                months=36,
                assumed_annual_rate=8,
            ),
            "상환 방법",
        ),
        (dict(prepayment_after_days=10), "모두 필요"),
        (dict(product_code="HB-DEP-001"), "DEPOSIT"),
        (dict(principal=100_000_000), "허용 범위"),
    ],
)
def test_calculate_loan_errors(tool_ctx, overrides, message):
    args = dict(
        product_code="HB-LOAN-001",
        principal=10_000_000,
        months=12,
        assumed_annual_rate=10,
        repayment_method="EQUAL_PAYMENT",
        **LOAN,
    )
    out = execute_tool(tool_ctx, "calculate_loan", {**args, **overrides})
    assert out.is_error
    assert message in out.payload["error"]


def test_record_suitability(tool_ctx, conversation):
    out = run(
        tool_ctx,
        "record_suitability_check",
        annual_income=36_000_000,
        existing_debt=5_000_000,
        employment_type="EMPLOYEE",
        loan_purpose="생활비",
        customer_declined=False,
    )
    assert out.payload["recorded"] is True
    assert "심사" in out.payload["note"]
    assert conversation.suitability["annual_income"] == 36_000_000
    assert (FigureUnit.KRW, D(36_000_000)) in figure_keys(out.figures)


def test_record_suitability_declined(tool_ctx, conversation):
    run(
        tool_ctx,
        "record_suitability_check",
        annual_income=None,
        existing_debt=None,
        employment_type=None,
        loan_purpose=None,
        customer_declined=True,
    )
    assert conversation.suitability["customer_declined"] is True


def test_escalate(tool_ctx):
    out = run(tool_ctx, "escalate_to_human", category="OUT_OF_SCOPE", summary="주식 추천 요청")
    assert out.payload == {"escalated": True, "category": "OUT_OF_SCOPE"}


def test_unknown_tool_and_missing_args(tool_ctx):
    assert execute_tool(tool_ctx, "rm_rf", {}).is_error
    out = execute_tool(tool_ctx, "calculate_deposit", {"product_code": "HB-DEP-001"})
    assert out.is_error
    assert "KeyError" in out.payload["error"]


def test_llm_content_is_json(tool_ctx):
    out = run(tool_ctx, "get_product_detail", product_code="HB-DEP-001")
    assert json.loads(out.to_llm_content())["product_code"] == "HB-DEP-001"
