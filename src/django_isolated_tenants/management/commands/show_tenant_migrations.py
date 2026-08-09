from typing import Any

from django.core.management.commands.showmigrations import Command as ShowMigrationsCommand

from ...connections import register_database, remove_database
from ._fleet import failure_summary, selected_databases


class Command(ShowMigrationsCommand):
    help: str = "Show migration state across tenant databases"

    def add_arguments(self, parser: Any) -> None:
        super().add_arguments(parser)
        parser.add_argument("--tenant", help="Inspect only the selected tenant database alias")
        parser.add_argument("--missing", action="store_true", help="Show only unapplied migrations")

    def handle(self, *args: object, **options: Any) -> None:
        failures: list[tuple[str, BaseException]] = []
        tenant = options.pop("tenant", None)
        missing = bool(options.pop("missing", False))
        for database in selected_databases(tenant):
            self.stdout.write(self.style.MIGRATE_HEADING(f"Tenant: {database.alias}"))
            try:
                register_database(database)
                if missing:
                    options["list"] = True
                    output = self._capture_show(*args, **{**options, "database": database.alias})
                    lines = [line for line in output.splitlines() if "[ ]" in line]
                    if lines:
                        self.stdout.write("\n".join(lines))
                else:
                    super().handle(*args, **{**options, "database": database.alias})
            except Exception as error:  # continue the fleet and report once
                failures.append((database.alias, error))
                self.stderr.write(self.style.ERROR(f"Tenant '{database.alias}' failed: {error}"))
            finally:
                remove_database(database.alias)
        if failures:
            raise failure_summary("show_tenant_migrations", failures)

    def _capture_show(self, *args: object, **options: Any) -> str:
        from io import StringIO

        original = self.stdout
        stream = StringIO()
        self.stdout = type(original)(stream)
        try:
            super().handle(*args, **options)
            return stream.getvalue()
        finally:
            self.stdout = original
