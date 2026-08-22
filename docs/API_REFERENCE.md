# django-isolated-tenants

Database-per-tenant routing for Django 5.2 and PostgreSQL. This document describes the public API of `django-isolated-tenants` - its settings, model bases, context helpers, database router, middleware, Celery integration, system checks and management commands. It is intended as a reference for application developers integrating the package.

The notation used here follows the [Django documentation](https://docs.djangoproject.com/en/5.2/) conventions: fully-qualified Python paths, signature blocks, and ``Note`` / ``Warning`` admonitions.

> **Requires:** Python 3.11 or 3.12, Django 5.2, PostgreSQL for tenant databases, Celery 5.3 or newer for task integration. Install with ``pip install "django-isolated-tenants[postgres,celery]"``.

## Contents

- [Quick start](#quick-start)
- [Settings](#settings)
- [Provider interface](#provider-interface)
- [Model bases](#model-bases)
- [Model classification](#model-classification)
- [Tenant context](#tenant-context)
- [Connection registry](#connection-registry)
- [Database router](#database-router)
- [Middleware](#middleware)
- [Celery tasks](#celery-tasks)
- [System checks](#system-checks)
- [Application configuration](#application-configuration)
- [Exceptions](#exceptions)
- [Management commands](#management-commands)

---

## Quick start

A complete integration touches five places in your project:

1. **Install and configure** - add ``django_isolated_tenants`` to ``INSTALLED_APPS``:

   ```python
   INSTALLED_APPS = [
       # ...
       "django_isolated_tenants",
   ]
   ```

2. **Implement a provider** - a small class that maps requests to tenants and aliases to database credentials (see [Provider interface](#provider-interface)).

3. **Wire the router** - route master/tenant models to the correct database:

   ```python
   DATABASE_ROUTERS = ["django_isolated_tenants.router.TenantRouter"]
   ```

4. **Add the middleware** - resolve the tenant per request and hold the tenant context:

   ```python
   MIDDLEWARE = [
       "django.middleware.security.SecurityMiddleware",
       # ... host validation, common middleware, ...
       "django_isolated_tenants.middleware.TenantMiddleware",
       # ... everything downstream that touches tenant models ...
   ]
   ```

5. **Declare your models** with an explicit scope:

   ```python
   from django.db import models
   from django_isolated_tenants import MasterModel, TenantModel

   class TenantRegistry(MasterModel):  # lives on the control-plane DB
       tenant_id = models.CharField(max_length=64, unique=True)
       database_alias = models.CharField(max_length=64, unique=True)

   class Invoice(TenantModel):  # lives on each tenant DB
       amount = models.DecimalField(max_digits=10, decimal_places=2)
   ```

After that, migrate the master database with ``python manage.py migrate`` and the tenant fleet with ``python manage.py migrate_tenants``.

---

## Settings

All package settings live under the ``ISOLATED_TENANTS`` dictionary in your Django settings module. The settings are read by ``django_isolated_tenants.conf.get_settings()`` and cached for the lifetime of the process.

Add the application, middleware and router to your project settings. The middleware should be placed after security or host-validation middleware and before any code that accesses tenant models.

```python
# settings.py
INSTALLED_APPS = [
    # ...
    "django_isolated_tenants",
]

MIDDLEWARE = [
    # ...
    "django_isolated_tenants.middleware.TenantMiddleware",
]

DATABASE_ROUTERS = [
    "django_isolated_tenants.router.TenantRouter",
]

ISOLATED_TENANTS = {
    "PROVIDER": "myproject.tenants.provider",
    "MASTER_ALIAS": "default",
    "MASTER_APPS": [],
    "MASTER_MODELS": ["legacy.controlmodel"],
    "EXCLUDED_PATHS": [r"^/health/$"],
}
```

### `ISOLATED_TENANTS`

A dictionary with the following keys:

| Key | Type | Default | Description |
|---|---|---|---|
| ``PROVIDER`` | ``str`` | (required) | Dotted path to the tenant provider. |
| ``MASTER_ALIAS`` | ``str`` | ``"default"`` | Alias of the control-plane database in ``DATABASES``. |
| ``MASTER_APPS`` | iterable of ``str`` | ``()`` | App labels whose models always live on the master database. |
| ``MASTER_MODELS`` | iterable of ``str`` | ``()`` | ``"app_label.model_name"`` entries for individual master models. |
| ``EXCLUDED_PATHS`` | iterable of ``str`` | ``()`` | Regex patterns; matching requests skip tenant resolution. |
| ``TENANT_ATTRIBUTE`` | ``str`` | ``"tenant"`` | Request attribute holding the resolved ``Tenant``. |
| ``DATABASE_ATTRIBUTE`` | ``str`` | ``"tenant_database_alias"`` | Request attribute holding the resolved alias. |

#### `PROVIDER`

*Required.* A dotted Python path to an object that implements the tenant provider interface (see [Provider interface](#provider-interface) below). The path may point to an instance or to a class; if it points to a class, it will be instantiated with no arguments.

If the value is not a non-empty string, ``django.core.exceptions.ImproperlyConfigured`` is raised when the settings are accessed.

```python
ISOLATED_TENANTS = {
    # Module-level instance:
    "PROVIDER": "myproject.tenants.provider",
    # ... or a class, instantiated lazily on first use:
    "PROVIDER": "myproject.tenants.provider.ProjectTenantProvider",
}
```

#### `MASTER_ALIAS`

The alias of the master (control-plane) database in ``DATABASES``. Defaults to ``"default"``. The value is stripped of surrounding whitespace and must be non-empty; otherwise ``ImproperlyConfigured`` is raised.

The master alias is used by the router (``MASTER`` models route here), by ``allow_migrate`` (only ``MASTER``-scoped migrations may apply here), by the connection registry (tenant aliases must differ from it) and by ``check_tenant_layout`` (the database that is introspected for master tables).

#### `MASTER_APPS`

An iterable of application labels whose models are always placed on the master database. Each entry is normalised with ``str(label).strip().lower()`` and must be non-empty; an empty entry raises ``ImproperlyConfigured``. Defaults to an empty collection.

``MASTER_APPS`` takes precedence over ``MASTER_MODELS`` and over the model-base markers (see [Model classification](#model-classification)) - an app listed here is placed on master wholesale, even if some of its models inherit ``TenantModel``.

> **Note:** The package provides no default master applications. ``auth``, ``contenttypes`` and ``admin`` are related through foreign keys and should not be split between databases without careful consideration. Choose master applications explicitly for your project.

#### `MASTER_MODELS`

An iterable of ``"app_label.ModelName"`` strings for individual models that are placed on the master database. This is primarily an escape hatch for legacy or third-party models that cannot inherit from ``MasterModel``. Each entry is normalised to lower case, must contain exactly one ``"."`` and must have non-empty parts on both sides; otherwise ``ImproperlyConfigured`` is raised. Defaults to an empty collection.

Because normalisation lower-cases the whole entry, ``"legacy.ControlModel"`` and ``"legacy.controlmodel"`` are equivalent - Django's default ``model_name`` is already lower case.

#### `EXCLUDED_PATHS`

An iterable of regular-expression strings. If ``request.path_info`` matches any of these patterns, the middleware skips tenant resolution for that request. Defaults to ``()``.

The patterns are compiled once at middleware construction and applied with ``re.search``, so they match anywhere in the path unless you anchor them yourself. Use ``^`` (and optionally ``$``) to pin them to the start (end) of the path:

```python
ISOLATED_TENANTS = {
    # ...
    "EXCLUDED_PATHS": [
        r"^/health/$",      # exactly /health/
        r"^/static/",       # anything under /static/
        r"^/api/public/",   # anything under /api/public/
    ],
}
```

Excluded requests run *without* a tenant context: the request is passed straight to ``get_response``, no database is registered and no ``Tenant`` attribute is set. Accessing tenant-scoped models in such views raises ``TenantContextMissing``.

#### `TENANT_ATTRIBUTE`

The attribute name under which the resolved ``Tenant`` instance is attached to the request object. Defaults to ``"tenant"``. The value is coerced with ``str()``.

```python
def dashboard(request):
    tenant = getattr(request, "tenant")  # the default attribute name
    ...
```

#### `DATABASE_ATTRIBUTE`

The attribute name under which the resolved database alias is attached to the request object. Defaults to ``"tenant_database_alias"``. The value is coerced with ``str()``.

### `django_isolated_tenants.conf.get_settings()`

```python
get_settings() -> IsolatedTenantSettings
```

Returns the parsed ``IsolatedTenantSettings`` dataclass. The result is cached with ``functools.lru_cache`` (``maxsize=1``); the function performs no database queries and touches no model state.

Validation performed on first access:

| Condition | Exception |
|---|---|
| ``PROVIDER`` missing or not a non-empty ``str`` | ``ImproperlyConfigured("ISOLATED_TENANTS['PROVIDER'] must be a dotted path")`` |
| ``MASTER_ALIAS`` empty after stripping | ``ImproperlyConfigured("ISOLATED_TENANTS['MASTER_ALIAS'] must be non-empty")`` |
| A ``MASTER_MODELS`` entry without exactly one ``"."`` or with an empty side | ``ImproperlyConfigured("ISOLATED_TENANTS['MASTER_MODELS'] entries must be app_label.model_name")`` |
| A ``MASTER_APPS`` entry empty after normalisation | ``ImproperlyConfigured("ISOLATED_TENANTS['MASTER_APPS'] entries must be non-empty")`` |

When settings are overridden in tests (for example with ``override_settings``), clear the cache:

```python
from django.test import override_settings
from django_isolated_tenants.conf import get_settings, get_provider

@override_settings(ISOLATED_TENANTS={...})
def test_example():
    get_settings.cache_clear()
    get_provider.cache_clear()
    # ...
    get_settings.cache_clear()
    get_provider.cache_clear()
```

> **Note:** Clear both caches. ``get_provider()`` calls ``get_settings()`` and is itself cached, so clearing only the settings cache leaves a stale provider behind.

### `django_isolated_tenants.conf.get_provider()`

```python
get_provider() -> TenantProvider
```

Imports and returns the configured provider instance. The path is resolved with ``django.utils.module_loading.import_string``. If the imported object is a class, it is instantiated with no arguments; otherwise the object itself is used. The result is cached with ``functools.lru_cache``.

Before returning, each of the four interface methods (``resolve_request``, ``get_database``, ``iter_databases``, ``iter_tenants``) is checked with ``callable()``; a missing method raises ``ImproperlyConfigured("Tenant provider must define <method>()")``. The check is structural only - signature and return types are validated lazily wherever the provider is consumed (see the invariants in [Provider interface](#provider-interface)).

### `django_isolated_tenants.conf.iter_tenants()`

```python
iter_tenants(provider=None) -> list[Tenant]
```

Returns ``list(provider.iter_tenants())``. If *provider* is ``None``, the configured provider from ``get_provider()`` is used. This helper is used by the fleet commands and by ``AllTenantsTask`` to obtain a snapshot of the tenant fleet.

Consuming a snapshot materialises it into a list, so later changes to the provider's backing store do not affect an in-flight fan-out.

### `IsolatedTenantSettings`

```python
@dataclass(frozen=True, slots=True)
class IsolatedTenantSettings:
    provider_path: str
    master_alias: str
    master_models: frozenset[str]
    master_apps: frozenset[str]
    excluded_paths: tuple[str, ...]
    tenant_attribute: str
    database_attribute: str
```

An immutable value object returned by ``get_settings()``. All ``master_*`` collections are normalised to lower case. Because every field is a ``str``, ``frozenset`` or ``tuple``, instances are hashable and compare by value, which makes them convenient in tests:

```python
from django_isolated_tenants.conf import get_settings

def test_settings_normalised():
    config = get_settings()
    assert config.master_models == frozenset({"legacy.controlmodel"})
    assert config.excluded_paths == (r"^/health/$",)
```

---

## Provider interface

The provider is the single integration point that the package delegates to your application for tenant resolution and credential lookup. Credentials are never serialised into task headers; only the tenant identifier and database alias are transmitted.

### `django_isolated_tenants.types.TenantProvider`

```python
@runtime_checkable
class TenantProvider(Protocol):
    def resolve_request(self, request: HttpRequest) -> Tenant | None: ...
    def get_database(self, alias: str) -> TenantDatabase: ...
    def iter_databases(self) -> list[TenantDatabase] | tuple[TenantDatabase, ...]: ...
    def iter_tenants(self) -> Iterable[Tenant]: ...
```

You must implement all four methods. The protocol is ``runtime_checkable``, so structural implementations satisfy ``isinstance(provider, TenantProvider)`` without inheritance. When each method is called:

| Method | Called by | Frequency |
|---|---|---|
| ``resolve_request(request)`` | ``TenantMiddleware``, once per non-excluded request | Hot path - keep it fast (one indexed query is typical). |
| ``get_database(alias)`` | Middleware, Celery workers (web *and* worker processes), fleet validation | Hot path on workers; must be deterministic. |
| ``iter_databases()`` | ``migrate_tenants``, ``show_tenant_migrations``, ``check_tenant_layout`` | Once per command invocation. |
| ``iter_tenants()`` | ``all_tenants_task`` dispatch, fleet helpers | Once per fan-out dispatch. |

A full implementation, backed by a registry model on the master database:

```python
# myproject/tenants/provider.py
from django_isolated_tenants import Tenant, TenantDatabase

class ProjectTenantProvider:
    def resolve_request(self, request) -> Tenant | None:
        # Use subdomain, header or session to identify the tenant.
        host = request.get_host().split(":")[0]
        subdomain, _, domain = host.partition(".")
        if domain != "example.com" or not subdomain:
            return None
        from myproject.tenants.models import TenantRegistry
        entry = TenantRegistry.objects.filter(tenant_id=subdomain).first()
        if entry is None:
            return None
        return Tenant(identifier=entry.tenant_id, database_alias=entry.database_alias)

    def get_database(self, alias: str) -> TenantDatabase:
        # Looked up here on the web process AND on Celery workers;
        # must never query tenant databases.
        from myproject.tenants.models import TenantRegistry
        entry = TenantRegistry.objects.get(database_alias=alias)
        return TenantDatabase(alias, {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": entry.database_name,
            "HOST": entry.database_host,
            "PORT": entry.database_port,
            "USER": entry.database_user,
            "PASSWORD": entry.database_password,
        })

    def iter_databases(self) -> list[TenantDatabase]:
        # Used by migrate_tenants, show_tenant_migrations and
        # check_tenant_layout.
        from myproject.tenants.models import TenantRegistry
        return [self.get_database(entry.database_alias) for entry in TenantRegistry.objects.all()]

    def iter_tenants(self) -> Iterable[Tenant]:
        # Used by all_tenants_task and the fleet helpers.
        from myproject.tenants.models import TenantRegistry
        for entry in TenantRegistry.objects.all():
            yield Tenant(identifier=entry.tenant_id, database_alias=entry.database_alias)

provider = ProjectTenantProvider()
```

A minimal stub (useful for tests) looks like this:

```python
from django_isolated_tenants import Tenant, TenantDatabase

class ProjectTenantProvider:
    def resolve_request(self, request):
        # Return None if no tenant can be resolved (the middleware
        # will return HttpResponseNotFound for that request).
        ...

    def get_database(self, alias: str) -> TenantDatabase:
        return TenantDatabase(alias, {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": f"tenant_{alias}",
            # HOST, USER, PASSWORD, etc. are looked up here.
        })

    def iter_databases(self) -> list[TenantDatabase]:
        ...

    def iter_tenants(self) -> Iterable[Tenant]:
        ...

provider = ProjectTenantProvider()
```

Implementation rules:

* Provider methods must not establish a tenant context themselves; the middleware, task wrapper and commands own the context lifecycle.
* ``get_database()`` must return the same normalised configuration for the same alias across calls - the connection registry treats a configuration change for a live alias as an error (see [Connection registry](#connection-registry)).
* Only master-database queries are permitted inside the provider. Querying a tenant database from ``resolve_request()`` would recurse into the router.

The following invariants are enforced wherever a fleet snapshot is consumed (management commands and ``AllTenantsTask``):

* Identifiers and aliases are non-empty strings and are unique within the snapshot.
* Every ``tenant.database_alias`` can be resolved through ``get_database()`` and the returned ``TenantDatabase.alias`` matches the requested alias.
* ``get_database()`` must not return the master alias, its ``ENGINE`` must be ``"django.db.backends.postgresql"`` and ``NAME`` must be non-empty.

### `django_isolated_tenants.types.Tenant`

```python
@dataclass(frozen=True, slots=True)
class Tenant:
    identifier: str
    database_alias: str
```

An immutable value that identifies a tenant. *identifier* is the logical tenant name (for example ``"acme"``) and *database_alias* is the Django database alias (for example ``"customer_a"``). Instances are passed to ``tenant_context`` and to ``TenantTask.apply_async_for_tenant()``.

Being a frozen dataclass, instances have structural ``__eq__``, are hashable and reproduce usefully in tracebacks:

```python
tenant = Tenant(identifier="acme", database_alias="customer_a")
assert tenant.identifier == "acme"
assert Tenant("acme", "customer_a") == tenant
```

### `django_isolated_tenants.types.TenantDatabase`

```python
@dataclass(frozen=True, slots=True)
class TenantDatabase:
    alias: str
    config: Mapping[str, object]
```

A pairing of a database alias and the Django ``DATABASES`` entry for that alias. The *config* mapping is validated by ``connections._validated_config`` before registration; provider-supplied mappings are deep-copied, so later mutation of the source mapping never leaks into a registered connection.

---

## Model bases

The package provides two abstract model bases. Inheriting from them makes database placement explicit and migration-safe. The placement is recorded through a private manager that has ``use_in_migrations = True``, so historical models obtained from ``ModelState`` remain classifiable.

### `django_isolated_tenants.models.MasterModel`

```python
class MasterModel(models.Model):
    class Meta:
        abstract = True
```

Abstract base class for control-plane models. Tables for subclasses are created only on the master database. The class defines a private marker manager ``_isolated_tenants_scope_marker`` that does not replace the default ``objects`` manager.

### `django_isolated_tenants.models.TenantModel`

```python
class TenantModel(models.Model):
    class Meta:
        abstract = True
```

Abstract base class for tenant-scoped models. Tables for subclasses are created only on tenant databases. Accessing a ``TenantModel`` without an active tenant context raises ``TenantContextMissing``.

### How the marker works

Each base class attaches a dedicated ``models.Manager`` subclass (``_MasterModelMarkerManager`` / ``_TenantModelMarkerManager``) carrying ``_isolated_tenants_model_scope = "master"`` or ``"tenant"``. The classifier inspects ``model._meta.managers`` for that attribute, which means:

* The marker survives inheritance, including multi-level abstract bases.
* Because ``use_in_migrations = True``, Django serialises the manager into migration state files, so ``RunPython`` operations and the router's ``hints["model"]`` (a historical model) classify identically to the live model.
* Adding your own managers (including a custom default) does not interfere - the marker is an additional, private manager.

```python
class Invoice(TenantModel):
    objects = InvoiceQuerySet.as_manager()  # your manager stays the default
```

### Model placement summary

| Model declaration | Placement |
|---|---|
| Subclass of ``MasterModel`` | Master database only |
| Subclass of ``TenantModel`` | Tenant database (requires context, fail-closed) |
| Model whose ``app_label`` is in ``MASTER_APPS`` | Master database |
| Model whose ``app_label.ModelName`` is in ``MASTER_MODELS`` | Master database |
| Plain ``models.Model`` | Not handled by this router; defers to the next database router |

Example:

```python
from django_isolated_tenants import MasterModel, TenantModel

class TenantRegistry(MasterModel):
    tenant_id = models.CharField(max_length=64, unique=True)

class Invoice(TenantModel):
    amount = models.DecimalField(max_digits=10, decimal_places=2)
```

> **Warning:** Do not define database relations (``ForeignKey``, ``OneToOneField``, ``ManyToManyField``) that cross the master/tenant boundary. Such relations are reported by the system check ``isolated_tenants.E001``.

Both classes are re-exported from ``django_isolated_tenants`` and are also available from ``django_isolated_tenants.models``. They are loaded lazily through ``__getattr__`` so that importing ``django_isolated_tenants`` does not trigger Django model loading - keep ``django_isolated_tenants`` early in ``INSTALLED_APPS`` ordering considerations in mind only if you import model bases at module import time before ``django.setup()``.

---

## Model classification

Classification is pure - it does not touch the database or mutate settings - and is shared by the router, the system check and the ``check_tenant_layout`` command.

### `django_isolated_tenants.classification.ModelScope`

```python
class ModelScope(StrEnum):
    MASTER = "master"
    TENANT = "tenant"
    DEFAULT = "default"
```

``StrEnum`` members compare equal to their string values (``ModelScope.MASTER == "master"``), which simplifies assertions in tests.

### `django_isolated_tenants.classification.classify_model()`

```python
classify_model(app_label, model_name=None, model=None) -> ModelScope
```

Classifies a model by its application label, model name and optional model class. The precedence is:

1. If ``app_label.lower()`` is in ``MASTER_APPS``, return ``MASTER``.
2. If ``"app_label.model_name".lower()`` is in ``MASTER_MODELS``, return ``MASTER``.
3. If *model* carries a marker manager whose ``_isolated_tenants_model_scope`` is ``"master"`` or ``"tenant"``, return that scope (the check inspects ``model._meta.managers``).
4. Otherwise return ``DEFAULT``.

If *model_name* is ``None``, it falls back to ``model._meta.model_name``. *model* may be a live model class, a historical model from migration state, or ``None`` (labels-only classification, as used by ``allow_migrate`` when no model hint is available).

Worked examples (assuming ``MASTER_APPS = ()`` and ``MASTER_MODELS = ("legacy.controlmodel",)``):

| Call | Result | Reason |
|---|---|---|
| ``classify_model("legacy", "controlmodel")`` | ``MASTER`` | Exact match in ``MASTER_MODELS``. |
| ``classify_model("legacy", "ControlModel")`` | ``MASTER`` | Label lower-cased before matching. |
| ``classify_model("billing", "invoice", Invoice)`` | ``TENANT`` | Marker manager on ``Invoice(TenantModel)``. |
| ``classify_model("billing", "invoice")`` | ``DEFAULT`` | No model hint → no marker inspection. |
| ``classify_model("billing", "invoice", None)`` | ``DEFAULT`` | Explicit ``None`` behaves the same. |

> **Note:** Because settings take precedence over markers, ``MASTER_APPS`` and ``MASTER_MODELS`` can *override* a model base - but only toward ``MASTER``. There is no setting that moves a ``MasterModel`` subclass onto tenant databases.

---

## Tenant context

The tenant context is stored in a ``contextvars.ContextVar`` and is therefore safe for synchronous, asynchronous and concurrent execution. It is the mechanism that connects the current request or task to a tenant database.

Each ``asyncio`` task, thread and Celery job sees its own copy of the context: setting a tenant in one coroutine never leaks into another. The context does **not** propagate to threads you start manually - establish it inside the thread with ``tenant_context`` if needed.

### `django_isolated_tenants.context.tenant_context()`

```python
@contextmanager
def tenant_context(tenant: Tenant) -> Iterator[Tenant]:
```

Context manager that establishes the given *tenant* for the duration of the ``with`` block. The manager yields the tenant, so ``as`` bindings work. The previous context is restored on exit, even if the block raises an exception. Contexts may be nested - the inner block shadows the outer one, and the outer tenant is restored afterwards.

```python
from django_isolated_tenants import Tenant, tenant_context

tenant = Tenant(identifier="acme", database_alias="customer_a")

with tenant_context(tenant) as active:
    Invoice.objects.create(amount=100)
# context is cleared here
```

Nesting example:

```python
with tenant_context(Tenant("acme", "customer_a")):
    with tenant_context(Tenant("globex", "customer_b")):
        assert get_current_tenant_id() == "globex"
    assert get_current_tenant_id() == "acme"
```

Code that runs outside the request/middleware path - for example management commands or standalone scripts - should use this helper to establish a tenant:

```python
# standalone script
import django

django.setup()

from django_isolated_tenants import Tenant, tenant_context

with tenant_context(Tenant("acme", "customer_a")):
    ...  # run tenant work
```

### `django_isolated_tenants.context.get_current_tenant()`

```python
get_current_tenant() -> Tenant | None
```

Returns the active ``Tenant`` or ``None`` if no context is established. This is the same object that was passed to ``tenant_context``.

### `django_isolated_tenants.context.get_current_tenant_id()`

```python
get_current_tenant_id() -> str | None
```

Returns the identifier of the active tenant, or ``None``.

### `django_isolated_tenants.context.get_current_database_alias()`

```python
get_current_database_alias() -> str | None
```

Returns the database alias of the active tenant, or ``None``. The database router uses this helper to determine where tenant model queries should be sent.

### `django_isolated_tenants.context.clear_tenant_context()`

```python
clear_tenant_context() -> None
```

Clears the current tenant context. The middleware calls this automatically after each request; it is also useful in tests and in manual cleanup code.

> **Note:** ``clear_tenant_context()`` sets the context to ``None``; it does not unwind ``tenant_context`` tokens. Prefer letting the context manager exit naturally, and use the clear function for teardown in framework code or test fixtures.

### Using the context in tests

A pytest fixture is the most ergonomic way to expose a tenant to a test:

```python
import pytest
from django_isolated_tenants import Tenant, tenant_context

@pytest.fixture
def tenant_acme(db):
    with tenant_context(Tenant("acme", "customer_a")) as tenant:
        yield tenant
```

---

## Connection registry

Tenant databases are registered dynamically at request or task execution time. The registry is protected by a re-entrant lock and tracks which aliases it owns.

The underlying helper ``_validated_config`` deep-copies the provider-supplied mapping, checks that the alias is non-empty and not the master alias, requires ``ENGINE == "django.db.backends.postgresql"`` and a non-empty ``NAME``, and fills in the connection keys that Django expects:

| Key | Default |
|---|---|
| ``ATOMIC_REQUESTS`` | ``False`` |
| ``AUTOCOMMIT`` | ``True`` |
| ``CONN_MAX_AGE`` | ``0`` |
| ``CONN_HEALTH_CHECKS`` | ``False`` |
| ``OPTIONS`` | ``{}`` |
| ``TIME_ZONE`` | ``None`` |
| ``USER`` | ``""`` |
| ``PASSWORD`` | ``""`` |
| ``HOST`` | ``""`` |
| ``PORT`` | ``""`` |
| ``TEST`` | ``{}`` |

All defaults are applied with ``setdefault`` - values present in the provider config are preserved.

Validation failures raise ``TenantDatabaseInvalid`` with a message that contains no secret values:

| Condition | Message |
|---|---|
| Empty alias or alias equal to the master alias | ``Tenant database alias must be non-empty and cannot be the master alias '<master>'`` |
| Engine other than PostgreSQL | ``Only django.db.backends.postgresql is supported`` |
| Missing or empty ``NAME`` | ``Tenant database configuration requires NAME`` |
| Alias already registered with a different config | ``Database alias '<alias>' is already registered differently`` |

### `django_isolated_tenants.connections.register_database()`

```python
register_database(database: TenantDatabase) -> str
```

Validates and inserts the database into ``django.db.connections.databases``. If the same alias is registered again with an identical normalised configuration, the call is idempotent. If the alias already exists with a different configuration, ``TenantDatabaseInvalid`` is raised without including secret values in the message. Returns the alias.

```python
from django_isolated_tenants.connections import register_database
from django_isolated_tenants import TenantDatabase

register_database(TenantDatabase(alias="customer_a", config={
    "ENGINE": "django.db.backends.postgresql",
    "NAME": "tenant_acme",
}))
```

The middleware registers databases at request time and never removes them - re-registration across requests is the idempotent path. Fleet commands and the Celery task wrapper remove databases when they finish (see below).

### `django_isolated_tenants.connections.remove_database()`

```python
remove_database(alias: str) -> None
```

Removes the alias if it is owned by this package and is not the master alias. The function closes the underlying connection (any error during close is suppressed), removes the entry from ``connections.databases`` and discards the alias from the owned set. If the alias is not owned, the call is a no-op - you can call it unconditionally in cleanup paths. Fleet commands, the Celery task wrapper and tests call this in ``finally`` blocks.

### `django_isolated_tenants.connections.registered_database_aliases()`

```python
registered_database_aliases() -> frozenset[str]
```

Returns a snapshot of the aliases owned by this package. The router uses this to distinguish tenant databases from unrelated aliases in ``allow_migrate``.

### `django_isolated_tenants.connections.redacted_config()`

```python
redacted_config(config: Mapping[str, object]) -> dict[str, object]
```

Returns a copy of *config* with the sensitive keys ``PASSWORD``, ``OPTIONS``, ``USER`` and ``HOST`` replaced by ``"<redacted>"``. Matching is case-insensitive on the key (``key.upper()``), so ``"password"`` is redacted as well as ``"PASSWORD"``. Values themselves are never inspected, only the key names. Fleet commands use this when writing to stdout or stderr.

```python
from django_isolated_tenants.connections import redacted_config

redacted_config({"NAME": "tenant_acme", "USER": "acme", "HOST": "db1", "PORT": 5432})
# {"NAME": "tenant_acme", "USER": "<redacted>", "HOST": "<redacted>", "PORT": 5432}
```

---

## Database router

To enable routing, add the router to ``DATABASE_ROUTERS``:

```python
DATABASE_ROUTERS = ["django_isolated_tenants.router.TenantRouter"]
```

### `django_isolated_tenants.router.TenantRouter`

The router class. You do not instantiate it directly; Django does so when evaluating ``DATABASE_ROUTERS``. Its behaviour is described below.

#### `TenantRouter.db_for_read()`

```python
def db_for_read(self, model, **hints) -> str | None
```

Routes the *model* according to its classification:

| Classification | Result |
|---|---|
| ``MASTER`` | ``MASTER_ALIAS`` |
| ``DEFAULT`` | ``None`` (defer to the next router / ``DATABASES`` default) |
| ``TENANT`` | Current tenant alias from the context |

Raises ``TenantContextMissing`` ("``No tenant context for <app_label>.<model>``") if a tenant model is accessed without an active context. The fail-closed behaviour is deliberate: it converts "silently read the wrong database" into a loud, immediate error.

#### `TenantRouter.db_for_write()`

```python
def db_for_write(self, model, **hints) -> str | None
```

As ``db_for_read()``, with the additional rule that writes whose resolved alias ends with ``_replica`` or ``-replica`` (case-insensitive) raise ``TenantContextMissing`` ("``Tenant writes cannot target a replica-style alias``"). This prevents accidental writes to a replica-style alias; note that the rule is based on alias *naming*, so name your read replicas accordingly.

#### `TenantRouter.allow_relation()`

```python
def allow_relation(self, obj1, obj2, **hints) -> bool | None
```

Controls whether a relation between two instances is allowed. Decision table, in order:

| Condition | Result |
|---|---|
| Either instance classifies as ``DEFAULT`` | ``None`` |
| The instances span ``MASTER`` and ``TENANT`` | ``False`` |
| Both instances pinned to a database (``obj._state.db`` set on both) | ``database1 == database2`` |
| Both ``MASTER`` and no database pinned | ``True`` |
| Both ``TENANT`` and a tenant context is active | ``True`` |
| Otherwise (both ``TENANT``, no context) | ``None`` |

``None`` means "no opinion" - Django falls back to its default behaviour (relations are allowed if both objects share ``_state.db``) and any remaining routers are consulted.

#### `TenantRouter.allow_migrate()`

```python
def allow_migrate(self, db, app_label, model_name=None, **hints) -> bool | None
```

Controls where migrations are applied. The method first looks for a hint ``hints["isolated_tenants_scope"]``; if present it must be ``"master"`` or ``"tenant"`` (otherwise ``ImproperlyConfigured`` is raised). If no hint is supplied it falls back to ``hints["model"]`` (a historical model, inspected through ``_meta``) and then to ``classify_model``. The decision is:

| Condition | Result |
|---|---|
| Scope resolves to ``DEFAULT`` | ``None`` |
| ``db`` is the master alias | ``True`` only for ``MASTER`` |
| ``db`` is a registered tenant alias | ``True`` only for ``TENANT`` |
| Otherwise (unrelated database) | ``None`` (defer to the next router) |

For data migrations that have no model, declare their scope explicitly:

```python
migrations.RunPython(my_func, hints={"isolated_tenants_scope": "master"})
migrations.RunSQL("UPDATE ...", hints={"isolated_tenants_scope": "tenant"})
```

> **Note:** The tenant-alias branch only recognises aliases present in ``registered_database_aliases()`` - i.e. databases registered by ``register_database()`` in the current process. ``migrate_tenants`` registers each database before invoking the base ``migrate`` command, which is why tenant migrations should be applied through it rather than plain ``migrate --database=<alias>`` (an unregistered alias simply yields ``None`` from this router).

---

## Middleware

### `django_isolated_tenants.middleware.TenantMiddleware`

```python
class TenantMiddleware:
    sync_capable = True
    async_capable = True
```

Resolves the tenant for each incoming request and holds the tenant context for the entire downstream execution. The middleware should be placed after security or host-validation middleware and before any code that accesses tenant models.

The constructor caches the parsed settings, pre-compiles the ``EXCLUDED_PATHS`` regular expressions and detects whether *get_response* is a coroutine function. On each request ``_resolve`` is called:

* If ``request.path_info`` matches an excluded pattern, the request is passed through without tenant resolution.
* Otherwise ``get_provider().resolve_request(request)`` is called. If it returns ``None``, the middleware returns ``HttpResponseNotFound("Tenant not found")``.
* If a tenant is returned, its database is resolved through ``get_provider().get_database(tenant.database_alias)``, registered with ``register_database``, and attached to the request as ``request.<TENANT_ATTRIBUTE>`` and ``request.<DATABASE_ATTRIBUTE>``.

The tenant context is held with ``tenant_context`` using explicit ``__enter__`` / ``__exit__`` so that it remains active during the complete response, including any exception. For ``StreamingHttpResponse`` the ``streaming_content`` iterator is wrapped (``_stream`` for synchronous responses and ``_astream`` for asynchronous responses) so that the context stays active while the iterator is consumed and is cleaned in a ``finally`` block even if the iterator raises.

The middleware supports synchronous, asynchronous and streaming responses and preserves the context across ``await`` boundaries.

Request lifecycle at a glance:

```python
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django_isolated_tenants.middleware.TenantMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    # ... the rest of your stack ...
]
```

* Databases registered by the middleware stay registered for the process lifetime; subsequent requests re-register idempotently.
* Unresolved tenants are fail-closed: the middleware short-circuits with 404 and never enters a tenant context.
* Views reached through an excluded path run with no tenant context and no ``request.tenant`` attribute - use ``getattr(request, "tenant", None)`` in shared code paths.

---

## Celery tasks

Celery integration requires the ``celery`` extra:

```console
pip install "django-isolated-tenants[celery]"
```

Importing ``django_isolated_tenants.celery`` without the extra raises ``ImportError``.

Only the tenant identifier and database alias are serialised into the task header ``"django_isolated_tenants"``. The header payload has the shape:

```json
{"version": 1, "identifier": "acme", "database_alias": "customer_a"}
```

Database credentials are resolved on the worker through ``get_provider().get_database()`` and are never included in the message. Workers must therefore run with your Django settings loaded and the provider importable - the standard ``celery -A proj`` setup with Django integration satisfies this.

### `django_isolated_tenants.celery.tenant_task()`

```python
def tenant_task(function=None, **options) -> Any
```

Decorator that turns a function into a tenant-aware Celery task. It may be used with or without arguments and preserves the usual Celery options such as ``bind``, ``name``, ``autoretry_for``, ``retry_kwargs``, ``queue`` and ``ignore_result``. It is implemented as ``shared_task(base=TenantTask, **options)``.

```python
from django_isolated_tenants.celery import tenant_task

@tenant_task
def rebuild_index():
    ...

@tenant_task(bind=True, queue="tenants")
def rebuild_with_retry(self):
    ...
```

Dispatch:

```python
# From within a request or a tenant_context - uses current context:
rebuild_index.delay()
rebuild_index.apply_async(args=[...])

# From outside a request - explicit tenant:
from django_isolated_tenants import Tenant
rebuild_index.apply_async_for_tenant(Tenant("acme", "customer_a"))
```

``delay`` / ``apply_async`` require an active tenant context and raise ``TenantContextMissing`` ("``Cannot schedule a tenant task without tenant context``") otherwise. The header ``"django_isolated_tenants"`` is reserved; attempting to supply or override it raises ``TenantTaskMetadataInvalid``. Any *other* headers you pass through ``headers={...}`` are forwarded untouched.

On the worker, the header is validated, the database is resolved and registered, and the task body is executed inside ``tenant_context``. The database is removed in a ``finally`` block and the header is preserved across retries (it travels in the request headers, so Celery's retry machinery resends it automatically).

The worker-side entry point also verifies that the provider honours the requested alias: if ``get_database(tenant.database_alias).alias`` differs from the requested alias, ``TenantTaskMetadataInvalid`` ("``Tenant provider returned a mismatched database alias``") is raised before the body runs.

### `django_isolated_tenants.celery.TenantTask`

```python
class TenantTask(Task):
    abstract = True
```

The base class used by ``tenant_task``. It carries a dedicated ``request_stack = LocalStack()`` so that the tenant header of an outer task is not shadowed when tasks nest. Its notable methods are:

* ``apply_async(args=None, kwargs=None, **options)`` - context-based dispatch. Reads the current tenant with ``get_current_tenant()`` and forwards to ``_apply_for_tenant``. A pre-existing reserved header is accepted only if it exactly matches the current tenant's metadata.
* ``apply_async_for_tenant(tenant, args=None, kwargs=None, **options)`` - explicit dispatch; *tenant* must be a ``Tenant`` instance, otherwise ``TypeError`` is raised.
* ``__call__(*args, **kwargs)`` - worker-side entry point; restores the tenant context and manages database registration.

### `django_isolated_tenants.celery.all_tenants_task()`

```python
def all_tenants_task(function=None, **options) -> Any
```

Decorator that fans a single function out to the entire tenant fleet. The decorated function is registered twice: an internal ``TenantTask`` named ``"<name>.__tenant"`` that executes per tenant, and a public ``AllTenantsTask`` named ``"<name>"`` whose ``apply_async`` performs the fan-out.

```python
from django_isolated_tenants.celery import all_tenants_task

@all_tenants_task
def nightly_cleanup():
    ...

result = nightly_cleanup.delay()  # returns GroupResult
```

The returned value is a Celery ``GroupResult`` containing one child ``AsyncResult`` per tenant. Inspect it as usual:

```python
if result.ready():
    failed = [r for r in result if r.failed()]
```

Positional and keyword arguments are forwarded to every child:

```python
@all_tenants_task
def export(kind: str, *, since=None):
    ...

export.delay("csv", since=yesterday)  # every tenant receives ("csv", since=yesterday)
```

### `django_isolated_tenants.celery.AllTenantsTask`

```python
class AllTenantsTask(Task):
    abstract = True
```

The base class used by ``all_tenants_task``. Its ``apply_async`` method:

* Rejects a caller-supplied ``task_id`` (a single id cannot represent a fan-out) and rejects ``link``, ``link_error``, ``chain`` and ``chord`` options - each raises ``ValueError`` explaining the restriction. Compose on the returned ``GroupResult`` instead.
* Rejects a caller-supplied reserved header (``TenantTaskMetadataInvalid``).
* Obtains a fleet snapshot through ``iter_tenants()`` and validates identifiers, aliases and ``get_database`` alias matches; raises ``TenantTaskMetadataInvalid`` on duplicates, empty strings or mismatches.
* Creates one child signature per tenant using the internal tenant task, assigns a shared ``group_id`` (via ``celery.utils.uuid``), dispatches the children as a ``group`` and returns the ``GroupResult``.
* If the fleet is empty, returns an empty ``GroupResult`` without executing the body. Child failures and retries are independent; the task body should therefore be idempotent.

> **Note:** The tenant list is a snapshot taken at dispatch time. Tasks that depend on fleet membership should be idempotent and tolerant of concurrent fleet changes.

### Celery error reference

| Situation | Exception | Typical message |
|---|---|---|
| ``delay``/``apply_async`` with no tenant context | ``TenantContextMissing`` | ``Cannot schedule a tenant task without tenant context`` |
| Worker receives a task without the header | ``TenantContextMissing`` | ``Cannot execute a tenant task without serialized tenant context`` |
| Malformed header or unknown version | ``TenantTaskMetadataInvalid`` | ``Tenant task metadata is malformed or has an unsupported version`` |
| Empty identifier/alias in the header | ``TenantTaskMetadataInvalid`` | ``Tenant task metadata requires non-empty identifier and database_alias`` |
| Caller supplies the reserved header | ``TenantTaskMetadataInvalid`` | ``The reserved 'django_isolated_tenants' header is managed by django-isolated-tenants`` |
| Fleet snapshot contains empty/duplicate values | ``TenantTaskMetadataInvalid`` | ``Tenant fleet contains an empty identifier or database alias`` / ``... duplicate identifiers or database aliases`` |
| Provider returns mismatched alias | ``TenantTaskMetadataInvalid`` | ``Tenant provider returned a mismatched database alias`` |
| ``apply_async_for_tenant`` with a non-``Tenant`` | ``TypeError`` | ``apply_async_for_tenant() requires a Tenant`` |
| Fan-out with ``task_id``/``link``/``link_error``/``chain``/``chord`` | ``ValueError`` | ``all_tenants_task does not accept a single task_id for fan-out`` (and similar) |

---

## System checks

The package registers a Django system check that runs during ``manage.py check`` and ``manage.py migrate``. The check is imported in ``IsolatedTenantsConfig.ready()`` without touching the database.

### `django_isolated_tenants.checks.check_cross_database_relations`

```python
@checks.register(checks.Tags.models)
def check_cross_database_relations(app_configs=None, **kwargs) -> list[checks.Error]
```

Inspects all concrete ``ForeignKey``, ``OneToOneField`` and ``ManyToManyField`` relations. If a relation connects a master-scoped model to a tenant-scoped model (and neither side is ``DEFAULT`` and the target is not a self-relation), it emits:

* ``id = "isolated_tenants.E001"``
* ``msg = "{Source}.{field} relates {Target} across master and tenant databases."``
* ``hint = "Use a scalar identifier and application-level lookup instead of a database relation."``

Skipped cases: non-concrete relations (for example reverse descriptors), self-relations, and any relation where either side classifies as ``DEFAULT`` (those are the next router's business). Passing *app_configs* restricts the inspection to a subset of applications.

Example output:

```console
$ python manage.py check
SystemCheckError: System check identified some issues:

ERRORS:
billing.Invoice.customer: (isolated_tenants.E001)
        HINT: Use a scalar identifier and application-level lookup instead of a database relation.
```

Run the check with:

```console
python manage.py check
```

---

## Application configuration

### `django_isolated_tenants.apps.IsolatedTenantsConfig`

```python
class IsolatedTenantsConfig(AppConfig):
    name = "django_isolated_tenants"
    verbose_name = "Isolated tenants"
```

The application configuration. Its ``ready()`` method imports ``django_isolated_tenants.checks`` to register the system check. It performs no database queries. Django discovers it automatically from ``INSTALLED_APPS``; you never need to reference the class explicitly.

---

## Exceptions

All exceptions are importable from ``django_isolated_tenants`` and from ``django_isolated_tenants.exceptions``. Catch ``IsolatedTenantsError`` to handle every package error at once.

| Exception | Base class | Description |
|---|---|---|
| ``IsolatedTenantsError`` | ``Exception`` | Base class for all package errors. |
| ``TenantContextMissing`` | ``IsolatedTenantsError`` | Raised when tenant-scoped work is attempted without an active tenant context, or when a Celery task arrives without a tenant header. Subclassed from ``TenantContextMissing`` in the router and task dispatch paths. |
| ``TenantNotResolved`` | ``IsolatedTenantsError`` | Reserved for cases where a request cannot be mapped to a tenant. |
| ``TenantDatabaseInvalid`` | ``IsolatedTenantsError`` | Raised when a provider supplies an unsafe or inconsistent database configuration (empty alias, master alias, wrong engine, missing ``NAME``, or conflicting registration). |
| ``TenantTaskMetadataInvalid`` | ``IsolatedTenantsError`` | Raised when a Celery task carries malformed, version-mismatched or disallowed tenant metadata, or when a fleet snapshot contains duplicate or empty identifiers. |

Where each exception typically surfaces:

| Exception | Raised by |
|---|---|
| ``TenantContextMissing`` | ``TenantRouter.db_for_read`` / ``db_for_write`` (no context or replica alias), ``TenantTask.apply_async``, ``TenantTask.__call__`` |
| ``TenantDatabaseInvalid`` | ``register_database`` / ``_validated_config`` |
| ``TenantTaskMetadataInvalid`` | Header validation (dispatch and worker), fleet validation in ``AllTenantsTask``, provider alias mismatch |
| ``TenantNotResolved`` | Reserved; the middleware itself returns 404 rather than raising |

---

## Management commands

All fleet commands redact sensitive connection values before writing to stdout or stderr and continue with remaining tenants after a per-tenant failure, raising a single combined ``CommandError`` at the end. A raised ``CommandError`` makes ``manage.py`` exit with a non-zero status, which makes the commands safe to use in CI and cron jobs.

Fleet helpers shared by the commands live in ``django_isolated_tenants.management.commands._fleet``:

* ``selected_databases(alias)`` - returns the databases for *alias* or the entire fleet; raises ``CommandError`` for duplicate aliases or an unknown alias.
* ``tenant_snapshot()`` - returns a validated snapshot of ``iter_tenants()``; raises ``CommandError`` for empty, duplicate or unresolvable entries.
* ``tenant_for_alias(alias)`` - finds the tenant for *alias* in the snapshot or returns ``Tenant(alias, alias)`` as a fallback.
* ``failure_summary(command, failures)`` - formats ``[(alias, exc), ...]`` into a ``CommandError`` whose message reads ``<command> failed for tenant databases: <alias>: <ExcType>: <message>; ...``.

### `migrate_tenants`

```console
python manage.py migrate_tenants [--tenant ALIAS] [migrate options]
```

Runs Django migrations across tenant databases. Extends ``django.core.management.commands.migrate.Command`` and forwards all standard ``migrate`` options (``--plan``, ``--fake``, ``--fake-initial``, ``--prune``, app/migration targets, and so on). The ``--database`` option is forced per tenant and cannot be overridden.

* ``--tenant ALIAS`` - migrate only the named tenant database (otherwise all tenants).
* For each selected database the command writes ``Migrating tenant '<alias>' (<redacted config>)``, registers the database, enters ``tenant_context`` for the matching tenant, and calls the base ``migrate`` command with ``database=alias``. Per-tenant failures are collected and reported; ``remove_database`` is called in a ``finally`` block.
* The tenant context is established through ``tenant_for_alias``, which falls back to ``Tenant(alias, alias)`` when the fleet snapshot has no entry for the alias - so the router's context requirement is satisfied even for databases known only to ``iter_databases()``.
* An unknown ``--tenant`` alias aborts before any migration runs (``CommandError: Unknown tenant database alias: ...``).

Examples:

```console
python manage.py migrate_tenants
python manage.py migrate_tenants --tenant customer_a --plan
python manage.py migrate_tenants --tenant customer_a --fake
python manage.py migrate_tenants billing 0002_add_index
```

### `show_tenant_migrations`

```console
python manage.py show_tenant_migrations [--tenant ALIAS] [--missing]
```

Shows migration state across tenant databases. Extends ``django.core.management.commands.showmigrations.Command``. Per-tenant failures are collected (a ``Tenant: <alias>`` heading is still printed) and reported as a combined ``CommandError``; ``remove_database`` runs in a ``finally`` block.

* ``--tenant ALIAS`` - inspect only the named tenant database.
* ``--missing`` - show only unapplied migrations (lines containing ``[ ]``).
* The ``--missing`` implementation sets ``options["list"] = True``, captures the output of the base command without polluting fleet stdout (redirecting ``self.stdout`` to a ``StringIO`` and restoring it in ``finally``), filters for ``[ ]`` lines, and prints them under a ``Tenant: <alias>`` heading. Tenants with no missing migrations produce no ``[ ]`` lines.
* ``--missing`` composes with the base command's ``--plan`` flag the same way plain ``showmigrations --plan --list`` does.

Examples:

```console
python manage.py show_tenant_migrations
python manage.py show_tenant_migrations --missing
python manage.py show_tenant_migrations --tenant customer_a --missing
```

### `check_tenant_layout`

```console
python manage.py check_tenant_layout [--tenant ALIAS]
```

Inspects master and tenant table placement without creating or modifying any tables.

The command builds the sets of expected master and tenant tables from all managed, non-proxy models classified as ``MASTER`` or ``TENANT``. It then introspects ``connections[MASTER_ALIAS].introspection.table_names()`` and each tenant connection (after ``register_database``). Discrepancies are collected:

* ``master missing expected table <table>``
* ``tenant table unexpectedly on master: <table>``
* ``<alias>: master table unexpectedly present: <table>``
* ``<alias>: missing expected tenant table <table>``
* ``<alias>: inspection failed (<Exc>)`` on introspection errors.

If any discrepancies exist the command raises ``CommandError("Tenant layout discrepancies: ...")`` with a semicolon-separated summary. Otherwise it writes ``Tenant layout matches expected model placement.`` Database aliases are cleaned with ``remove_database`` in a ``finally`` block regardless of outcome.

The command requires a reachable master database (it introspects ``MASTER_ALIAS``) and, without ``--tenant``, a reachable database for every fleet entry; unreachable tenant databases are reported as ``inspection failed`` discrepancies rather than aborting the run.

This command is read-only; it does not provision or repair tables. If layout changes are needed, review the output, plan manual remediation, and then run migrations.

Examples:

```console
python manage.py check_tenant_layout
python manage.py check_tenant_layout --tenant customer_a
```

---