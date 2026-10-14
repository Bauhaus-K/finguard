"""현재 적용 중인 게이트웨이 규칙 조회."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from app.api.deps import AdminTenant
from app.services import Services, get_services

router = APIRouter(prefix="/v1/rules", tags=["rules"])


@router.get("")
def current_rules(
    tenant: AdminTenant, services: Annotated[Services, Depends(get_services)]
) -> dict[str, Any]:
    loaded = services.rules.get(tenant.id)
    return {
        "tenant_id": tenant.id,
        "files": loaded.files,
        "version": loaded.rules.version if loaded.rules else None,
        "digest": loaded.digest or None,
        "error": loaded.error,
        "rules": loaded.rules.model_dump(mode="json") if loaded.rules else None,
    }
