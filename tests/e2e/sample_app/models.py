from django.db import models

from django_isolated_tenants import MasterModel, TenantModel


class Workspace(MasterModel):
    slug = models.CharField(max_length=64, unique=True)
    tenant_alias = models.CharField(max_length=64, unique=True)


class Project(TenantModel):
    workspace_slug = models.CharField(max_length=64)
    name = models.CharField(max_length=128)


class AuditEvent(TenantModel):
    workspace_slug = models.CharField(max_length=64)
    action = models.CharField(max_length=128)
