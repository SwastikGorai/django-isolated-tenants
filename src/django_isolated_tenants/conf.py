from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils.module_loading import import_string

from .types import Tenant, TenantProvider


@dataclass(frozen=True, slots=True)
class IsolatedTenantSettings:
    provider_path: str
    master_alias: str
    master_models: frozenset[str]
    master_apps: frozenset[str]
    excluded_paths: tuple[str, ...]
    tenant_attribute: str
    database_attribute: str


@lru_cache(maxsize=1)
def get_settings() -> IsolatedTenantSettings:
    config = getattr(settings, "ISOLATED_TENANTS", {})
    provider = config.get("PROVIDER")
    if not isinstance(provider, str) or not provider:
        raise ImproperlyConfigured("ISOLATED_TENANTS['PROVIDER'] must be a dotted path")
    master_alias = str(config.get("MASTER_ALIAS", "default")).strip()
    if not master_alias:
        raise ImproperlyConfigured("ISOLATED_TENANTS['MASTER_ALIAS'] must be non-empty")
    master_models: set[str] = set()
    for label in config.get("MASTER_MODELS", ()):
        normalized = str(label).strip().lower()
        if normalized.count(".") != 1 or any(not part for part in normalized.split(".")):
            raise ImproperlyConfigured("ISOLATED_TENANTS['MASTER_MODELS'] entries must be app_label.model_name")
        master_models.add(normalized)
    master_apps: set[str] = set()
    for label in config.get("MASTER_APPS", ()):
        normalized = str(label).strip().lower()
        if not normalized:
            raise ImproperlyConfigured("ISOLATED_TENANTS['MASTER_APPS'] entries must be non-empty")
        master_apps.add(normalized)
    return IsolatedTenantSettings(
        provider_path=provider,
        master_alias=master_alias,
        master_models=frozenset(master_models),
        master_apps=frozenset(master_apps),
        excluded_paths=tuple(str(pattern) for pattern in config.get("EXCLUDED_PATHS", ())),
        tenant_attribute=str(config.get("TENANT_ATTRIBUTE", "tenant")),
        database_attribute=str(config.get("DATABASE_ATTRIBUTE", "tenant_database_alias")),
    )


@lru_cache(maxsize=1)
def get_provider() -> TenantProvider:
    loaded: Any = import_string(get_settings().provider_path)
    provider: Any = loaded() if isinstance(loaded, type) else loaded
    for method in ("resolve_request", "get_database", "iter_databases", "iter_tenants"):
        if not callable(getattr(provider, method, None)):
            raise ImproperlyConfigured(f"Tenant provider must define {method}()")
    return provider


def iter_tenants(provider: TenantProvider | None = None) -> list[Tenant]:
    value = provider or get_provider()
    return list(value.iter_tenants())
