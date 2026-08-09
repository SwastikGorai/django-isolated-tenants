from django.http import HttpRequest

from django_isolated_tenants import Tenant, TenantDatabase


def database(alias: str) -> TenantDatabase:
    return TenantDatabase(
        alias=alias,
        config={"ENGINE": "django.db.backends.postgresql", "NAME": alias},
    )


class Provider:
    tenant: Tenant | None = Tenant("tenant-id", "tenant_a")

    def resolve_request(self, request: HttpRequest) -> Tenant | None:
        return self.tenant

    def get_database(self, alias: str) -> TenantDatabase:
        return database(alias)

    def iter_databases(self) -> list[TenantDatabase]:
        return [database("tenant_a"), database("tenant_b")]

    def iter_tenants(self) -> list[Tenant]:
        return [Tenant("tenant-1", "tenant_a"), Tenant("tenant-2", "tenant_b")]


provider = Provider()
