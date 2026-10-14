"""대화 상태 (Phase 2: 프로세스 메모리 저장).

대화 이력에는 '고객에게 실제로 전달된' 텍스트만 저장한다. LLM 원본 답변이 아니라
게이트웨이를 거친 최종 답변이 다음 턴의 문맥이 되어야 하기 때문이다(Phase 3 에서 연결).
같은 요청 안의 도구 호출·thinking 블록은 요청이 끝나면 버린다. 따라서 이전 턴의 수치를
다시 말하려면 이번 턴에서 다시 도구를 호출해야 한다(수치 출처는 항상 '같은 요청 안').
"""

import threading
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

MAX_CONVERSATIONS = 1000
MAX_HISTORY_MESSAGES = 20


@dataclass
class ConversationState:
    conversation_id: str
    tenant_id: str
    history: list[tuple[str, str]] = field(default_factory=list)  # (role, masked text)
    suitability: dict[str, Any] | None = None  # 대출 적합성 확인 기록
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def append(self, role: str, text: str) -> None:
        self.history.append((role, text))
        del self.history[:-MAX_HISTORY_MESSAGES]
        self.updated_at = datetime.now(UTC)


class ConversationStore:
    def __init__(self, max_size: int = MAX_CONVERSATIONS) -> None:
        self._data: OrderedDict[tuple[str, str], ConversationState] = OrderedDict()
        self._lock = threading.Lock()
        self._max = max_size

    def get_or_create(self, tenant_id: str, conversation_id: str | None) -> ConversationState:
        with self._lock:
            if conversation_id and (tenant_id, conversation_id) in self._data:
                self._data.move_to_end((tenant_id, conversation_id))
                return self._data[(tenant_id, conversation_id)]
            cid = conversation_id or f"conv_{uuid.uuid4().hex[:16]}"
            state = ConversationState(conversation_id=cid, tenant_id=tenant_id)
            self._data[(tenant_id, cid)] = state
            while len(self._data) > self._max:
                self._data.popitem(last=False)
            return state
