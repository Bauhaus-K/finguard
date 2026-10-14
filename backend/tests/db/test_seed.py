from decimal import Decimal

from sqlalchemy import select

from app.config import Settings
from app.db.models import Product, Tenant
from app.db.seed import hash_api_key, seed


def test_seed_loads_catalog(session, catalog, settings):
    stats = seed(session, catalog, settings)
    assert stats == {"created": 8, "updated": 0, "deleted": 0}

    products = session.scalars(select(Product).order_by(Product.code)).all()
    assert len(products) == 8
    dep = session.scalar(select(Product).where(Product.code == "HB-DEP-001"))
    assert dep.base_rate == Decimal("3.30")
    assert isinstance(dep.base_rate, Decimal)
    assert dep.interest_method == "SIMPLE"
    assert dep.early_termination_tiers[0] == {"min_elapsed_months": 0, "rate_ratio": "0.1"}

    special = session.scalar(select(Product).where(Product.code == "HB-DEP-003"))
    assert [c.rate for c in special.preferential_conditions] == [Decimal("0.10"), Decimal("0.10")]

    loan = session.scalar(select(Product).where(Product.code == "HB-LOAN-001"))
    assert loan.max_rate == Decimal("15.90")
    assert loan.repayment_methods == ["EQUAL_PAYMENT", "EQUAL_PRINCIPAL", "BULLET"]
    assert loan.prepayment_fee_rate == Decimal("1.20")


def test_seed_is_idempotent(session, catalog, settings):
    seed(session, catalog, settings)
    stats = seed(session, catalog, settings)
    assert stats == {"created": 0, "updated": 8, "deleted": 0}
    assert len(session.scalars(select(Product)).all()) == 8
    special = session.scalar(select(Product).where(Product.code == "HB-DEP-003"))
    assert len(special.preferential_conditions) == 2


def test_seed_removes_products_dropped_from_catalog(session, catalog, settings):
    seed(session, catalog, settings)
    smaller = catalog.model_copy(update={"products": catalog.products[:-1]})
    stats = seed(session, smaller, settings)
    assert stats["deleted"] == 1
    assert session.scalar(select(Product).where(Product.code == "HB-POL-001")) is None


def test_api_key_stored_as_hash_only(session, catalog):
    s = Settings(demo_api_key="super-secret-key")
    seed(session, catalog, s)
    tenant = session.get(Tenant, "demo")
    assert tenant.api_key_hash == hash_api_key("super-secret-key")
    assert "super-secret-key" not in tenant.api_key_hash
    # 키 변경 후 재시드하면 해시가 갱신된다
    seed(session, catalog, Settings(demo_api_key="rotated"))
    assert session.get(Tenant, "demo").api_key_hash == hash_api_key("rotated")
