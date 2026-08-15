from unittest.mock import MagicMock, patch

import pytest
from django.db import connections

from django_isolated_tenants import (
    Tenant,
    TenantContextMissing,
    TenantTaskMetadataInvalid,
    get_current_tenant,
    tenant_context,
)
from django_isolated_tenants.celery import AllTenantsTask, TenantTask, all_tenants_task, tenant_task


class ConcreteTask(TenantTask):
    name = "tests.concrete"

    def run(self) -> object:
        return get_current_tenant()


def test_enqueue_serializes_context() -> None:
    task = ConcreteTask()
    with tenant_context(Tenant("id", "tenant_a")), patch.object(TenantTask.__mro__[1], "apply_async") as apply:
        task.apply_async()
    assert apply.call_args.kwargs["headers"]["django_isolated_tenants"]["database_alias"] == "tenant_a"


def test_enqueue_and_execution_require_context() -> None:
    task = ConcreteTask()
    with pytest.raises(TenantContextMissing):
        task.apply_async()
    with pytest.raises(TenantContextMissing):
        task()


def test_execution_restores_serialized_context() -> None:
    task = ConcreteTask()
    task.request_stack.push(
        type(
            "Request",
            (),
            {
                "headers": {
                    "django_isolated_tenants": {
                        "version": 1,
                        "identifier": "id",
                        "database_alias": "a",
                    }
                }
            },
        )()
    )
    try:
        assert task() == Tenant("id", "a")
        assert get_current_tenant() is None
        assert "a" not in connections.databases
    finally:
        task.request_stack.pop()


def test_unversioned_serialized_context_is_rejected() -> None:
    task = ConcreteTask()
    task.request_stack.push(
        type("Request", (), {"headers": {"django_isolated_tenants": {"identifier": "id", "database_alias": "a"}}})()
    )
    try:
        with pytest.raises(TenantTaskMetadataInvalid, match="malformed|unsupported"):
            task()
    finally:
        task.request_stack.pop()


def test_explicit_tenant_scheduling_does_not_require_request_context() -> None:
    task = ConcreteTask()
    with patch.object(TenantTask.__mro__[1], "apply_async") as apply:
        task.apply_async_for_tenant(Tenant("id", "tenant_a"), args=(1,))
    assert apply.call_args.kwargs["headers"]["django_isolated_tenants"]["identifier"] == "id"


def test_reserved_tenant_header_cannot_be_supplied_by_callers() -> None:
    task = ConcreteTask()
    with pytest.raises(TenantTaskMetadataInvalid, match="reserved"):
        task.apply_async_for_tenant(
            Tenant("id", "tenant_a"),
            headers={"django_isolated_tenants": {"version": 1, "identifier": "other", "database_alias": "other"}},
        )


def test_all_tenants_task_schedules_one_tenant_child_per_snapshot() -> None:
    child = ConcreteTask()

    class FleetTask(AllTenantsTask):
        name = "tests.fleet"
        tenant_task = child

    fleet = FleetTask()
    results = [MagicMock(), MagicMock()]
    with patch.object(child, "_apply_for_tenant", side_effect=results) as apply:
        result = fleet.apply_async(args=(1,), countdown=2)
    assert result.results == results
    assert [call.args[0] for call in apply.call_args_list] == [
        Tenant("tenant-1", "tenant_a"),
        Tenant("tenant-2", "tenant_b"),
    ]
    assert all(call.kwargs["countdown"] == 2 for call in apply.call_args_list)


def test_all_tenants_decorator_builds_a_distinct_tenant_child() -> None:
    @all_tenants_task(name="tests.cleanup")
    def cleanup() -> None:
        return None

    assert cleanup.name == "tests.cleanup"
    assert cleanup.tenant_task.name == "tests.cleanup.__tenant"


def test_all_tenants_task_rejects_duplicate_fleet_entries() -> None:
    child = ConcreteTask()

    class FleetTask(AllTenantsTask):
        name = "tests.duplicate-fleet"
        tenant_task = child

    with (
        patch(
            "django_isolated_tenants.celery.iter_tenants",
            return_value=[Tenant("same", "tenant_a"), Tenant("same", "tenant_b")],
        ),
        pytest.raises(TenantTaskMetadataInvalid, match="duplicate"),
    ):
        FleetTask().apply_async()


@pytest.mark.parametrize("option", ["task_id", "link", "link_error", "chain", "chord"])
def test_all_tenants_task_rejects_unsupported_canvas_options(option: str) -> None:
    class FleetTask(AllTenantsTask):
        name = "tests.unsupported-option"
        tenant_task = ConcreteTask()

    with pytest.raises(ValueError, match="does not (accept|support)"):
        FleetTask().apply_async(**{option: object()})


def test_all_tenants_task_requires_a_child_task() -> None:
    with pytest.raises(RuntimeError, match="no tenant child task"):
        AllTenantsTask().apply_async()


def test_task_metadata_and_explicit_tenant_are_validated() -> None:
    task = ConcreteTask()
    with pytest.raises(TypeError, match="requires a Tenant"):
        task.apply_async_for_tenant(object())  # type: ignore[arg-type]
    with pytest.raises(TenantTaskMetadataInvalid, match="requires identifier"):
        task.apply_async_for_tenant(Tenant("", "tenant_a"))


def test_tenant_task_decorator_supports_both_forms() -> None:
    @tenant_task
    def direct() -> None:
        return None

    @tenant_task(name="tests.configured")
    def configured() -> None:
        return None

    assert isinstance(direct, TenantTask)
    assert configured.name == "tests.configured"
