"""에이전트 도구 정의와 실행기.

원칙
- 상품 정보는 DB(카탈로그)에서만, 수치는 계산 엔진에서만 나온다.
- 모든 도구는 결과 페이로드와 함께 '출처 수치(figures)' 와 '인용(citations)' 을 반환한다.
  게이트웨이 수치 검증은 이 figures 를 같은 요청 안의 유일한 출처로 사용한다.
- 입력 오류는 예외 대신 is_error 결과로 돌려 LLM 이 고쳐서 다시 호출하게 한다.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.agent.state import ConversationState
from app.calc import (
    DepositInput,
    EarlyTerminationInput,
    EarlyTerminationTier,
    LoanInput,
    PrepaymentFeeInput,
    SavingsInput,
    calculate_deposit,
    calculate_early_termination,
    calculate_loan,
    calculate_prepayment_fee,
    calculate_savings,
)
from app.calc.common import Figure, FigureUnit, InterestMethod, TaxType, krw, months, pct
from app.calc.early import EarlyTerminationKind
from app.compliance.numbers import extract_numbers
from app.config import Settings
from app.db.models import Product, ProductType
from app.llm.base import ToolSpec
from app.rag.retriever import Retriever

ESCALATE_TOOL = "escalate_to_human"
LOAN_TYPES = (ProductType.CREDIT_LOAN, ProductType.POLICY_LOAN)
SCHEDULE_PREVIEW_ROWS = 3


class ToolInputError(Exception):
    """LLM 이 고쳐서 다시 호출할 수 있는 입력 오류."""


@dataclass
class ToolContext:
    session: Session
    tenant_id: str
    settings: Settings
    retriever: Retriever
    conversation: ConversationState


@dataclass
class ToolOutput:
    payload: dict[str, Any]
    figures: list[Figure] = field(default_factory=list)
    citations: list[dict[str, str]] = field(default_factory=list)
    is_error: bool = False

    def to_llm_content(self) -> str:
        return json.dumps(self.payload, ensure_ascii=False, default=str)


# --------------------------------------------------------------------------- 스키마


def _nullable(schema: dict[str, Any]) -> dict[str, Any]:
    t = schema["type"]
    return {**schema, "type": [t, "null"]} if isinstance(t, str) else schema


def _obj(properties: dict[str, Any]) -> dict[str, Any]:
    # strict tool use: 모든 필드 required + additionalProperties false. 선택 필드는 null 허용.
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


_PRODUCT_CODE = {"type": "string", "description": "상품코드 (예: HB-DEP-001)"}
_TAX_TYPE = {
    "type": "string",
    "enum": [t.value for t in TaxType],
    "description": "GENERAL=일반과세(15.4%), TAX_FREE=비과세. 고객이 비과세 대상이라고 밝히지 않았으면 GENERAL",
}
_INCLUDE_PREF = {
    "type": "boolean",
    "description": "true 면 상품의 모든 우대금리 조건을 충족했다고 가정해 최고 금리로 계산",
}
_EARLY = _nullable(
    {
        "type": "integer",
        "description": "중도해지 예상 이자를 함께 계산할 경과 개월 수. 필요 없으면 null",
    }
)

TOOL_SPECS: list[ToolSpec] = [
    ToolSpec(
        name="search_products",
        description=(
            "한빛저축은행(가상) 상품 목록을 조회한다. 상품 유형이나 키워드로 거를 수 있다. "
            "상품을 안내·비교하기 전에 반드시 호출한다."
        ),
        input_schema=_obj(
            {
                "product_type": _nullable(
                    {
                        "type": "string",
                        "enum": [t.value for t in ProductType],
                        "description": "DEPOSIT=정기예금, SAVINGS=정기적금, CREDIT_LOAN=신용대출, POLICY_LOAN=서민금융대출",
                    }
                ),
                "keyword": _nullable({"type": "string", "description": "상품명·설명 검색어"}),
            }
        ),
    ),
    ToolSpec(
        name="get_product_detail",
        description="상품 상세(금리, 우대조건, 기간·금액 범위, 중도해지/중도상환 규칙, 필수 고지 문구)를 조회한다.",
        input_schema=_obj({"product_code": _PRODUCT_CODE}),
    ),
    ToolSpec(
        name="search_terms",
        description="상품 약관·상품설명서에서 관련 조항과 FAQ 를 검색한다. 약관 내용을 설명할 때 근거로 사용한다.",
        input_schema=_obj(
            {
                "query": {"type": "string", "description": "검색 질의 (한국어)"},
                "product_code": _nullable(
                    {**_PRODUCT_CODE, "description": "특정 상품으로 한정할 때"}
                ),
            }
        ),
    ),
    ToolSpec(
        name="calculate_deposit",
        description="정기예금 만기 이자(세전·세후)를 상품 금리로 계산한다. 선택적으로 중도해지 시 이자도 계산한다.",
        input_schema=_obj(
            {
                "product_code": _PRODUCT_CODE,
                "principal": {"type": "integer", "description": "예치 원금(원)"},
                "months": {"type": "integer", "description": "예치 기간(개월)"},
                "include_preferential": _INCLUDE_PREF,
                "tax_type": _TAX_TYPE,
                "early_termination_after_months": _EARLY,
            }
        ),
    ),
    ToolSpec(
        name="calculate_savings",
        description="정기적금 만기 수령액(세전·세후 이자)을 상품 금리로 계산한다. 선택적으로 중도해지 시 이자도 계산한다.",
        input_schema=_obj(
            {
                "product_code": _PRODUCT_CODE,
                "monthly_payment": {"type": "integer", "description": "월 납입액(원)"},
                "months": {"type": "integer", "description": "적립 기간(개월)"},
                "include_preferential": _INCLUDE_PREF,
                "tax_type": _TAX_TYPE,
                "early_termination_after_months": _EARLY,
            }
        ),
    ),
    ToolSpec(
        name="calculate_loan",
        description=(
            "대출 예상 상환액을 계산한다. 대출 금리는 심사 후 결정되므로 반드시 상품 금리 범위 안의 "
            "'가정 금리'로 계산하고, 답변에 가정 금리임을 밝힌다. 선택적으로 중도상환수수료도 계산한다."
        ),
        input_schema=_obj(
            {
                "product_code": _PRODUCT_CODE,
                "principal": {"type": "integer", "description": "대출 원금(원)"},
                "months": {"type": "integer", "description": "대출 기간(개월)"},
                "assumed_annual_rate": {
                    "type": "number",
                    "description": "가정 연 금리(%). 상품 금리 범위 안이어야 한다",
                },
                "repayment_method": {
                    "type": "string",
                    "enum": ["EQUAL_PAYMENT", "EQUAL_PRINCIPAL", "BULLET"],
                    "description": "EQUAL_PAYMENT=원리금균등, EQUAL_PRINCIPAL=원금균등, BULLET=만기일시",
                },
                "prepayment_after_days": _nullable(
                    {
                        "type": "integer",
                        "description": "중도상환 시점(대출 실행 후 경과일수). 없으면 null",
                    }
                ),
                "prepayment_amount": _nullable(
                    {"type": "integer", "description": "중도상환 원금(원). 없으면 null"}
                ),
            }
        ),
    ),
    ToolSpec(
        name="record_suitability_check",
        description=(
            "대출 상품을 안내·권유하기 전에 고객에게 확인한 적합성 정보(소득, 기존 부채, 고용 형태, 자금 용도)를 "
            "기록한다. 고객이 답한 내용만 기록하며, 기록은 심사·승인 판단이 아니다. 고객이 답변을 거부하면 "
            "customer_declined=true 로 기록한다."
        ),
        input_schema=_obj(
            {
                "annual_income": _nullable({"type": "integer", "description": "연소득(원)"}),
                "existing_debt": _nullable(
                    {"type": "integer", "description": "기존 부채 총액(원)"}
                ),
                "employment_type": _nullable(
                    {
                        "type": "string",
                        "enum": ["EMPLOYEE", "SELF_EMPLOYED", "FREELANCER", "UNEMPLOYED", "OTHER"],
                    }
                ),
                "loan_purpose": _nullable({"type": "string", "description": "자금 용도"}),
                "customer_declined": {"type": "boolean"},
            }
        ),
    ),
    ToolSpec(
        name=ESCALATE_TOOL,
        description=(
            "상담원에게 이관한다. 업무 범위 밖 요청(투자 종목 추천, 세무 신고 대리, 법률 판단 등), "
            "고객의 상담원 연결 요청, 민원, 판단이 불확실한 경우에 호출한다. 호출하면 대화가 상담원에게 넘어간다."
        ),
        input_schema=_obj(
            {
                "category": {
                    "type": "string",
                    "enum": [
                        "OUT_OF_SCOPE",
                        "CUSTOMER_REQUEST",
                        "COMPLAINT",
                        "SENSITIVE",
                        "UNCERTAIN",
                        "OTHER",
                    ],
                },
                "summary": {"type": "string", "description": "상담원에게 전달할 한 줄 요약"},
            }
        ),
    ),
]

# --------------------------------------------------------------------------- 헬퍼


def _load_product(ctx: ToolContext, code: str) -> Product:
    product = ctx.session.scalar(
        select(Product)
        .where(Product.tenant_id == ctx.tenant_id, Product.code == code)
        .options(selectinload(Product.preferential_conditions))
    )
    if product is None:
        raise ToolInputError(f"상품코드 {code} 를 찾을 수 없습니다. search_products 로 확인하세요.")
    return product


def _require_type(product: Product, *types: ProductType) -> None:
    if product.product_type not in types:
        allowed = ", ".join(t.value for t in types)
        raise ToolInputError(
            f"{product.code} 는 {product.product_type.value} 상품입니다. 이 도구는 {allowed} 상품용입니다."
        )


def _check_range(label: str, value: int, lo: int, hi: int, unit: str) -> None:
    if not lo <= value <= hi:
        raise ToolInputError(
            f"{label} {value:,}{unit} 는 상품 허용 범위({lo:,}~{hi:,}{unit})를 벗어납니다."
        )


def _product_figures(p: Product) -> list[Figure]:
    figs = [
        pct("base_rate", p.base_rate),
        months("min_term_months", p.min_term_months),
        months("max_term_months", p.max_term_months),
        krw("min_amount", Decimal(p.min_amount)),
        krw("max_amount", Decimal(p.max_amount)),
    ]
    if p.max_rate is not None:
        figs.append(pct("max_rate", p.max_rate))
    prefs = [c.rate for c in p.preferential_conditions]
    for i, rate in enumerate(prefs):
        figs.append(pct(f"preferential_rate_{i}", rate))
    if prefs:
        total = sum(prefs, Decimal(0))
        figs.append(pct("preferential_rate_total", total))
        if p.product_type not in LOAN_TYPES:
            figs.append(pct("max_rate_with_preferential", p.base_rate + total))
        else:
            figs.append(pct("min_rate_with_preferential", p.base_rate - total))
    for t in p.early_termination_tiers:
        ratio = Decimal(t["rate_ratio"])
        figs.append(pct("early_termination_ratio", ratio * 100))
        figs.append(pct("early_termination_rate", p.base_rate * ratio))
        figs.append(months("early_termination_tier_months", t["min_elapsed_months"]))
    if p.prepayment_fee_rate is not None:
        figs.append(pct("prepayment_fee_rate", p.prepayment_fee_rate))
    if p.prepayment_exemption_days:
        days = p.prepayment_exemption_days
        figs.append(
            Figure(name="prepayment_exemption_days", value=Decimal(days), unit=FigureUnit.DAYS)
        )
        if days % 365 == 0:
            figs.append(months("prepayment_exemption_months", days // 365 * 12))
    for text in p.required_disclosures:
        figs.extend(_text_figures("disclosure", text))
    return figs


def _text_figures(name: str, text: str) -> list[Figure]:
    return [Figure(name=name, value=n.value, unit=n.unit) for n in extract_numbers(text)]


def _product_summary(p: Product) -> dict[str, Any]:
    out: dict[str, Any] = {
        "product_code": p.code,
        "name": p.name,
        "product_type": p.product_type.value,
        "summary": p.summary,
        "base_rate_percent": str(p.base_rate),
        "term_months": f"{p.min_term_months}~{p.max_term_months}",
        "amount_range_krw": f"{p.min_amount:,}~{p.max_amount:,}",
    }
    if p.max_rate is not None:
        out["rate_range_percent"] = f"{p.base_rate}~{p.max_rate}"
        out["rate_note"] = "실제 금리는 심사 결과에 따라 결정"
    if p.product_type is ProductType.SAVINGS:
        out["amount_note"] = "금액 범위는 월 납입액 기준"
    return out


def _pref_rate(p: Product, include: bool) -> Decimal:
    return sum((c.rate for c in p.preferential_conditions), Decimal(0)) if include else Decimal(0)


def _early_termination(
    ctx: ToolContext,
    p: Product,
    kind: EarlyTerminationKind,
    amount: int,
    rate: Decimal,
    term: int,
    elapsed: int,
    tax_type: str,
) -> tuple[dict[str, Any], list[Figure]]:
    # 중도해지이율은 우대금리를 제외한 기본(약정)금리 기준
    result = calculate_early_termination(
        EarlyTerminationInput(
            kind=kind,
            amount=Decimal(amount),
            contracted_rate=rate,
            term_months=term,
            elapsed_months=elapsed,
            tiers=[EarlyTerminationTier(**t) for t in p.early_termination_tiers],
            tax_type=tax_type,
            tax_rate=ctx.settings.interest_tax_rate,
            rounding=ctx.settings.rounding_mode,
        )
    )
    figs = [*result.figures, pct("early_termination_ratio", result.applied_tier.rate_ratio * 100)]
    payload = {
        "elapsed_months": elapsed,
        "applied_rate_percent": str(result.applied_rate),
        "rate_ratio_of_contracted_percent": str(result.applied_tier.rate_ratio * 100),
        "principal_returned_krw": str(result.principal_returned),
        "pre_tax_interest_krw": str(result.pre_tax_interest),
        "tax_krw": str(result.tax),
        "after_tax_interest_krw": str(result.after_tax_interest),
        "payout_krw": str(result.payout),
        "formula_id": result.formula_id,
    }
    return payload, figs


def _citation_product(p: Product) -> dict[str, str]:
    return {"type": "product", "product_code": p.code, "name": p.name}


# --------------------------------------------------------------------------- 실행기


def search_products(ctx: ToolContext, args: dict[str, Any]) -> ToolOutput:
    stmt = select(Product).where(Product.tenant_id == ctx.tenant_id).order_by(Product.code)
    if args.get("product_type"):
        stmt = stmt.where(Product.product_type == ProductType(args["product_type"]))
    products = list(
        ctx.session.scalars(stmt.options(selectinload(Product.preferential_conditions)))
    )
    if kw := (args.get("keyword") or "").strip():
        products = [p for p in products if kw in p.name or kw in p.summary] or products
    figs = [f for p in products for f in _product_figures(p)]
    return ToolOutput(
        payload={"products": [_product_summary(p) for p in products]},
        figures=figs,
        citations=[_citation_product(p) for p in products],
    )


def get_product_detail(ctx: ToolContext, args: dict[str, Any]) -> ToolOutput:
    p = _load_product(ctx, args["product_code"])
    detail = _product_summary(p)
    detail.update(
        {
            "eligibility": p.eligibility,
            "interest_method": p.interest_method,
            "repayment_methods": p.repayment_methods,
            "preferential_conditions": [
                {"condition": c.description, "rate_percent_point": str(c.rate)}
                for c in p.preferential_conditions
            ],
            "early_termination_tiers": [
                {
                    "from_elapsed_months": t["min_elapsed_months"],
                    "rate_ratio_of_contracted_percent": str(Decimal(t["rate_ratio"]) * 100),
                }
                for t in p.early_termination_tiers
            ],
            "deposit_protected": p.deposit_protected,
            "required_disclosures": p.required_disclosures,
        }
    )
    prefs = _pref_rate(p, True)
    if prefs and p.product_type not in LOAN_TYPES:
        detail["max_rate_with_preferential_percent"] = str(p.base_rate + prefs)
    if p.prepayment_fee_rate is not None:
        detail["prepayment_fee_rate_percent"] = str(p.prepayment_fee_rate)
        detail["prepayment_fee_exemption_after_days"] = p.prepayment_exemption_days
    return ToolOutput(payload=detail, figures=_product_figures(p), citations=[_citation_product(p)])


def search_terms(ctx: ToolContext, args: dict[str, Any]) -> ToolOutput:
    hits = ctx.retriever.search(args["query"], k=4, product_code=args.get("product_code"))
    return ToolOutput(
        payload={
            "results": [
                {"chunk_id": h.chunk.chunk_id, "section": h.chunk.section, "text": h.chunk.text}
                for h in hits
            ]
            or "검색 결과 없음"
        },
        figures=[f for h in hits for f in _text_figures(h.chunk.chunk_id, h.chunk.text)],
        citations=[
            {
                "type": "terms",
                "product_code": h.chunk.product_code,
                "chunk_id": h.chunk.chunk_id,
                "section": h.chunk.section,
            }
            for h in hits
        ],
    )


def calculate_deposit_tool(ctx: ToolContext, args: dict[str, Any]) -> ToolOutput:
    p = _load_product(ctx, args["product_code"])
    _require_type(p, ProductType.DEPOSIT)
    _check_range("예치 기간", args["months"], p.min_term_months, p.max_term_months, "개월")
    _check_range("예치 원금", args["principal"], p.min_amount, p.max_amount, "원")
    pref = _pref_rate(p, args["include_preferential"])
    rate = p.base_rate + pref
    r = calculate_deposit(
        DepositInput(
            principal=Decimal(args["principal"]),
            annual_rate=rate,
            months=args["months"],
            method=InterestMethod(p.interest_method),
            tax_type=args["tax_type"],
            tax_rate=ctx.settings.interest_tax_rate,
            rounding=ctx.settings.rounding_mode,
        )
    )
    payload: dict[str, Any] = {
        "product_code": p.code,
        "product_name": p.name,
        "interest_method": p.interest_method,
        "applied_annual_rate_percent": str(rate),
        "preferential_included_percent_point": str(pref),
        "principal_krw": str(r.principal),
        "months": r.inputs.months,
        "pre_tax_interest_krw": str(r.pre_tax_interest),
        "tax_rate_percent": str(r.inputs.tax_rate * 100)
        if r.inputs.tax_type == TaxType.GENERAL
        else "0",
        "tax_krw": str(r.tax),
        "after_tax_interest_krw": str(r.after_tax_interest),
        "maturity_amount_krw": str(r.maturity_amount),
        "formula_id": r.formula_id,
    }
    figs = [*r.figures, pct("tax_rate", r.inputs.tax_rate * 100), pct("preferential", pref)]
    if (elapsed := args.get("early_termination_after_months")) is not None:
        early, early_figs = _early_termination(
            ctx,
            p,
            EarlyTerminationKind.DEPOSIT,
            args["principal"],
            p.base_rate,
            args["months"],
            elapsed,
            args["tax_type"],
        )
        payload["early_termination"] = early
        figs.extend(early_figs)
    return ToolOutput(payload=payload, figures=figs, citations=[_citation_product(p)])


def calculate_savings_tool(ctx: ToolContext, args: dict[str, Any]) -> ToolOutput:
    p = _load_product(ctx, args["product_code"])
    _require_type(p, ProductType.SAVINGS)
    _check_range("적립 기간", args["months"], p.min_term_months, p.max_term_months, "개월")
    _check_range("월 납입액", args["monthly_payment"], p.min_amount, p.max_amount, "원")
    pref = _pref_rate(p, args["include_preferential"])
    rate = p.base_rate + pref
    r = calculate_savings(
        SavingsInput(
            monthly_payment=Decimal(args["monthly_payment"]),
            annual_rate=rate,
            months=args["months"],
            method=InterestMethod(p.interest_method),
            tax_type=args["tax_type"],
            tax_rate=ctx.settings.interest_tax_rate,
            rounding=ctx.settings.rounding_mode,
        )
    )
    payload: dict[str, Any] = {
        "product_code": p.code,
        "product_name": p.name,
        "applied_annual_rate_percent": str(rate),
        "preferential_included_percent_point": str(pref),
        "monthly_payment_krw": str(r.inputs.monthly_payment),
        "months": r.inputs.months,
        "total_payment_krw": str(r.total_payment),
        "pre_tax_interest_krw": str(r.pre_tax_interest),
        "tax_rate_percent": str(r.inputs.tax_rate * 100)
        if r.inputs.tax_type == TaxType.GENERAL
        else "0",
        "tax_krw": str(r.tax),
        "after_tax_interest_krw": str(r.after_tax_interest),
        "maturity_amount_krw": str(r.maturity_amount),
        "formula_id": r.formula_id,
        "note": "적금 이자는 회차별 실제 예치기간에 대해서만 계산됨",
    }
    figs = [*r.figures, pct("tax_rate", r.inputs.tax_rate * 100), pct("preferential", pref)]
    if (elapsed := args.get("early_termination_after_months")) is not None:
        early, early_figs = _early_termination(
            ctx,
            p,
            EarlyTerminationKind.SAVINGS,
            args["monthly_payment"],
            p.base_rate,
            args["months"],
            elapsed,
            args["tax_type"],
        )
        payload["early_termination"] = early
        figs.extend(early_figs)
    return ToolOutput(payload=payload, figures=figs, citations=[_citation_product(p)])


def calculate_loan_tool(ctx: ToolContext, args: dict[str, Any]) -> ToolOutput:
    p = _load_product(ctx, args["product_code"])
    _require_type(p, *LOAN_TYPES)
    _check_range("대출 기간", args["months"], p.min_term_months, p.max_term_months, "개월")
    _check_range("대출 원금", args["principal"], p.min_amount, p.max_amount, "원")
    if args["repayment_method"] not in p.repayment_methods:
        raise ToolInputError(f"{p.code} 의 상환 방법은 {p.repayment_methods} 중 하나여야 합니다.")
    rate = Decimal(str(args["assumed_annual_rate"]))
    lo = p.base_rate - _pref_rate(p, True)
    if not lo <= rate <= p.max_rate:
        raise ToolInputError(
            f"가정 금리 {rate}% 는 상품 금리 범위({lo}~{p.max_rate}%)를 벗어납니다."
        )
    r = calculate_loan(
        LoanInput(
            principal=Decimal(args["principal"]),
            annual_rate=rate,
            months=args["months"],
            method=args["repayment_method"],
            rounding=ctx.settings.rounding_mode,
        )
    )
    preview = r.schedule[:SCHEDULE_PREVIEW_ROWS] + (
        r.schedule[-1:] if len(r.schedule) > SCHEDULE_PREVIEW_ROWS else []
    )
    payload: dict[str, Any] = {
        "product_code": p.code,
        "product_name": p.name,
        "assumed_annual_rate_percent": str(rate),
        "rate_note": "가정 금리로 계산한 예시이며 실제 금리·한도는 심사 후 결정됨",
        "principal_krw": str(r.inputs.principal),
        "months": r.inputs.months,
        "repayment_method": r.inputs.method.value,
        "first_payment_krw": str(r.first_payment),
        "last_payment_krw": str(r.last_payment),
        "total_interest_krw": str(r.total_interest),
        "total_payment_krw": str(r.total_payment),
        "schedule_preview": [
            {
                "no": row.no,
                "payment_krw": str(row.payment),
                "principal_krw": str(row.principal),
                "interest_krw": str(row.interest),
                "balance_krw": str(row.balance),
            }
            for row in preview
        ],
        "formula_id": r.formula_id,
    }
    figs = list(r.figures)
    for row in preview:
        figs += [
            krw(f"payment_{row.no}", row.payment),
            krw(f"principal_{row.no}", row.principal),
            krw(f"interest_{row.no}", row.interest),
            krw(f"balance_{row.no}", row.balance),
        ]

    days, amount = args.get("prepayment_after_days"), args.get("prepayment_amount")
    if days is not None or amount is not None:
        if days is None or amount is None:
            raise ToolInputError(
                "중도상환수수료 계산에는 prepayment_after_days 와 prepayment_amount 가 모두 필요합니다."
            )
        loan_days = args["months"] * 365 // 12  # 대출기간(일) 환산: 12개월=365일, 36개월=1,095일
        fee = calculate_prepayment_fee(
            PrepaymentFeeInput(
                prepay_amount=Decimal(amount),
                fee_rate=p.prepayment_fee_rate,
                loan_days=loan_days,
                elapsed_days=days,
                exemption_days=p.prepayment_exemption_days or None,
                rounding=ctx.settings.rounding_mode,
            )
        )
        payload["prepayment"] = {
            "loan_days": loan_days,
            "elapsed_days": days,
            "remaining_days": fee.remaining_days,
            "fee_rate_percent": str(p.prepayment_fee_rate),
            "exempted": fee.exempted,
            "fee_krw": str(fee.fee),
            "formula_id": fee.formula_id,
        }
        figs += [
            *fee.figures,
            Figure(name="loan_days", value=Decimal(loan_days), unit=FigureUnit.DAYS),
            Figure(name="elapsed_days", value=Decimal(days), unit=FigureUnit.DAYS),
        ]
    return ToolOutput(payload=payload, figures=figs, citations=[_citation_product(p)])


def record_suitability_check(ctx: ToolContext, args: dict[str, Any]) -> ToolOutput:
    record = {
        k: args.get(k)
        for k in ("annual_income", "existing_debt", "employment_type", "loan_purpose")
    }
    record["customer_declined"] = bool(args.get("customer_declined"))
    ctx.conversation.suitability = record
    figs = [
        krw(k, Decimal(record[k]))
        for k in ("annual_income", "existing_debt")
        if record[k] is not None
    ]
    return ToolOutput(
        payload={
            "recorded": True,
            "note": "적합성 확인 정보가 기록되었습니다. 이는 심사·승인 판단이 아니며, 대출 가능 여부와 금리·한도는 신청 후 심사로 결정됩니다.",
        },
        figures=figs,
    )


def escalate_to_human(ctx: ToolContext, args: dict[str, Any]) -> ToolOutput:
    return ToolOutput(payload={"escalated": True, "category": args["category"]})


EXECUTORS: dict[str, Callable[[ToolContext, dict[str, Any]], ToolOutput]] = {
    "search_products": search_products,
    "get_product_detail": get_product_detail,
    "search_terms": search_terms,
    "calculate_deposit": calculate_deposit_tool,
    "calculate_savings": calculate_savings_tool,
    "calculate_loan": calculate_loan_tool,
    "record_suitability_check": record_suitability_check,
    ESCALATE_TOOL: escalate_to_human,
}
assert set(EXECUTORS) == {t.name for t in TOOL_SPECS}


def execute_tool(ctx: ToolContext, name: str, args: dict[str, Any]) -> ToolOutput:
    """도구를 실행한다. 입력 오류는 is_error 결과로 돌려준다. 그 외 예외는 호출자에게 전파."""
    executor = EXECUTORS.get(name)
    if executor is None:
        return ToolOutput(payload={"error": f"알 수 없는 도구: {name}"}, is_error=True)
    try:
        return executor(ctx, args)
    except ToolInputError as e:
        return ToolOutput(payload={"error": str(e)}, is_error=True)
    except (ValidationError, KeyError, TypeError, ValueError) as e:
        return ToolOutput(
            payload={"error": f"입력값 오류: {type(e).__name__}: {e}"[:500]}, is_error=True
        )
