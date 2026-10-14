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


def get_admin_tenant(
    session: DbSession,
    x_admin_key: Annotated[str | None, Header()] = None,
) -> Tenant:
    """감사 로그·규칙·지표 등 관리 기능. 상담용 API 키로는 접근할 수 없다."""
    if not x_admin_key:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "X-Admin-Key 헤더가 필요합니다")
    tenant = session.scalar(
        select(Tenant).where(Tenant.admin_key_hash == hash_api_key(x_admin_key))
    )
    if tenant is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "유효하지 않은 관리자 키입니다")
    return tenant


AdminTenant = Annotated[Tenant, Depends(get_admin_tenant)]
