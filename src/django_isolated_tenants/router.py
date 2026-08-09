from typing import Any

from django.core.exceptions import ImproperlyConfigured

from .classification import ModelScope, classify_model
from .conf import get_settings
from .connections import registered_database_aliases
from .context import get_current_database_alias
from .exceptions import TenantContextMissing


class TenantRouter:
    """Route master models to the master DB and tenant models to their context."""

    def _scope(self, model: Any, app_label: str | None = None, model_name: str | None = None) -> ModelScope:
        meta = getattr(model, "_meta", None)
        return classify_model(
            app_label or getattr(meta, "app_label", ""),
            model_name or getattr(meta, "model_name", None),
            model,
        )

    def _route(self, model: Any) -> str | None:
        scope = self._scope(model)
        if scope is ModelScope.MASTER:
            return get_settings().master_alias
        if scope is ModelScope.DEFAULT:
            return None
        alias = get_current_database_alias()
        if alias is None:
            raise TenantContextMissing(f"No tenant context for {model._meta.label_lower}")
        return alias

    def db_for_read(self, model: type[Any], **hints: object) -> str | None:
        return self._route(model)

    def db_for_write(self, model: type[Any], **hints: object) -> str | None:
        alias = self._route(model)
        if alias is not None and alias.lower().endswith(("_replica", "-replica")):
            raise TenantContextMissing("Tenant writes cannot target a replica-style alias")
        return alias

    def allow_relation(self, obj1: Any, obj2: Any, **hints: object) -> bool | None:
        scope1 = self._scope(obj1)
        scope2 = self._scope(obj2)
        if ModelScope.DEFAULT in {scope1, scope2}:
            return None
        if scope1 is not scope2:
            return False
        database1 = getattr(obj1._state, "db", None)
        database2 = getattr(obj2._state, "db", None)
        if database1 is not None and database2 is not None:
            return database1 == database2
        if scope1 is ModelScope.MASTER:
            return True
        if get_current_database_alias() is not None:
            return True
        return None

    def allow_migrate(self, db: str, app_label: str, model_name: str | None = None, **hints: object) -> bool | None:
        scope_hint = hints.get("isolated_tenants_scope")
        if scope_hint is not None:
            if scope_hint not in {"master", "tenant"}:
                raise ImproperlyConfigured("isolated_tenants_scope must be 'master' or 'tenant'")
            scope = ModelScope(scope_hint)
        else:
            model = hints.get("model")
            scope = classify_model(app_label, model_name, model)
        if scope is ModelScope.DEFAULT:
            return None
        master = get_settings().master_alias
        if db == master:
            return scope is ModelScope.MASTER
        if db in registered_database_aliases():
            return scope is ModelScope.TENANT
        return None
