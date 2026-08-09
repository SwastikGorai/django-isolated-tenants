import pytest
from django.db import models

from django_isolated_tenants import MasterModel, TenantModel


class CustomManager(models.Manager):
    pass


class BareMaster(MasterModel):
    class Meta:
        app_label = "model_manager_tests"


class BareTenant(TenantModel):
    class Meta:
        app_label = "model_manager_tests"


class CustomMaster(MasterModel):
    objects = CustomManager()

    class Meta:
        app_label = "model_manager_tests"


class CustomTenant(TenantModel):
    objects = CustomManager()

    class Meta:
        app_label = "model_manager_tests"


@pytest.mark.parametrize("model", [BareMaster, BareTenant])
def test_concrete_subclass_gets_objects_and_scope_marker(model: type[models.Model]) -> None:
    assert model.objects is model._default_manager
    assert model._default_manager.name == "objects"
    assert "_isolated_tenants_scope_marker" in {manager.name for manager in model._meta.managers}


@pytest.mark.parametrize("model", [CustomMaster, CustomTenant])
def test_custom_objects_manager_remains_default(model: type[models.Model]) -> None:
    assert model.objects is model._default_manager
    assert model._default_manager.name == "objects"
    assert isinstance(model._default_manager, CustomManager)
