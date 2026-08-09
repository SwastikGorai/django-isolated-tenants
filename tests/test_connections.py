from concurrent.futures import ThreadPoolExecutor

import pytest
from django.db import connections

from django_isolated_tenants import TenantDatabase, TenantDatabaseInvalid
from django_isolated_tenants.connections import redacted_config, register_database, remove_database


def tenant_database(alias: str = "dynamic") -> TenantDatabase:
    return TenantDatabase(alias, {"ENGINE": "django.db.backends.postgresql", "NAME": alias, "PASSWORD": "secret"})


def test_registration_copies_reuses_and_removes_configuration() -> None:
    database = tenant_database()
    register_database(database)
    assert connections.databases["dynamic"]["NAME"] == "dynamic"
    assert register_database(database) == "dynamic"
    remove_database("dynamic")
    assert "dynamic" not in connections.databases


def test_invalid_and_conflicting_configurations_fail() -> None:
    with pytest.raises(TenantDatabaseInvalid):
        register_database(TenantDatabase("bad", {"ENGINE": "django.db.backends.sqlite3", "NAME": "x"}))
    register_database(tenant_database())
    with pytest.raises(TenantDatabaseInvalid):
        register_database(TenantDatabase("dynamic", {"ENGINE": "django.db.backends.postgresql", "NAME": "other"}))
    remove_database("dynamic")


def test_first_registration_is_thread_safe() -> None:
    database = tenant_database()
    with ThreadPoolExecutor(max_workers=4) as executor:
        assert list(executor.map(register_database, [database] * 8)) == ["dynamic"] * 8
    remove_database("dynamic")


def test_redaction_does_not_expose_credentials() -> None:
    assert redacted_config(tenant_database().config)["PASSWORD"] == "<redacted>"
