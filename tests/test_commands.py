from io import StringIO
from unittest.mock import MagicMock, patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connections

from django_isolated_tenants import Tenant, TenantDatabase
from django_isolated_tenants.management.commands._fleet import selected_databases, tenant_snapshot


def test_migrate_forwards_options_and_cleans_every_alias() -> None:
    with patch("django.core.management.commands.migrate.Command.handle") as handle:
        call_command("migrate_tenants", tenant="tenant_a", plan=True, fake=True, verbosity=0)
    assert handle.call_args.kwargs["database"] == "tenant_a"
    assert handle.call_args.kwargs["plan"] is True
    assert handle.call_args.kwargs["fake"] is True
    assert "tenant_a" not in connections.databases


def test_migrate_continues_and_combines_failures() -> None:
    with (
        patch(
            "django.core.management.commands.migrate.Command.handle", side_effect=[ValueError("one"), TypeError("two")]
        ),
        pytest.raises(CommandError, match="tenant_a.*tenant_b"),
    ):
        call_command("migrate_tenants", verbosity=0)
    assert "tenant_a" not in connections.databases
    assert "tenant_b" not in connections.databases


def test_show_single_tenant_forwards_and_missing_filters() -> None:
    output = StringIO()
    with patch(
        "django.core.management.commands.showmigrations.Command.handle",
        autospec=True,
        side_effect=lambda command, *args, **kwargs: command.stdout.write("[X] applied\n[ ] missing"),
    ) as handle:
        call_command("show_tenant_migrations", tenant="tenant_b", missing=True, stdout=output, verbosity=0)
    assert handle.call_args.kwargs["database"] == "tenant_b"
    assert "missing" in output.getvalue()
    assert "applied" not in output.getvalue()
    assert "tenant_b" not in connections.databases


def test_unknown_tenant_is_an_error() -> None:
    with pytest.raises(CommandError, match="Unknown"):
        call_command("migrate_tenants", tenant="missing", verbosity=0)


def test_show_all_tenants_continues_after_failure() -> None:
    output = StringIO()
    with (
        patch("django.core.management.commands.showmigrations.Command.handle", side_effect=[ValueError("one"), None]),
        pytest.raises(CommandError, match="tenant_a.*ValueError.*one"),
    ):
        call_command("show_tenant_migrations", stdout=output, verbosity=0)
    assert "Tenant: tenant_a" in output.getvalue()
    assert "Tenant: tenant_b" in output.getvalue()
    assert "tenant_a" not in connections.databases
    assert "tenant_b" not in connections.databases


def test_fleet_provider_output_is_validated() -> None:
    with patch("django_isolated_tenants.management.commands._fleet.get_provider") as get_provider:
        get_provider.return_value.iter_databases.return_value = [
            TenantDatabase("same", {}),
            TenantDatabase("same", {}),
        ]
        with pytest.raises(CommandError, match="duplicate database aliases"):
            selected_databases(None)

        get_provider.return_value.iter_tenants.return_value = [Tenant("same", "a"), Tenant("same", "b")]
        with pytest.raises(CommandError, match="duplicate tenant identifiers"):
            tenant_snapshot()


@pytest.mark.django_db
def test_layout_command_reports_discrepancies_and_cleans_alias() -> None:
    master_introspection = MagicMock(table_names=lambda: [])
    with (
        patch("django_isolated_tenants.management.commands.check_tenant_layout.apps.get_models", return_value=[]),
        patch("django.db.utils.ConnectionHandler.__getitem__") as item,
        pytest.raises(CommandError, match="inspection failed"),
    ):
        item.side_effect = [MagicMock(introspection=master_introspection), RuntimeError("offline")]
        call_command("check_tenant_layout", tenant="tenant_a", verbosity=0)
    assert "tenant_a" not in connections.databases


@pytest.mark.django_db
def test_layout_command_succeeds_for_empty_expected_layout() -> None:
    output = StringIO()
    with (
        patch("django_isolated_tenants.management.commands.check_tenant_layout.apps.get_models", return_value=[]),
        patch("django_isolated_tenants.management.commands.check_tenant_layout.selected_databases", return_value=[]),
    ):
        call_command("check_tenant_layout", stdout=output, verbosity=0)
    assert "matches expected" in output.getvalue()
