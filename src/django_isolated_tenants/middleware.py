import inspect
import re
from collections.abc import AsyncIterator, Callable, Iterator
from typing import Any

from django.http import HttpRequest, HttpResponse, HttpResponseNotFound, StreamingHttpResponse

from .conf import get_provider, get_settings
from .connections import register_database
from .context import tenant_context


class TenantMiddleware:
    sync_capable = True
    async_capable = True

    def __init__(self, get_response: Callable[[HttpRequest], Any]) -> None:
        self.get_response = get_response
        self.config = get_settings()
        self.excluded = tuple(re.compile(pattern) for pattern in self.config.excluded_paths)
        self._is_async = inspect.iscoroutinefunction(get_response)

    def __call__(self, request: HttpRequest) -> Any:
        if self._is_async:
            return self._call_async(request)
        return self._call_sync(request)

    def _resolve(self, request: HttpRequest) -> Any:
        if any(pattern.search(request.path_info) for pattern in self.excluded):
            return None
        tenant = get_provider().resolve_request(request)
        if tenant is None:
            return False
        register_database(get_provider().get_database(tenant.database_alias))
        setattr(request, self.config.tenant_attribute, tenant)
        setattr(request, self.config.database_attribute, tenant.database_alias)
        return tenant

    def _call_sync(self, request: HttpRequest) -> HttpResponse:
        resolved = self._resolve(request)
        if resolved is None:
            return self.get_response(request)
        if resolved is False:
            return HttpResponseNotFound("Tenant not found")
        tenant = resolved
        context = tenant_context(tenant)
        context.__enter__()
        try:
            response = self.get_response(request)
        except BaseException as error:
            context.__exit__(type(error), error, error.__traceback__)
            raise
        if isinstance(response, StreamingHttpResponse):
            response.streaming_content = self._stream(response.streaming_content, context)
            return response
        context.__exit__(None, None, None)
        return response

    def _stream(self, content: Iterator[Any], context: Any) -> Iterator[Any]:
        try:
            yield from content
        finally:
            context.__exit__(None, None, None)

    async def _call_async(self, request: HttpRequest) -> HttpResponse:
        resolved = self._resolve(request)
        if resolved is None:
            return await self.get_response(request)
        if resolved is False:
            return HttpResponseNotFound("Tenant not found")
        tenant = resolved
        context = tenant_context(tenant)
        context.__enter__()
        try:
            response = await self.get_response(request)
        except BaseException as error:
            context.__exit__(type(error), error, error.__traceback__)
            raise
        if isinstance(response, StreamingHttpResponse):
            response.streaming_content = self._astream(response.streaming_content, context)
            return response
        context.__exit__(None, None, None)
        return response

    async def _astream(self, content: AsyncIterator[Any], context: Any) -> AsyncIterator[Any]:
        try:
            async for chunk in content:
                yield chunk
        finally:
            context.__exit__(None, None, None)
