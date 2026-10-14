"""DB 엔진/세션."""

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings


def make_engine(url: str) -> Engine:
    if url in ("sqlite://", "sqlite:///:memory:"):
        # 인메모리 DB 는 스레드 간에 같은 연결을 공유해야 한다(테스트용)
        engine = create_engine(url, poolclass=StaticPool, connect_args={"check_same_thread": False})
    else:
        engine = create_engine(url)
    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _fk_on(dbapi_conn, _):
            dbapi_conn.execute("PRAGMA foreign_keys=ON")

    return engine


@lru_cache
def get_engine() -> Engine:
    return make_engine(get_settings().database_url)


def get_session() -> Iterator[Session]:
    with sessionmaker(get_engine(), expire_on_commit=False)() as session:
        yield session
