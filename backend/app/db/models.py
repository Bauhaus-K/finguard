"""ORM 모델. 상품 정보의 단일 진실 원천."""

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.db.types import ExactDecimal


class Base(DeclarativeBase):
    pass


def _utcnow() -> datetime:
    return datetime.now(UTC)


class ProductType(StrEnum):
    DEPOSIT = "DEPOSIT"  # 정기예금
    SAVINGS = "SAVINGS"  # 정기적금
    CREDIT_LOAN = "CREDIT_LOAN"  # 신용대출
    POLICY_LOAN = "POLICY_LOAN"  # 정책서민금융(가상)


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    # API 키는 SHA-256 해시만 저장한다
    api_key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (UniqueConstraint("tenant_id", "code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    code: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(200))
    product_type: Mapped[ProductType] = mapped_column(SAEnum(ProductType, native_enum=False))
    summary: Mapped[str] = mapped_column(Text, default="")
    eligibility: Mapped[str] = mapped_column(Text, default="")

    # 금리(연 %). 대출은 base_rate~max_rate 범위(실제 금리는 심사 후 결정).
    base_rate: Mapped[Decimal] = mapped_column(ExactDecimal())
    max_rate: Mapped[Decimal | None] = mapped_column(ExactDecimal(), nullable=True)
    interest_method: Mapped[str | None] = mapped_column(String(32), nullable=True)
    repayment_methods: Mapped[list[str]] = mapped_column(JSON, default=list)

    min_term_months: Mapped[int] = mapped_column(Integer)
    max_term_months: Mapped[int] = mapped_column(Integer)
    # 예금/대출: 1회 금액, 적금: 월 납입액
    min_amount: Mapped[int] = mapped_column(BigInteger)
    max_amount: Mapped[int] = mapped_column(BigInteger)

    early_termination_tiers: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    prepayment_fee_rate: Mapped[Decimal | None] = mapped_column(ExactDecimal(), nullable=True)
    prepayment_exemption_days: Mapped[int | None] = mapped_column(Integer, nullable=True)

    deposit_protected: Mapped[bool] = mapped_column(default=False)
    required_disclosures: Mapped[list[str]] = mapped_column(JSON, default=list)
    terms_path: Mapped[str] = mapped_column(String(500))

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    preferential_conditions: Mapped[list["PreferentialRateCondition"]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
        order_by="PreferentialRateCondition.id",
    )


class PreferentialRateCondition(Base):
    __tablename__ = "preferential_rate_conditions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"))
    description: Mapped[str] = mapped_column(String(500))
    rate: Mapped[Decimal] = mapped_column(ExactDecimal())  # 우대 금리(연 %p)

    product: Mapped[Product] = relationship(back_populates="preferential_conditions")


class AuditRecord(Base):
    """감사 로그 (append-only, 해시 체인). 로직은 Phase 3 에서 구현한다."""

    __tablename__ = "audit_records"
    __table_args__ = (UniqueConstraint("tenant_id", "seq"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    seq: Mapped[int] = mapped_column(BigInteger)
    request_id: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(16))  # PASS / AUTO_FIXED / BLOCKED / ESCALATED
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)  # 마스킹된 trace
    prev_hash: Mapped[str] = mapped_column(String(64))
    record_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
