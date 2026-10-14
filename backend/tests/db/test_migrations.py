from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.seed import seed
from app.db.session import make_engine

BACKEND = Path(__file__).resolve().parents[2]


def test_alembic_upgrade_then_seed(tmp_path, monkeypatch, catalog, settings):
    url = f"sqlite:///{tmp_path / 'm.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    get_settings.cache_clear()
    try:
        cfg = Config(str(BACKEND / "alembic.ini"))
        cfg.set_main_option("script_location", str(BACKEND / "migrations"))
        command.upgrade(cfg, "head")
        command.downgrade(cfg, "0001")
        command.upgrade(cfg, "head")
    finally:
        get_settings.cache_clear()

    engine = make_engine(url)
    tables = set(inspect(engine).get_table_names())
    assert {"tenants", "products", "preferential_rate_conditions", "audit_records"} <= tables
    with engine.connect() as conn:
        triggers = {
            r[0]
            for r in conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='trigger'")
        }
    assert triggers == {"audit_records_no_update", "audit_records_no_delete"}
    with Session(engine) as s:
        assert seed(s, catalog, settings)["created"] == 8
    engine.dispose()
