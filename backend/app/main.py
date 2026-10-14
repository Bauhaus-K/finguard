"""FastAPI 진입점."""

from fastapi import FastAPI

from app.api.v1 import audit, chat, gateway, rules

app = FastAPI(
    title="FinGuard AI",
    version="0.3.0",
    description="컴플라이언스 게이트웨이 내장 금융 상담 에이전트 (데모·MOCK 데이터 전용)",
)
app.include_router(chat.router)
app.include_router(gateway.router)
app.include_router(audit.router)
app.include_router(rules.router)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}
