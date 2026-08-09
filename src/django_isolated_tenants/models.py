"""Model bases used to make database placement explicit."""

from django.db import models


class _ModelScopeMarkerManager(models.Manager):
    """Migration-serializable marker used by the central classifier."""

    use_in_migrations = True


class _MasterModelMarkerManager(_ModelScopeMarkerManager):
    _isolated_tenants_model_scope = "master"


class _TenantModelMarkerManager(_ModelScopeMarkerManager):
    _isolated_tenants_model_scope = "tenant"


class MasterModel(models.Model):
    """Abstract model whose table is always placed on the master database."""

    _isolated_tenants_scope_marker = _MasterModelMarkerManager()

    class Meta:
        abstract = True


class TenantModel(models.Model):
    """Abstract model whose table is placed only on tenant databases."""

    _isolated_tenants_scope_marker = _TenantModelMarkerManager()

    class Meta:
        abstract = True


__all__ = ["MasterModel", "TenantModel"]
