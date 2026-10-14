"""POST /v1/gateway/check — 게이트웨이 단독 호출.

금융사가 기존 챗봇의 답변을 고객에게 보내기 전에 이 API 로 검사받는 판매 옵션.
요청·판정은 감사 로그(mode=gateway_only)에 남는다.
"""

import time
import uuid
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.deps import CurrentTenant, DbSession
from app.audit.hashchain import append_audit
from app.calc.common import Figure, FigureUnit
from app.chat_service import product_refs
from app.gateway.checks import CheckContext
from app.gateway.engine import run_gateway
from app.gateway.types import GatewayInput, SuitabilityInfo
from app.privacy.pii import mask_pii
from app.services import Services, get_services

router = APIRouter(prefix="/v1/gateway", tags=["gateway"])


class SourceIn(BaseModel):
    name: str = "source"
    value: Decimal
    unit: FigureUnit


class GatewayCheckRequest(BaseModel):
    answer: str = Field(min_length=1, max_length=8000, description="검사할 챗봇 답변")
    user_message: str = Field(default="", max_length=2000)
    sources: list[SourceIn] = Field(
        default_factory=list, description="답변 수치의 출처(계산·조회 결과)"
    )
    context_texts: list[str] = Field(
        default_factory=list, description="출처로 인정할 원문(검색 문서 등)"
    )
    tools_called: list[str] = Field(default_factory=list)
    product_types: list[str] = Field(default_factory=list)
    suitability: SuitabilityInfo = Field(default_factory=SuitabilityInfo)


class GatewayCheckResponse(BaseModel):
    request_id: str
    status: str
    final_answer: str
    retryable: bool
    checks: list[dict[str, Any]]
    rules_version: str | None
    rules_digest: str | None


@router.post("/check", response_model=GatewayCheckResponse)
def check(
    req: GatewayCheckRequest,
    tenant: CurrentTenant,
    session: DbSession,
    services: Annotated[Services, Depends(get_services)],
) -> GatewayCheckResponse:
    t0 = time.perf_counter()
    request_id = f"gw_{uuid.uuid4().hex}"
    loaded = services.rules.get(tenant.id)
    inp = GatewayInput(
        user_message=req.user_message,
        answer=req.answer,
        sources=[Figure(name=s.name, value=s.value, unit=s.unit) for s in req.sources],
        context_texts=req.context_texts,
        tools_called=req.tools_called,
        product_types=req.product_types,
        products=product_refs(session, tenant.id),
        suitability=req.suitability,
    )
    decision = run_gateway(inp, loaded, CheckContext(judge_llm=services.llm))
    append_audit(
        session,
        tenant_id=tenant.id,
        request_id=request_id,
        status=decision.status.value,
        payload={
            "mode": "gateway_only",
            "input": {
                "user_message": mask_pii(req.user_message).text,
                "answer": mask_pii(req.answer).text,
                "sources": [s.model_dump(mode="json") for s in req.sources],
                "tools_called": req.tools_called,
                "product_types": req.product_types,
                "suitability": req.suitability.model_dump(),
            },
            "gateway": decision.model_dump(mode="json"),
            "final": {"status": decision.status, "answer": decision.final_answer},
            "rules": {
                "version": decision.rules_version,
                "digest": loaded.digest,
                "files": loaded.files,
                "error": loaded.error,
            },
            "latency_ms": int((time.perf_counter() - t0) * 1000),
        },
    )
    return GatewayCheckResponse(
        request_id=request_id,
        status=decision.status,
        final_answer=decision.final_answer,
        retryable=decision.retryable,
        checks=[c.model_dump(mode="json", exclude={"text_after"}) for c in decision.checks],
        rules_version=decision.rules_version,
        rules_digest=decision.rules_digest,
    )
