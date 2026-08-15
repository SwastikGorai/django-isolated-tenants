from types import SimpleNamespace

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

from django_isolated_tenants.conf import get_provider, get_settings, iter_tenants


@pytest.fixture(autouse=True)
def clear_configuration_caches() -> None:
    get_provider.cache_clear()
    get_settings.cache_clear()
    yield
    get_provider.cache_clear()
    get_settings.cache_clear()


@pytest.mark.parametrize(
    ("config", "message"),
    [
        ({}, "PROVIDER"),
        ({"PROVIDER": "tests.provider.provider", "MASTER_ALIAS": "  "}, "MASTER_ALIAS"),
        ({"PROVIDER": "tests.provider.provider", "MASTER_MODELS": ["invalid"]}, "MASTER_MODELS"),
        ({"PROVIDER": "tests.provider.provider", "MASTER_APPS": ["  "]}, "MASTER_APPS"),
    ],
)
def test_invalid_settings_are_rejected(config: dict[str, object], message: str) -> None:
    with override_settings(ISOLATED_TENANTS=config), pytest.raises(ImproperlyConfigured, match=message):
        get_settings()


def test_settings_are_normalized_and_defaults_are_applied() -> None:
    config = {
        "PROVIDER": "tests.provider.Provider",
        "MASTER_MODELS": [" Auth.User "],
        "MASTER_APPS": [" Admin "],
    }
    with override_settings(ISOLATED_TENANTS=config):
        value = get_settings()
        assert value.master_alias == "default"
        assert value.master_models == frozenset({"auth.user"})
        assert value.master_apps == frozenset({"admin"})
        assert get_provider().__class__.__name__ == "Provider"


def test_provider_contract_is_validated() -> None:
    incomplete = SimpleNamespace(resolve_request=lambda request: None)
    with (
        override_settings(ISOLATED_TENANTS={"PROVIDER": "tests.provider.provider"}),
        pytest.MonkeyPatch.context() as monkeypatch,
    ):
        monkeypatch.setattr("django_isolated_tenants.conf.import_string", lambda path: incomplete)
        with pytest.raises(ImproperlyConfigured, match=r"get_database\(\)"):
            get_provider()


def test_iter_tenants_materializes_provider_iterable() -> None:
    provider = SimpleNamespace(iter_tenants=lambda: (value for value in ("one", "two")))
    assert iter_tenants(provider) == ["one", "two"]
