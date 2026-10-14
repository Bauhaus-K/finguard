"""상품 카탈로그 YAML → DB 적재 (멱등).

실행: `make seed` (alembic upgrade head 후 `python -m app.db.seed`)
스키마는 Alembic 마이그레이션이 관리한다.
"""

import hashlib
import logging

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.catalog import CatalogSpec, ProductSpec, load_catalog
from app.config import Settings, get_settings
from app.db.models import PreferentialRateCondition, Product, Tenant
from app.db.session import get_engine

log = logging.getLogger(__name__)


def hash_api_key(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _apply_product(product: Product, spec: ProductSpec) -> None:
    data = spec.model_dump(
        mode="json",
        exclude={"code", "preferential_conditions", "early_termination_tiers"},
    )
    data["base_rate"] = spec.base_rate
    data["max_rate"] = spec.max_rate
    data["prepayment_fee_rate"] = spec.prepayment_fee_rate
    for key, value in data.items():
        setattr(product, key, value)
    product.early_termination_tiers = [
        t.model_dump(mode="json") for t in spec.early_termination_tiers
    ]
    product.preferential_conditions = [
        PreferentialRateCondition(description=c.description, rate=c.rate)
        for c in spec.preferential_conditions
    ]


def seed(session: Session, catalog: CatalogSpec, settings: Settings) -> dict[str, int]:
    """카탈로그를 DB 에 반영한다. 같은 카탈로그로 여러 번 실행해도 결과가 같다."""
    tenant_spec = catalog.tenant
    tenant = session.get(Tenant, tenant_spec.id)
    key_hash = hash_api_key(settings.demo_api_key.get_secret_value())
    if tenant is None:
        tenant = Tenant(id=tenant_spec.id, name=tenant_spec.name, api_key_hash=key_hash)
        session.add(tenant)
    else:
        tenant.name = tenant_spec.name
        tenant.api_key_hash = key_hash

    existing = {
        p.code: p
        for p in session.scalars(select(Product).where(Product.tenant_id == tenant_spec.id))
    }
    created = updated = 0
    for spec in catalog.products:
        product = existing.pop(spec.code, None)
        if product is None:
            product = Product(tenant_id=tenant_spec.id, code=spec.code)
            session.add(product)
            created += 1
        else:
            updated += 1
        _apply_product(product, spec)

    # 카탈로그에서 빠진 상품은 삭제한다(YAML 이 원본)
    for stale in existing.values():
        session.delete(stale)
    session.commit()
    return {"created": created, "updated": updated, "deleted": len(existing)}


def run(engine: Engine | None = None, settings: Settings | None = None) -> dict[str, int]:
    settings = settings or get_settings()
    engine = engine or get_engine()
    catalog = load_catalog(settings.data_dir / "products" / "catalog.yaml")
    with Session(engine) as session:
        return seed(session, catalog, settings)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("seed 완료:", run())
