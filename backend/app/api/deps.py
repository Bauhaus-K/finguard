"""API 공통 의존성: DB 세션, 테넌트 인증."""

from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Tenant
from app.db.seed import hash_api_key
from app.db.session import get_session

DbSession = Annotated[Session, Depends(get_session)]


def get_tenant(
    session: DbSession,
    x_api_key: Annotated[str | None, Header()] = None,
) -> Tenant:
    if not x_api_key:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "X-API-Key 헤더가 필요합니다")
    tenant = session.scalar(select(Tenant).where(Tenant.api_key_hash == hash_api_key(x_api_key)))
    if tenant is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "유효하지 않은 API 키입니다")
    return tenant


CurrentTenant = Annotated[Tenant, Depends(get_tenant)]
