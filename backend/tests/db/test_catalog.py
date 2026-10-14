import copy
import re

import pytest
import yaml
from pydantic import ValidationError

from app.catalog import CatalogSpec, ProductSpec
from app.db.models import ProductType

EXPECTED_COUNTS = {
    ProductType.DEPOSIT: 3,
    ProductType.SAVINGS: 2,
    ProductType.CREDIT_LOAN: 2,
    ProductType.POLICY_LOAN: 1,
}


def test_product_mix(catalog):
    counts = {t: 0 for t in ProductType}
    for p in catalog.products:
        counts[p.product_type] += 1
    assert counts == EXPECTED_COUNTS


def test_all_names_marked_fictional(catalog):
    assert catalog.tenant.name.endswith("(가상)")
    assert all("(가상)" in p.name for p in catalog.products)


@pytest.mark.parametrize("idx", range(8))
def test_terms_document(catalog, settings, idx):
    p = catalog.products[idx]
    path = settings.data_dir / p.terms_path
    assert path.is_file(), path
    text = path.read_text(encoding="utf-8")
    assert f"product_code: {p.code}" in text
    assert "데모용 가상 문서" in text
    assert p.name in text
    # 조항 번호가 있어 RAG 출처로 인용할 수 있어야 한다
    assert len(re.findall(r"^## 제\d+조", text, flags=re.M)) >= 8
    # 2쪽 이상 분량 (공백 제외 약 1,800자 이상)
    assert len(re.sub(r"\s", "", text)) >= 1800


def test_terms_rates_match_catalog(catalog, settings):
    """약관에 적힌 기본금리가 카탈로그(단일 진실 원천)와 일치해야 한다."""
    for p in catalog.products:
        text = (settings.data_dir / p.terms_path).read_text(encoding="utf-8")
        assert f"연 {p.base_rate:.2f}%" in text, p.code
        if p.max_rate is not None:
            assert f"연 {p.max_rate:.2f}%" in text, p.code


def test_required_disclosures(catalog):
    for p in catalog.products:
        joined = " ".join(p.required_disclosures)
        if p.product_type in (ProductType.DEPOSIT, ProductType.SAVINGS):
            assert p.deposit_protected
            assert "예금자보호" in joined
            assert "중도해지" in joined
        else:
            assert not p.deposit_protected
            assert "심사" in joined
            assert "신용평점" in joined


def _raw(settings):
    with (settings.data_dir / "products" / "catalog.yaml").open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def test_duplicate_codes_rejected(settings):
    raw = _raw(settings)
    raw["products"].append(copy.deepcopy(raw["products"][0]))
    with pytest.raises(ValidationError, match="중복 상품코드"):
        CatalogSpec.model_validate(raw)


def _product(settings, code):
    return copy.deepcopy(next(p for p in _raw(settings)["products"] if p["code"] == code))


@pytest.mark.parametrize(
    ("code", "patch", "message"),
    [
        ("HB-DEP-001", {"name": "실제 정기예금"}, "가상"),
        ("HB-DEP-001", {"min_term_months": 48}, "min_term_months"),
        ("HB-DEP-001", {"min_amount": 10**12}, "min_amount"),
        ("HB-DEP-001", {"interest_method": None}, "interest_method"),
        ("HB-DEP-001", {"early_termination_tiers": []}, "중도해지"),
        ("HB-DEP-001", {"max_rate": "5"}, "대출 필드"),
        ("HB-LOAN-001", {"max_rate": "5"}, "base_rate <= max_rate"),
        ("HB-LOAN-001", {"max_rate": None}, "base_rate <= max_rate"),
        ("HB-LOAN-001", {"max_rate": "25"}, "상한"),
        ("HB-LOAN-001", {"repayment_methods": []}, "repayment_methods"),
        ("HB-LOAN-001", {"prepayment_fee_rate": None}, "중도상환수수료"),
        ("HB-LOAN-001", {"deposit_protected": True}, "예금자보호"),
        ("HB-LOAN-001", {"code": "XX-1"}, "pattern"),
        ("HB-LOAN-001", {"required_disclosures": []}, "required_disclosures"),
    ],
)
def test_invalid_product_rejected(settings, code, patch, message):
    data = _product(settings, code)
    data.update(patch)
    with pytest.raises(ValidationError, match=message):
        ProductSpec.model_validate(data)
