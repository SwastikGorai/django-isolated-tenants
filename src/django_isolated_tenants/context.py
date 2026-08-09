from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from .types import Tenant


@dataclass(frozen=True, slots=True)
class _TenantContext:
    tenant: Tenant


_current: ContextVar[_TenantContext | None] = ContextVar("isolated_tenant_context", default=None)


@contextmanager
def tenant_context(tenant: Tenant) -> Iterator[Tenant]:
    token = _current.set(_TenantContext(tenant=tenant))
    try:
        yield tenant
    finally:
        _current.reset(token)


def get_current_tenant() -> Tenant | None:
    value = _current.get()
    return value.tenant if value else None


def get_current_tenant_id() -> str | None:
    tenant = get_current_tenant()
    return tenant.identifier if tenant else None


def get_current_database_alias() -> str | None:
    tenant = get_current_tenant()
    return tenant.database_alias if tenant else None


def clear_tenant_context() -> None:
    _current.set(None)
