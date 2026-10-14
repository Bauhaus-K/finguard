"""상품 카탈로그 YAML 스키마와 로더."""

from decimal import Decimal
from pathlib import Path
from typing import Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.calc.common import InterestMethod, RepaymentMethod
from app.calc.early import EarlyTerminationTier
from app.db.models import ProductType

DEPOSIT_TYPES = {ProductType.DEPOSIT, ProductType.SAVINGS}
LOAN_TYPES = {ProductType.CREDIT_LOAN, ProductType.POLICY_LOAN}
LEGAL_MAX_LOAN_RATE = Decimal("20")  # 데모 데이터 sanity check 용 상한


class PreferentialSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: str
    rate: Decimal = Field(ge=0, le=10)


class ProductSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(pattern=r"^HB-[A-Z]+-\d{3}$")
    name: str
    product_type: ProductType
    summary: str
    eligibility: str
    base_rate: Decimal = Field(ge=0, le=100)
    max_rate: Decimal | None = Field(default=None, ge=0, le=100)
    interest_method: InterestMethod | None = None
    repayment_methods: list[RepaymentMethod] = Field(default_factory=list)
    min_term_months: int = Field(ge=1)
    max_term_months: int = Field(ge=1)
    min_amount: int = Field(ge=0)
    max_amount: int = Field(ge=0)
    preferential_conditions: list[PreferentialSpec] = Field(default_factory=list)
    early_termination_tiers: list[EarlyTerminationTier] = Field(default_factory=list)
    prepayment_fee_rate: Decimal | None = Field(default=None, ge=0, le=10)
    prepayment_exemption_days: int | None = Field(default=None, ge=0)
    deposit_protected: bool
    required_disclosures: list[str] = Field(min_length=1)
    terms_path: str

    @model_validator(mode="after")
    def _check(self) -> Self:
        if "(가상)" not in self.name:
            raise ValueError(f"{self.code}: 상품명에 '(가상)' 표기가 필요합니다")
        if self.min_term_months > self.max_term_months:
            raise ValueError(f"{self.code}: min_term_months > max_term_months")
        if self.min_amount > self.max_amount:
            raise ValueError(f"{self.code}: min_amount > max_amount")
        if self.product_type in DEPOSIT_TYPES:
            if self.interest_method is None:
                raise ValueError(f"{self.code}: 수신 상품은 interest_method 가 필요합니다")
            if not any(t.min_elapsed_months == 0 for t in self.early_termination_tiers):
                raise ValueError(f"{self.code}: 수신 상품은 경과 0개월 중도해지 구간이 필요합니다")
            if self.repayment_methods or self.max_rate is not None:
                raise ValueError(f"{self.code}: 수신 상품에는 대출 필드를 쓰지 않습니다")
        else:
            if self.max_rate is None or self.max_rate < self.base_rate:
                raise ValueError(
                    f"{self.code}: 대출 상품은 base_rate <= max_rate 범위가 필요합니다"
                )
            if self.max_rate > LEGAL_MAX_LOAN_RATE:
                raise ValueError(f"{self.code}: 대출 금리가 상한을 초과합니다")
            if not self.repayment_methods:
                raise ValueError(f"{self.code}: 대출 상품은 repayment_methods 가 필요합니다")
            if self.prepayment_fee_rate is None or self.prepayment_exemption_days is None:
                raise ValueError(f"{self.code}: 대출 상품은 중도상환수수료 규칙이 필요합니다")
            if self.deposit_protected:
                raise ValueError(f"{self.code}: 대출 상품은 예금자보호 대상이 아닙니다")
        return self


class TenantSpec(BaseModel):
    id: str
    name: str


class CatalogSpec(BaseModel):
    model_config = ConfigDict(extra="ignore")  # YAML 앵커용 '_' 키 무시

    tenant: TenantSpec
    products: list[ProductSpec] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_codes(self) -> Self:
        codes = [p.code for p in self.products]
        dupes = {c for c in codes if codes.count(c) > 1}
        if dupes:
            raise ValueError(f"중복 상품코드: {sorted(dupes)}")
        return self


def load_catalog(path: Path) -> CatalogSpec:
    with path.open(encoding="utf-8") as f:
        return CatalogSpec.model_validate(yaml.safe_load(f))
