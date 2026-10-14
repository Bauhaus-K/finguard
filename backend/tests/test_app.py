from fastapi.testclient import TestClient

from app.config import Settings
from app.main import app


def test_healthz():
    assert TestClient(app).get("/healthz").json() == {"status": "ok"}


def test_secrets_not_exposed_in_repr():
    s = Settings(anthropic_api_key="sk-ant-should-not-leak", demo_api_key="demo-should-not-leak")
    dumped = repr(s) + str(s.model_dump())
    assert "sk-ant-should-not-leak" not in dumped
    assert "demo-should-not-leak" not in dumped


def test_default_model(monkeypatch):
    monkeypatch.delenv("LLM_MODEL", raising=False)
    assert Settings(_env_file=None).llm_model == "claude-sonnet-5-5"
