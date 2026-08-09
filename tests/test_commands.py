from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connections


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
