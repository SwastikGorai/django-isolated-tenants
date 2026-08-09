from typing import Any

from django.core.management.commands.migrate import Command as MigrateCommand

from ...connections import redacted_config, register_database, remove_database
from ...context import tenant_context
from ._fleet import failure_summary, selected_databases, tenant_for_alias


class Command(MigrateCommand):
    help: str = "Run Django migrations across tenant databases"

    def add_arguments(self, parser: Any) -> None:
        super().add_arguments(parser)
        parser.add_argument("--tenant", help="Migrate only the selected tenant database alias")

    def handle(self, *args: object, **options: Any) -> None:
        failures: list[tuple[str, BaseException]] = []
        tenant = options.pop("tenant", None)
        for database in selected_databases(tenant):
            self.stdout.write(f"Migrating tenant '{database.alias}' ({redacted_config(database.config)})")
            try:
                register_database(database)
                with tenant_context(tenant_for_alias(database.alias)):
                    super().handle(*args, **{**options, "database": database.alias})
            except Exception as error:  # continue the fleet and report once
                failures.append((database.alias, error))
                self.stderr.write(self.style.ERROR(f"Tenant '{database.alias}' failed: {error}"))
            finally:
                remove_database(database.alias)
        if failures:
            raise failure_summary("migrate_tenants", failures)
