from collections.abc import Mapping
from copy import deepcopy
from threading import RLock
from typing import Any

from django.db import connections

from .conf import get_settings
from .exceptions import TenantDatabaseInvalid
from .types import TenantDatabase

_lock = RLock()
_owned_aliases: set[str] = set()


def _validated_config(database: TenantDatabase) -> dict[str, Any]:
    master_alias = get_settings().master_alias
    if not database.alias or database.alias == master_alias:
        raise TenantDatabaseInvalid(
            f"Tenant database alias must be non-empty and cannot be the master alias '{master_alias}'"
        )
    config = deepcopy(dict(database.config))
    engine = config.get("ENGINE")
    if engine != "django.db.backends.postgresql":
        raise TenantDatabaseInvalid("Only django.db.backends.postgresql is supported")
    if not config.get("NAME"):
        raise TenantDatabaseInvalid("Tenant database configuration requires NAME")
    defaults: dict[str, Any] = {
        "ATOMIC_REQUESTS": False,
        "AUTOCOMMIT": True,
        "CONN_MAX_AGE": 0,
        "CONN_HEALTH_CHECKS": False,
        "OPTIONS": {},
        "TIME_ZONE": None,
        "USER": "",
        "PASSWORD": "",
        "HOST": "",
        "PORT": "",
        "TEST": {},
    }
    for key, value in defaults.items():
        config.setdefault(key, value)
    return config


def register_database(database: TenantDatabase) -> str:
    config = _validated_config(database)
    with _lock:
        existing = connections.databases.get(database.alias)
        if existing is not None:
            if existing != config:
                raise TenantDatabaseInvalid(f"Database alias '{database.alias}' is already registered differently")
            _owned_aliases.add(database.alias)
            return database.alias
        connections.databases[database.alias] = config
        _owned_aliases.add(database.alias)
    return database.alias


def remove_database(alias: str) -> None:
    with _lock:
        if alias not in _owned_aliases or alias == get_settings().master_alias:
            return
        try:
            if alias in connections.databases:
                try:
                    connections[alias].close()
                except Exception:
                    pass
        finally:
            connections.databases.pop(alias, None)
            _owned_aliases.discard(alias)
            local = connections._connections  # noqa: SLF001 - Django exposes no dynamic-alias removal API.
            if hasattr(local, alias):
                delattr(local, alias)


def registered_database_aliases() -> frozenset[str]:
    with _lock:
        return frozenset(_owned_aliases)


def redacted_config(config: Mapping[str, object]) -> dict[str, object]:
    sensitive = {"PASSWORD", "OPTIONS", "USER", "HOST"}
    return {key: ("<redacted>" if key.upper() in sensitive else value) for key, value in config.items()}
