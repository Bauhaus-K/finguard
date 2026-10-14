import pytest
from sqlalchemy.orm import Session

from app.catalog import CatalogSpec, load_catalog
from app.config import Settings, get_settings
from app.db.models import Base
from app.db.session import make_engine


@pytest.fixture(scope="session")
def settings() -> Settings:
    return get_settings()


@pytest.fixture(scope="session")
def catalog(settings) -> CatalogSpec:
    return load_catalog(settings.data_dir / "products" / "catalog.yaml")


@pytest.fixture
def engine():
    eng = make_engine("sqlite://")
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine):
    with Session(engine) as s:
        yield s
