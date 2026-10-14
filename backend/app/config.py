"""애플리케이션 설정. 값은 환경변수 또는 .env 에서 읽는다.

비밀값(API 키)은 SecretStr 로만 다루어 repr/로그에 평문이 노출되지 않게 한다.
"""

from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.calc.rounding import RoundingMode

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", ".env"), env_file_encoding="utf-8", extra="ignore"
    )

    app_env: str = "dev"
    database_url: str = f"sqlite:///{REPO_ROOT / 'backend' / 'finguard.db'}"

    # LLM (Phase 2)
    llm_provider: str = "anthropic"
    llm_model: str = "claude-sonnet-5-5"
    anthropic_api_key: SecretStr | None = None
    llm_effort: str = "medium"
    llm_max_tokens: int = 16000
    llm_timeout_seconds: float = 120.0
    llm_refusal_fallback: bool = True

    # 에이전트
    agent_max_steps: int = 8  # 한 요청에서 LLM 호출 최대 횟수. 초과 시 상담원 이관
    allow_debug_mode: bool = True  # 게이트웨이 미적용 원본 답변 반환 허용 (운영에서는 false)

    # 계산 엔진 정책
    rounding_mode: RoundingMode = RoundingMode.TRUNCATE
    interest_tax_rate: Decimal = Decimal("0.154")

    # 데이터 경로
    data_dir: Path = REPO_ROOT / "data"
    rules_dir: Path = REPO_ROOT / "rules"

    # 데모 테넌트
    demo_tenant_id: str = "demo"
    demo_api_key: SecretStr = SecretStr("demo-key-change-me")
    demo_admin_key: SecretStr = SecretStr("demo-admin-key-change-me")


@lru_cache
def get_settings() -> Settings:
    return Settings()
