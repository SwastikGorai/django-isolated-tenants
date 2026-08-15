import os
from collections.abc import Iterator
from io import StringIO

import pytest
from celery import current_app
from django.core.management import call_command
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.test import Client, override_settings
from django.urls import path
from pytest_django.plugin import DjangoDbBlocker

from django_isolated_tenants import TenantContextMissing, get_current_tenant, tenant_context
from django_isolated_tenants.celery import all_tenants_task, tenant_task
from django_isolated_tenants.conf import get_provider, get_settings
from django_isolated_tenants.connections import register_database, remove_database
from tests.e2e.provider import TENANTS, provider
from tests.e2e.sample_app.models import AuditEvent, Project, Workspace

pytestmark = [
    pytest.mark.postgres_e2e,
    pytest.mark.skipif(os.environ.get("RUN_POSTGRES_E2E") != "1", reason="requires the PostgreSQL E2E databases"),
]

E2E_SETTINGS = {
    "PROVIDER": "tests.e2e.provider.provider",
    "MASTER_MODELS": ["contenttypes.contenttype"],
    "EXCLUDED_PATHS": [r"^/health/$"],
}


def health(request: HttpRequest) -> HttpResponse:
    return HttpResponse("healthy")


def projects(request: HttpRequest) -> JsonResponse:
    tenant = get_current_tenant()
    assert tenant is not None
    if request.method == "POST":
        Project.objects.create(workspace_slug=tenant.identifier, name=request.POST["name"])
    names = list(Project.objects.order_by("name").values_list("name", flat=True))
    return JsonResponse({"workspace": tenant.identifier, "projects": names})


urlpatterns = [path("health/", health), path("projects/", projects)]


@tenant_task(name="tests.e2e.record_audit_event")
def record_audit_event(action: str) -> tuple[str, int]:
    tenant = get_current_tenant()
    assert tenant is not None
    event = AuditEvent.objects.create(workspace_slug=tenant.identifier, action=action)
    return event.workspace_slug, event.pk


@all_tenants_task(name="tests.e2e.create_maintenance_event")
def create_maintenance_event() -> str:
    tenant = get_current_tenant()
    assert tenant is not None
    AuditEvent.objects.create(workspace_slug=tenant.identifier, action="maintenance")
    return tenant.identifier


@pytest.fixture(scope="module", autouse=True)
def migrated_tenant_fleet(django_db_setup: object, django_db_blocker: DjangoDbBlocker) -> Iterator[None]:
    with override_settings(ISOLATED_TENANTS=E2E_SETTINGS):
        get_settings.cache_clear()
        get_provider.cache_clear()
        with django_db_blocker.unblock():
            call_command("migrate", database="default", verbosity=0)
            call_command("migrate_tenants", verbosity=0)
        yield
        for tenant in TENANTS.values():
            remove_database(tenant.database_alias)
        get_provider.cache_clear()
        get_settings.cache_clear()


@pytest.fixture(autouse=True)
def clean_business_data(django_db_blocker: DjangoDbBlocker) -> Iterator[None]:
    with django_db_blocker.unblock():
        Workspace.objects.all().delete()
        for tenant in TENANTS.values():
            register_database(provider.get_database(tenant.database_alias))
            with tenant_context(tenant):
                Project.objects.all().delete()
                AuditEvent.objects.all().delete()
        yield
        for tenant in TENANTS.values():
            remove_database(tenant.database_alias)


@override_settings(
    ROOT_URLCONF=__name__,
    MIDDLEWARE=["django_isolated_tenants.middleware.TenantMiddleware"],
)
def test_http_crud_is_isolated_by_workspace_header() -> None:
    Workspace.objects.bulk_create(
        [Workspace(slug="acme", tenant_alias="e2e_acme"), Workspace(slug="globex", tenant_alias="e2e_globex")]
    )
    client = Client()

    assert client.post("/projects/", {"name": "Billing"}, headers={"X-Workspace": "acme"}).status_code == 200
    assert client.post("/projects/", {"name": "CRM"}, headers={"X-Workspace": "globex"}).status_code == 200
    acme = client.get("/projects/", headers={"X-Workspace": "acme"}).json()
    globex = client.get("/projects/", headers={"X-Workspace": "globex"}).json()

    assert acme == {"workspace": "acme", "projects": ["Billing"]}
    assert globex == {"workspace": "globex", "projects": ["CRM"]}
    assert list(Workspace.objects.values_list("slug", flat=True).order_by("slug")) == ["acme", "globex"]
    assert get_current_tenant() is None


@override_settings(
    ROOT_URLCONF=__name__,
    MIDDLEWARE=["django_isolated_tenants.middleware.TenantMiddleware"],
)
def test_public_health_and_unknown_workspace_behave_safely() -> None:
    client = Client()
    assert client.get("/health/").content == b"healthy"
    assert client.get("/projects/", headers={"X-Workspace": "unknown"}).status_code == 404
    assert get_current_tenant() is None


def test_service_code_is_fail_closed_and_explicit_context_selects_database() -> None:
    with pytest.raises(TenantContextMissing):
        Project.objects.count()
    with tenant_context(TENANTS["acme"]):
        Project.objects.create(workspace_slug="acme", name="API")
    with tenant_context(TENANTS["globex"]):
        assert Project.objects.count() == 0
    with tenant_context(TENANTS["acme"]):
        assert list(Project.objects.values_list("name", flat=True)) == ["API"]


def test_request_spawned_celery_work_preserves_tenant_and_isolation() -> None:
    previous = (current_app.conf.task_always_eager, current_app.conf.task_eager_propagates)
    current_app.conf.update(task_always_eager=True, task_eager_propagates=True)
    try:
        with tenant_context(TENANTS["acme"]):
            assert record_audit_event.delay("project.created").get()[0] == "acme"
        with tenant_context(TENANTS["globex"]):
            assert AuditEvent.objects.count() == 0
        register_database(provider.get_database("e2e_acme"))
        with tenant_context(TENANTS["acme"]):
            assert list(AuditEvent.objects.values_list("action", flat=True)) == ["project.created"]
    finally:
        current_app.conf.update(task_always_eager=previous[0], task_eager_propagates=previous[1])


def test_nightly_fanout_runs_once_for_every_tenant() -> None:
    previous = (current_app.conf.task_always_eager, current_app.conf.task_eager_propagates)
    current_app.conf.update(task_always_eager=True, task_eager_propagates=True)
    try:
        result = create_maintenance_event.delay()
        assert sorted(child.get() for child in result.results) == ["acme", "globex"]
        for tenant in TENANTS.values():
            register_database(provider.get_database(tenant.database_alias))
            with tenant_context(tenant):
                assert AuditEvent.objects.filter(action="maintenance").count() == 1
    finally:
        current_app.conf.update(task_always_eager=previous[0], task_eager_propagates=previous[1])


def test_operator_commands_report_migrations_and_valid_layout() -> None:
    migrations = StringIO()
    layout = StringIO()
    call_command("show_tenant_migrations", tenant="e2e_acme", stdout=migrations, verbosity=0)
    call_command("check_tenant_layout", stdout=layout, verbosity=0)
    assert "e2e_sample_app" in migrations.getvalue()
    assert "[X] 0001_initial" in migrations.getvalue()
    assert "matches expected model placement" in layout.getvalue()
