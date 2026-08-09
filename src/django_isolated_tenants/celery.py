from collections.abc import Callable, Mapping
from typing import Any, TypeVar, cast

try:
    from celery import Task, shared_task
    from celery.result import GroupResult
    from celery.utils import uuid
    from celery.utils.threads import LocalStack
except ImportError as error:  # pragma: no cover
    raise ImportError("Install django-isolated-tenants[celery] to use Celery integration") from error

from .conf import get_provider, iter_tenants
from .connections import register_database, remove_database
from .context import get_current_tenant, tenant_context
from .exceptions import TenantContextMissing, TenantTaskMetadataInvalid
from .types import Tenant

_HEADER = "django_isolated_tenants"
_HEADER_VERSION = 1
_F = TypeVar("_F", bound=Callable[..., Any])


def _metadata(tenant: Tenant) -> dict[str, Any]:
    if not tenant.identifier or not tenant.database_alias:
        raise TenantTaskMetadataInvalid("Tenant task metadata requires identifier and database_alias")
    return {"version": _HEADER_VERSION, "identifier": tenant.identifier, "database_alias": tenant.database_alias}


def _tenant_from_headers(headers: Mapping[str, Any] | None) -> Tenant:
    if headers is None or _HEADER not in headers:
        raise TenantContextMissing("Cannot execute a tenant task without serialized tenant context")
    value = headers[_HEADER]
    if not isinstance(value, dict) or value.get("version") != _HEADER_VERSION:
        raise TenantTaskMetadataInvalid("Tenant task metadata is malformed or has an unsupported version")
    identifier, alias = value.get("identifier"), value.get("database_alias")
    if not isinstance(identifier, str) or not identifier or not isinstance(alias, str) or not alias:
        raise TenantTaskMetadataInvalid("Tenant task metadata requires non-empty identifier and database_alias")
    return Tenant(identifier, alias)


def _validate_headers(options: dict[str, Any], trusted_tenant: Tenant | None = None) -> dict[str, Any]:
    headers = dict(options.pop("headers", {}) or {})
    if _HEADER in headers:
        if trusted_tenant is None or headers[_HEADER] != _metadata(trusted_tenant):
            raise TenantTaskMetadataInvalid(f"The reserved '{_HEADER}' header is managed by django-isolated-tenants")
        headers.pop(_HEADER)
    return headers


class TenantTask(Task):
    abstract = True
    request_stack = LocalStack()

    def _apply_for_tenant(
        self, tenant: Tenant, args: Any = None, kwargs: Any = None, allow_existing_header: bool = False, **options: Any
    ) -> Any:
        headers = _validate_headers(options, tenant if allow_existing_header else None)
        headers[_HEADER] = _metadata(tenant)
        return super().apply_async(args=args, kwargs=kwargs, headers=headers, **options)

    def apply_async(self, args: Any = None, kwargs: Any = None, **options: Any) -> Any:
        tenant = get_current_tenant()
        if tenant is None:
            raise TenantContextMissing("Cannot schedule a tenant task without tenant context")
        return self._apply_for_tenant(tenant, args=args, kwargs=kwargs, allow_existing_header=True, **options)

    def apply_async_for_tenant(self, tenant: Tenant, args: Any = None, kwargs: Any = None, **options: Any) -> Any:
        if not isinstance(tenant, Tenant):
            raise TypeError("apply_async_for_tenant() requires a Tenant")
        return self._apply_for_tenant(tenant, args=args, kwargs=kwargs, **options)

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        request = self.request_stack.top
        tenant = _tenant_from_headers(getattr(request, "headers", None))
        provider = get_provider()
        database = provider.get_database(tenant.database_alias)
        if database.alias != tenant.database_alias:
            raise TenantTaskMetadataInvalid("Tenant provider returned a mismatched database alias")
        register_database(database)
        try:
            with tenant_context(tenant):
                return super().__call__(*args, **kwargs)
        finally:
            remove_database(tenant.database_alias)


class AllTenantsTask(Task):
    abstract = True
    tenant_task: TenantTask | None = None

    def apply_async(self, args: Any = None, kwargs: Any = None, **options: Any) -> Any:
        if options.get("task_id") is not None:
            raise ValueError("all_tenants_task does not accept a single task_id for fan-out")
        if any(options.get(key) is not None for key in ("link", "link_error", "chain", "chord")):
            raise ValueError(
                "all_tenants_task does not support direct chain/chord/link options; compose its GroupResult"
            )
        headers = _validate_headers(options)
        tenants = iter_tenants()
        seen_ids: set[str] = set()
        seen_aliases: set[str] = set()
        child_task = self.tenant_task
        if child_task is None:
            raise RuntimeError("all_tenants_task has no tenant child task")
        group_id = uuid()
        results = []
        provider = get_provider()
        for tenant in tenants:
            if (
                not isinstance(tenant.identifier, str)
                or not tenant.identifier
                or not isinstance(tenant.database_alias, str)
                or not tenant.database_alias
            ):
                raise TenantTaskMetadataInvalid("Tenant fleet contains an empty identifier or database alias")
            if tenant.identifier in seen_ids or tenant.database_alias in seen_aliases:
                raise TenantTaskMetadataInvalid("Tenant fleet contains duplicate identifiers or database aliases")
            database = provider.get_database(tenant.database_alias)
            if database.alias != tenant.database_alias:
                raise TenantTaskMetadataInvalid("Tenant provider returned a mismatched database alias")
            seen_ids.add(tenant.identifier)
            seen_aliases.add(tenant.database_alias)
        for tenant in tenants:
            child_options = dict(options)
            child_options["headers"] = headers
            child_options["group_id"] = group_id
            results.append(child_task._apply_for_tenant(tenant, args=args, kwargs=kwargs, **child_options))
        return GroupResult(group_id, results, app=self.app)


def tenant_task(function: _F | None = None, **options: Any) -> Any:
    def decorate(target: _F) -> Any:
        return shared_task(base=TenantTask, **options)(target)

    return decorate(cast(_F, function)) if function is not None else decorate


def all_tenants_task(function: _F | None = None, **options: Any) -> Any:
    def decorate(target: _F) -> Any:
        public_name = options.get("name") or f"{target.__module__}.{target.__name__}"
        child_options = {**options, "name": f"{public_name}.__tenant"}
        child = shared_task(base=TenantTask, **child_options)(target)

        def dispatch(*args: Any, **kwargs: Any) -> Any:
            return target(*args, **kwargs)

        dispatch.__module__ = target.__module__
        dispatch.__name__ = target.__name__
        task = shared_task(base=AllTenantsTask, **{**options, "name": public_name})(dispatch)
        task.tenant_task = child
        return task

    return decorate(cast(_F, function)) if function is not None else decorate


__all__ = ["AllTenantsTask", "TenantTask", "all_tenants_task", "tenant_task"]
