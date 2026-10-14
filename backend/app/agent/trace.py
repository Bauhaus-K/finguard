"""요청 단위 실행 기록(trace).

request_id 하나로 질문 → 검색 문서 → 도구 호출/결과 → LLM 원본 답변 → 최종 답변을 재구성할 수 있어야 한다.
저장 직전에 모든 문자열에 개인정보 마스킹을 다시 적용한다. Phase 3 에서 해시 체인 감사 로그로 저장된다.
"""

import json
import logging
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
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


class TraceLogger:
    """JSON Lines 파일에 trace 를 남긴다(Phase 2 확인용). None 이면 기록하지 않는다."""

    def __init__(self, path: Path | None) -> None:
        self.path = path
        self._lock = threading.Lock()

    def write(self, record: dict[str, Any]) -> None:
        if self.path is None:
            return
        line = json.dumps(mask_deep(record), ensure_ascii=False, default=str)
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
