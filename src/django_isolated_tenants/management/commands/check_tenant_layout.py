from typing import Any

from django.apps import apps
from django.core.management.base import BaseCommand, CommandError
from django.db import connections

from ...classification import ModelScope, classify_model
from ...conf import get_settings
from ...connections import register_database, remove_database
from ._fleet import selected_databases


class Command(BaseCommand):
    help = "Inspect master and tenant table placement without changing schemas"

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--tenant", help="Inspect only one tenant database alias")

    def handle(self, *args: object, **options: Any) -> None:
        master_alias = get_settings().master_alias
        managed = [model for model in apps.get_models() if not model._meta.proxy and model._meta.managed]
        expected_master = {
            model._meta.db_table
            for model in managed
            if classify_model(model._meta.app_label, model._meta.model_name, model) is ModelScope.MASTER
        }
        expected_tenant = {
            model._meta.db_table
            for model in managed
            if classify_model(model._meta.app_label, model._meta.model_name, model) is ModelScope.TENANT
        }
        discrepancies: list[str] = []
        master_tables = set(connections[master_alias].introspection.table_names())
        discrepancies.extend(
            f"master missing expected table {table}" for table in sorted(expected_master - master_tables)
        )
        discrepancies.extend(
            f"tenant table unexpectedly on master: {table}" for table in sorted(expected_tenant & master_tables)
        )
        for database in selected_databases(options.get("tenant")):
            try:
                register_database(database)
                tables = set(connections[database.alias].introspection.table_names())
                discrepancies.extend(
                    f"{database.alias}: master table unexpectedly present: {table}"
                    for table in sorted(expected_master & tables)
                )
                discrepancies.extend(
                    f"{database.alias}: missing expected tenant table {table}"
                    for table in sorted(expected_tenant - tables)
                )
            except Exception as error:
                discrepancies.append(f"{database.alias}: inspection failed ({type(error).__name__})")
            finally:
                remove_database(database.alias)
        if discrepancies:
            raise CommandError("Tenant layout discrepancies: " + "; ".join(discrepancies))
        self.stdout.write(self.style.SUCCESS("Tenant layout matches expected model placement."))
