import os

from django.http import HttpRequest

from django_isolated_tenants import Tenant, TenantDatabase

TENANTS = {
    "acme": Tenant("acme", "e2e_acme"),
    "globex": Tenant("globex", "e2e_globex"),
}


class RealWorldProvider:
    def resolve_request(self, request: HttpRequest) -> Tenant | None:
        return TENANTS.get(request.headers.get("X-Workspace", ""))

    def get_database(self, alias: str) -> TenantDatabase:
        tenant = next((item for item in TENANTS.values() if item.database_alias == alias), None)
        if tenant is None:
            raise KeyError(alias)
        suffix = tenant.identifier.upper()
        return TenantDatabase(
            alias,
            {
                "ENGINE": "django.db.backends.postgresql",
                "NAME": os.environ[f"E2E_POSTGRES_DB_{suffix}"],
                "USER": os.environ.get("E2E_POSTGRES_USER", "postgres"),
                "PASSWORD": os.environ.get("E2E_POSTGRES_PASSWORD", "postgres"),
                "HOST": os.environ.get("E2E_POSTGRES_HOST", "127.0.0.1"),
                "PORT": os.environ.get("E2E_POSTGRES_PORT", "5432"),
            },
        )

    def iter_databases(self) -> list[TenantDatabase]:
        return [self.get_database(tenant.database_alias) for tenant in TENANTS.values()]

    def iter_tenants(self) -> list[Tenant]:
        return list(TENANTS.values())


provider = RealWorldProvider()
