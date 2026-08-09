from collections.abc import Iterable

from django.core.management.base import CommandError

from ...conf import get_provider
from ...conf import iter_tenants as configured_iter_tenants
from ...types import Tenant, TenantDatabase


def selected_databases(alias: str | None) -> list[TenantDatabase]:
    databases = list(get_provider().iter_databases())
    aliases = [database.alias for database in databases]
    if len(set(aliases)) != len(aliases):
        raise CommandError("Tenant provider returned duplicate database aliases")
    if alias is None:
        return databases
    selected = [database for database in databases if database.alias == alias]
    if not selected:
        raise CommandError(f"Unknown tenant database alias: {alias}")
    return selected


def tenant_snapshot() -> list[Tenant]:
    provider = get_provider()
    tenants = configured_iter_tenants(provider)
    identifiers = [tenant.identifier for tenant in tenants]
    aliases = [tenant.database_alias for tenant in tenants]
    if any(not isinstance(value, str) or not value for value in identifiers + aliases):
        raise CommandError("Tenant identifiers and database aliases must be non-empty")
    if len(set(identifiers)) != len(identifiers):
        raise CommandError("Tenant provider returned duplicate tenant identifiers")
    if len(set(aliases)) != len(aliases):
        raise CommandError("Tenant provider returned duplicate database aliases")
    for tenant in tenants:
        database = provider.get_database(tenant.database_alias)
        if database.alias != tenant.database_alias:
            raise CommandError(f"Tenant provider returned mismatched database alias for '{tenant.identifier}'")
    return tenants


def tenant_for_alias(alias: str) -> Tenant:
    for tenant in tenant_snapshot():
        if tenant.database_alias == alias:
            return tenant
    return Tenant(alias, alias)


def failure_summary(command: str, failures: Iterable[tuple[str, BaseException]]) -> CommandError:
    detail = "; ".join(f"{alias}: {type(error).__name__}: {error}" for alias, error in failures)
    return CommandError(f"{command} failed for tenant databases: {detail}")
