"""요청 단위 실행 기록(trace).

request_id 하나로 질문 → 검색 문서 → 도구 호출/결과 → LLM 원본 답변 → 최종 답변을 재구성할 수 있어야 한다.
감사 로그(app/audit)에 저장될 때 모든 문자열에 개인정보 마스킹을 다시 적용한다.
"""

import logging
import time
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from app.privacy.pii import mask_pii

log = logging.getLogger(__name__)


class TraceEvent(BaseModel):
    seq: int
    kind: str  # input | llm_call | tool_call | final | error
    elapsed_ms: int
    data: dict[str, Any]


class Trace(BaseModel):
    request_id: str
    tenant_id: str
    conversation_id: str
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    events: list[TraceEvent] = Field(default_factory=list)

    def model_post_init(self, _: Any) -> None:
        self._t0 = time.perf_counter()

    def add(self, kind: str, **data: Any) -> None:
        self.events.append(
            TraceEvent(
                seq=len(self.events),
                kind=kind,
                elapsed_ms=int((time.perf_counter() - self._t0) * 1000),
                data=data,
            )
        )


def mask_deep(value: Any) -> Any:
    if isinstance(value, str):
        return mask_pii(value).text
    if isinstance(value, dict):
        return {k: mask_deep(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [mask_deep(v) for v in value]
    return value
