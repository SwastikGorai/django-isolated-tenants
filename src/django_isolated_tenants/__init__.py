from typing import Any

from .context import (
    clear_tenant_context,
    get_current_database_alias,
    get_current_tenant,
    get_current_tenant_id,
    tenant_context,
)
from .exceptions import TenantContextMissing, TenantDatabaseInvalid, TenantNotResolved, TenantTaskMetadataInvalid
from .types import Tenant, TenantDatabase, TenantProvider

__all__ = [
    "Tenant",
    "TenantContextMissing",
    "TenantDatabase",
    "TenantDatabaseInvalid",
    "TenantNotResolved",
    "TenantTaskMetadataInvalid",
    "TenantProvider",
    "MasterModel",
    "TenantModel",
    "clear_tenant_context",
    "get_current_database_alias",
    "get_current_tenant",
    "get_current_tenant_id",
    "tenant_context",
]


def __getattr__(name: str) -> Any:
    if name in {"MasterModel", "TenantModel"}:
        from .models import MasterModel, TenantModel

        return {"MasterModel": MasterModel, "TenantModel": TenantModel}[name]
    raise AttributeError(name)
