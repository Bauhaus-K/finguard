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


@pytest.fixture(scope="session")
def retriever(settings):
    from app.rag import BM25Retriever, load_terms_chunks

    return BM25Retriever(load_terms_chunks(settings.data_dir / "terms"))


@pytest.fixture
def seeded_session(session, catalog, settings):
    from app.db.seed import seed

    seed(session, catalog, settings)
    return session


@pytest.fixture
def conversation():
    from app.agent.state import ConversationState

    return ConversationState(conversation_id="conv_test", tenant_id="demo")


@pytest.fixture
def tool_ctx(seeded_session, settings, retriever, conversation):
    from app.agent.tools import ToolContext

    return ToolContext(
        session=seeded_session,
        tenant_id="demo",
        settings=settings,
        retriever=retriever,
        conversation=conversation,
    )
