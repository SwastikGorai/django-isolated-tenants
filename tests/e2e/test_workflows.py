from collections.abc import Iterator
from typing import Any, cast

from celery import current_app
from django.http import HttpRequest, HttpResponse, StreamingHttpResponse
from django.test import Client, override_settings
from django.urls import path

from django_isolated_tenants import Tenant, get_current_tenant
from django_isolated_tenants.celery import tenant_task
from django_isolated_tenants.connections import registered_database_aliases, remove_database
from django_isolated_tenants.context import tenant_context


def tenant_view(request: HttpRequest) -> HttpResponse:
    tenant = get_current_tenant()
    assert tenant is not None
    return HttpResponse(f"{tenant.identifier}:{cast(Any, request).tenant_database_alias}")


def streaming_tenant_view(request: HttpRequest) -> StreamingHttpResponse:
    def content() -> Iterator[bytes]:
        tenant = get_current_tenant()
        assert tenant is not None
        yield f"{tenant.identifier}:{cast(Any, request).tenant_database_alias}".encode()

    return StreamingHttpResponse(content())


urlpatterns = [
    path("tenant/", tenant_view),
    path("tenant/stream/", streaming_tenant_view),
]


@override_settings(
    ROOT_URLCONF=__name__,
    MIDDLEWARE=["django_isolated_tenants.middleware.TenantMiddleware"],
)
def test_request_crosses_django_middleware_url_and_view_stack() -> None:
    client = Client()

    response = client.get("/tenant/")
    assert response.status_code == 200
    assert response.content == b"tenant-id:tenant_a"
    assert get_current_tenant() is None

    streamed = client.get("/tenant/stream/")
    assert b"".join(streamed.streaming_content) == b"tenant-id:tenant_a"
    assert get_current_tenant() is None
    remove_database("tenant_a")


def test_celery_eager_dispatch_restores_context_and_cleans_database() -> None:
    @tenant_task(name="tests.e2e.read_tenant_context")
    def read_tenant_context() -> tuple[str, str]:
        tenant = get_current_tenant()
        assert tenant is not None
        return tenant.identifier, tenant.database_alias

    previous_always_eager = current_app.conf.task_always_eager
    previous_eager_propagates = current_app.conf.task_eager_propagates
    current_app.conf.update(task_always_eager=True, task_eager_propagates=True)
    try:
        with tenant_context(Tenant("tenant-id", "tenant_a")):
            result = read_tenant_context.apply_async()
        assert result.get() == ("tenant-id", "tenant_a")
        assert get_current_tenant() is None
        assert "tenant_a" not in registered_database_aliases()
    finally:
        current_app.conf.update(
            task_always_eager=previous_always_eager,
            task_eager_propagates=previous_eager_propagates,
        )
        remove_database("tenant_a")
