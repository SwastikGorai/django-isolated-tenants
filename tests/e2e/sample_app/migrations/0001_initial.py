from django.db import migrations, models

import django_isolated_tenants.models


class Migration(migrations.Migration):
    initial = True
    dependencies = []
    operations = [
        migrations.CreateModel(
            name="Workspace",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("slug", models.CharField(max_length=64, unique=True)),
                ("tenant_alias", models.CharField(max_length=64, unique=True)),
            ],
            options={"abstract": False},
            managers=[("_isolated_tenants_scope_marker", django_isolated_tenants.models._MasterModelMarkerManager())],
        ),
        migrations.CreateModel(
            name="Project",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("workspace_slug", models.CharField(max_length=64)),
                ("name", models.CharField(max_length=128)),
            ],
            options={"abstract": False},
            managers=[("_isolated_tenants_scope_marker", django_isolated_tenants.models._TenantModelMarkerManager())],
        ),
        migrations.CreateModel(
            name="AuditEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("workspace_slug", models.CharField(max_length=64)),
                ("action", models.CharField(max_length=128)),
            ],
            options={"abstract": False},
            managers=[("_isolated_tenants_scope_marker", django_isolated_tenants.models._TenantModelMarkerManager())],
        ),
    ]
