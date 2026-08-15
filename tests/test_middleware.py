import asyncio
from collections.abc import AsyncIterator, Iterator
from typing import Any, cast

import pytest
from django.http import HttpRequest, HttpResponse, StreamingHttpResponse

from django_isolated_tenants import Tenant, get_current_tenant, tenant_context
from django_isolated_tenants.connections import remove_database
from django_isolated_tenants.middleware import TenantMiddleware
from tests.provider import provider


def request(path: str) -> HttpRequest:
    value = HttpRequest()
    value.path_info = path
    return value


def test_middleware_resolves_attaches_and_clears_context() -> None:
    seen = []

    def downstream(value: HttpRequest) -> HttpResponse:
        seen.append(get_current_tenant())
        assert cast(Any, value).tenant_database_alias == "tenant_a"
        return HttpResponse("ok")

    response = TenantMiddleware(downstream)(request("/orders"))
    assert response.status_code == 200
    assert seen == [provider.tenant]
    assert get_current_tenant() is None
    remove_database("tenant_a")


def test_exclusion_and_unresolved_tenant() -> None:
    assert TenantMiddleware(lambda value: HttpResponse("ok"))(request("/health/")).status_code == 200
    provider.tenant = None
    try:
        assert TenantMiddleware(lambda value: HttpResponse("bad"))(request("/orders")).status_code == 404
    finally:
        from django_isolated_tenants import Tenant

        provider.tenant = Tenant("tenant-id", "tenant_a")


def test_downstream_exception_cannot_leak_context() -> None:
    def explode(value: HttpRequest) -> HttpResponse:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        TenantMiddleware(explode)(request("/orders"))
    assert get_current_tenant() is None
    remove_database("tenant_a")


def test_middleware_restores_an_outer_context() -> None:
    outer = Tenant("outer", "outer_db")
    with tenant_context(outer):
        response = TenantMiddleware(lambda value: HttpResponse(str(get_current_tenant())))(request("/orders"))
        assert response.status_code == 200
        assert get_current_tenant() == outer
    assert get_current_tenant() is None
    remove_database("tenant_a")


def test_streaming_response_keeps_context_until_consumed() -> None:
    def content() -> Iterator[bytes]:
        tenant = get_current_tenant()
        assert tenant is not None
        yield tenant.identifier.encode()

    response = TenantMiddleware(lambda value: StreamingHttpResponse(content()))(request("/orders"))
    assert get_current_tenant() == provider.tenant
    assert b"".join(response.streaming_content) == b"tenant-id"
    assert get_current_tenant() is None
    remove_database("tenant_a")


def test_async_request_and_streaming_lifecycle() -> None:
    async def content() -> AsyncIterator[bytes]:
        tenant = get_current_tenant()
        assert tenant is not None
        yield tenant.identifier.encode()

    async def downstream(value: HttpRequest) -> StreamingHttpResponse:
        assert get_current_tenant() == provider.tenant
        return StreamingHttpResponse(content())

    async def run() -> bytes:
        response = await TenantMiddleware(downstream)(request("/orders"))
        assert get_current_tenant() == provider.tenant
        chunks = [chunk async for chunk in response.streaming_content]
        assert get_current_tenant() is None
        return b"".join(chunks)

    assert asyncio.run(run()) == b"tenant-id"
    remove_database("tenant_a")
