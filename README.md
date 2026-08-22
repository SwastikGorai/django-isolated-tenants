# django-isolated-tenants

[![CI](https://img.shields.io/badge/CI-GitHub_Actions-2088FF.svg?logo=github-actions&logoColor=white)](https://github.com/SwastikGorai/django-isolated-tenants/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.11%20%7C%203.12-3776AB.svg?logo=python&logoColor=white)](https://www.python.org/)
[![Django](https://img.shields.io/badge/Django-5.2-0C4B33.svg?logo=django&logoColor=white)](https://www.djangoproject.com/)
[![License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Database-per-tenant routing for Django 5.2 and PostgreSQL.

`django-isolated-tenants` switches database connections from request or task
context, keeps control-plane and tenant-only models separated, and provides
commands for operating across a tenant fleet. The package deliberately leaves
authentication, tenant records, credentials, provisioning, and schema policy
under application control.

> [!IMPORTANT]
> This project is under active development. Review migration plans and test
> against non-production databases before adopting it in an existing project.

## Features

- Request-scoped, fail-closed tenant routing.
- Explicit `MasterModel` and `TenantModel` abstract bases.
- Configuration settings for master applications and legacy models.
- Dynamic PostgreSQL connection registration without serializing credentials.
- Tenant fleet migration and schema-layout inspection commands.
- Tenant-aware Celery tasks and parallel all-tenant fan-out.
- Sync, async, and streaming-response middleware support.
- Typed public interfaces and Django system checks.

## Requirements

- Python 3.11 or 3.12
- Django 5.2
- PostgreSQL for tenant databases
- Celery 5.3 or newer when using task integration

## Installation

Install the base package and the integrations your project uses:

```console
pip install "django-isolated-tenants[postgres,celery]"
```

With uv:

```console
uv add "django-isolated-tenants[postgres,celery]"
```

The `postgres` and `celery` extras can be installed independently.

>For the full public API: settings, model bases, tenant context helpers,
>database router, middleware, Celery integration, system checks, and management
>commands, see the [API reference](docs/API_REFERENCE.md).

## Quick start

Add the application, middleware, and router to your Django settings. Place the
middleware after security or host validation middleware and before code that
accesses tenant models.

```python
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
    # Empty by design: each project chooses its control-plane applications.
    "MASTER_APPS": [],
    # Configuration escape hatch for third-party or existing models.
    "MASTER_MODELS": ["legacy.controlmodel"],
    "EXCLUDED_PATHS": [r"^/health/$"],
}
```

### Tenant provider

`PROVIDER` points to an object or class implementing the `TenantProvider`
interface:

```python
from django_isolated_tenants import Tenant, TenantDatabase


class ProjectTenantProvider:
    def resolve_request(self, request) -> Tenant | None:
        ...

    def get_database(self, alias: str) -> TenantDatabase:
        ...

    def iter_databases(self):
        ...

    def iter_tenants(self):
        ...


provider = ProjectTenantProvider()
```

Tenant database mappings must use Django's PostgreSQL backend. Credentials are
resolved through this provider and are never included in Celery task headers.

## Model placement

| Model declaration | Routing and migration behavior |
| --- | --- |
| `MasterModel` | Master database only |
| `TenantModel` | Active tenant database only |
| Plain `models.Model` | Deferred to Django's normal database-router chain |
| Model in `MASTER_APPS` or `MASTER_MODELS` | Master database only |

```python
from django_isolated_tenants import MasterModel, TenantModel


class TenantRegistry(MasterModel):
    ...


class Invoice(TenantModel):
    ...
```

Do not create database relations between master and tenant models. Cross-database
foreign keys are not supported. Django's `auth`, `contenttypes`, and `admin`
applications are related and should not be divided between databases casually.

## Explicit tenant context

Code running outside request middleware can establish tenant context directly:

```python
from django_isolated_tenants import Tenant, tenant_context

tenant = Tenant(identifier="acme", database_alias="customer_a")

with tenant_context(tenant):
    ...
```

## Migrations and fleet commands

```console
python manage.py migrate_tenants
python manage.py migrate_tenants --tenant customer_a --plan
python manage.py show_tenant_migrations --missing
python manage.py check_tenant_layout
```

Migration operations without a model must declare their scope, for example
`hints={"isolated_tenants_scope": "master"}` on `RunPython` or `RunSQL`.
Changing model placement after migrations have run can leave missing or
misplaced tables. Use `check_tenant_layout` to inspect placement and plan any
repair manually.

## Celery integration

```python
from django_isolated_tenants.celery import all_tenants_task, tenant_task


@tenant_task
def rebuild_index():
    ...


@all_tenants_task
def nightly_cleanup():
    ...
```

`rebuild_index.delay()` requires active tenant context. For work initiated
outside a request, use `rebuild_index.apply_async_for_tenant(tenant)`.

An all-tenant task snapshots the tenant fleet and schedules one independent
child task per tenant. Dispatch returns a Celery `GroupResult`; child failures
and retries remain independent. Fleet task bodies should therefore be
idempotent.

## Development

Clone the repository and install the test dependencies:

```console
git clone https://github.com/SwastikGorai/django-isolated-tenants.git
cd django-isolated-tenants
uv sync --locked --extra test
```

Run the same checks enforced by CI:

```console
uv run ruff check .
uvx --from tombi==1.1.0 tombi lint --error-on-warnings .
uv run python -m django check --settings tests.settings
uv run pytest
uv build
```

GitHub Actions runs linting, tests every declared Python version, performs
Django system checks, and builds both the wheel and source distribution.

## Contributing

Contributions are welcome, including bug reports, documentation improvements,
tests, and focused feature proposals.

Before opening a pull request:

1. Search the issue tracker to avoid duplicating existing work.
2. Open an issue before large behavioral or public-API changes so the design
   can be discussed first.
3. Keep changes focused and add tests for new or corrected behavior.
4. Run the complete development check suite shown above.
5. Update the README or changelog when behavior visible to users changes.

Pull requests should explain the problem, the chosen approach, migration or
compatibility implications, and how the change was verified. Please do not
include production credentials, tenant data, or identifying database details
in issues, fixtures, logs, or test output.

By contributing, you agree that your contributions will be licensed under the
project's MIT License.

## License

Copyright © 2026 Swastik Gorai.

Distributed under the [MIT License](LICENSE).
