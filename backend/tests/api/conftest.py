import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.db.session import get_session
from app.llm.fake import FakeLLM
from app.main import app
from app.services import build_services, get_services

KEY = "test-key"
H = {"X-API-Key": KEY}
DEPOSIT = (
    "calculate_deposit",
    dict(
        product_code="HB-DEP-001",
        principal=10_000_000,
        months=12,
        include_preferential=False,
        tax_type="GENERAL",
        early_termination_after_months=None,
    ),
)


@pytest.fixture
def make_client(engine, catalog, tmp_path):
    from app.db.seed import seed

    settings = Settings(_env_file=None, demo_api_key=KEY)
    with sessionmaker(engine)() as s:
        seed(s, catalog, settings)

    def _session():
        with sessionmaker(engine, expire_on_commit=False)() as s:
            yield s

    def factory(script=(), **overrides):
        services = build_services(settings.model_copy(update=overrides), llm=FakeLLM(script))
        app.dependency_overrides[get_session] = _session
        app.dependency_overrides[get_services] = lambda: services
        return TestClient(app), services

    yield factory
    app.dependency_overrides.clear()
