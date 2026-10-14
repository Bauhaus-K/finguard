"""게이트웨이 입출력 타입."""

from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.calc.common import Figure, FigureUnit


class GatewayStatus(StrEnum):
    PASS = "PASS"
    AUTO_FIXED = "AUTO_FIXED"
    BLOCKED = "BLOCKED"
    ESCALATED = "ESCALATED"


class Outcome(StrEnum):
    PASS = "PASS"  # 문제 없음
    FIXED = "FIXED"  # 자동 수정함(마스킹·문장 수정·고지 첨부)
    FAIL = "FAIL"  # 위반
    ERROR = "ERROR"  # 검사 자체 오류 (→ 이관)
    SKIPPED = "SKIPPED"  # 규칙에서 비활성화


class Action(StrEnum):
    NONE = "NONE"
    MASK = "MASK"
    REWRITE = "REWRITE"
    AUTO_APPEND = "AUTO_APPEND"
    BLOCK = "BLOCK"
    REGENERATE = "REGENERATE"  # 차단 + 재생성 시도 가능
    REPLACE = "REPLACE"  # 차단 + 지정 문구로 대체
    ESCALATE = "ESCALATE"


class Finding(BaseModel):
    code: str
    message: str
    excerpt: str | None = None
    severity: str = "violation"  # violation | info


class CheckResult(BaseModel):
    check: str
    outcome: Outcome
    action: Action = Action.NONE
    findings: list[Finding] = Field(default_factory=list)
    text_after: str | None = None  # 수정된 답변 (FIXED 일 때)
    replacement: str | None = None  # REPLACE 일 때 고객에게 보낼 문구


class ProductRef(BaseModel):
    code: str
    name: str
    product_type: str


class SuitabilityInfo(BaseModel):
    recorded: bool = False
    declined: bool = False


class GatewayInput(BaseModel):
    """검사 대상. 에이전트 내부 호출과 단독 게이트웨이 API 가 같은 형식을 쓴다."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    user_message: str = ""
    answer: str
    sources: list[Figure] = Field(default_factory=list)  # 같은 요청의 출처 수치
    context_texts: list[str] = Field(default_factory=list)  # 출처로 인정할 원문(검색 문서 등)
    tools_called: list[str] = Field(default_factory=list)
    product_types: list[str] = Field(default_factory=list)  # 답변이 다루는 상품 유형 힌트
    products: list[ProductRef] = Field(
        default_factory=list
    )  # 언급 탐지용 상품 목록(테넌트 카탈로그)
    suitability: SuitabilityInfo = Field(default_factory=SuitabilityInfo)


class GatewayDecision(BaseModel):
    status: GatewayStatus
    final_answer: str
    checks: list[CheckResult]
    retryable: bool = False  # 재생성으로 해결 가능한 차단인지 (수치 검증 실패)
    rules_version: str | None = None
    rules_digest: str | None = None
    masked_user_message: str = ""

    def failed(self) -> list[CheckResult]:
        return [c for c in self.checks if c.outcome in (Outcome.FAIL, Outcome.ERROR)]


def source(name: str, value: Decimal | int | str, unit: FigureUnit) -> Figure:
    return Figure(name=name, value=Decimal(str(value)), unit=unit)
