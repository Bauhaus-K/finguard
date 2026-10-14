"""프로세스 단위 싱글턴(LLM 어댑터, 검색기, 대화 저장소, trace 기록기).

FastAPI 의존성으로 주입하며 테스트에서는 dependency_overrides 로 교체한다.
"""

from dataclasses import dataclass
from functools import lru_cache

from app.agent.state import ConversationStore
from app.agent.trace import TraceLogger
from app.config import Settings, get_settings
from app.llm.base import LLMAdapter
from app.llm.factory import build_llm
from app.rag import BM25Retriever, Retriever, load_terms_chunks


@dataclass
class Services:
    settings: Settings
    llm: LLMAdapter
    retriever: Retriever
    conversations: ConversationStore
    trace_logger: TraceLogger


def build_services(settings: Settings, llm: LLMAdapter | None = None) -> Services:
    return Services(
        settings=settings,
        llm=llm or build_llm(settings),
        retriever=BM25Retriever(load_terms_chunks(settings.data_dir / "terms")),
        conversations=ConversationStore(),
        trace_logger=TraceLogger(settings.trace_log_path),
    )


@lru_cache
def get_services() -> Services:
    return build_services(get_settings())
