from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from django.http import HttpRequest


@dataclass(frozen=True, slots=True)
class Tenant:
    identifier: str
    database_alias: str


@dataclass(frozen=True, slots=True)
class TenantDatabase:
    alias: str
    config: Mapping[str, object]


@runtime_checkable
class TenantProvider(Protocol):
    def resolve_request(self, request: HttpRequest) -> Tenant | None: ...

    def get_database(self, alias: str) -> TenantDatabase: ...

    def iter_databases(self) -> "list[TenantDatabase] | tuple[TenantDatabase, ...]": ...

    def iter_tenants(self) -> Iterable[Tenant]: ...
