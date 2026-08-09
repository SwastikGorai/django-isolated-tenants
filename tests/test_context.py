import asyncio

import pytest

from django_isolated_tenants import (
    Tenant,
    clear_tenant_context,
    get_current_database_alias,
    get_current_tenant,
    tenant_context,
)


def test_nested_context_restores_after_exception() -> None:
    outer = Tenant("one", "tenant_one")
    inner = Tenant("two", "tenant_two")
    with tenant_context(outer):
        with pytest.raises(RuntimeError), tenant_context(inner):
            raise RuntimeError
        assert get_current_tenant() == outer
    assert get_current_tenant() is None


def test_clear_context_is_explicit() -> None:
    with tenant_context(Tenant("one", "tenant_one")):
        clear_tenant_context()
        assert get_current_database_alias() is None


def test_async_tasks_have_isolated_contexts() -> None:
    async def read(tenant: Tenant) -> str | None:
        with tenant_context(tenant):
            await asyncio.sleep(0)
            return get_current_database_alias()

    async def run() -> list[str | None]:
        return list(await asyncio.gather(read(Tenant("a", "a_db")), read(Tenant("b", "b_db"))))

    assert asyncio.run(run()) == ["a_db", "b_db"]
