from app.config import Settings
from app.llm.anthropic_adapter import AnthropicAdapter
from app.llm.base import LLMAdapter


def build_llm(settings: Settings) -> LLMAdapter:
    if settings.llm_provider == "anthropic":
        key = settings.anthropic_api_key.get_secret_value() if settings.anthropic_api_key else None
        return AnthropicAdapter(
            model=settings.llm_model,
            api_key=key,
            effort=settings.llm_effort,
            max_tokens=settings.llm_max_tokens,
            timeout=settings.llm_timeout_seconds,
            refusal_fallback=settings.llm_refusal_fallback,
        )
    # 오픈웨이트(온프레미스) 어댑터는 같은 LLMAdapter 프로토콜로 추가한다.
    raise ValueError(f"지원하지 않는 LLM_PROVIDER: {settings.llm_provider}")
