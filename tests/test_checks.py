from unittest.mock import patch

from django.db import models

from django_isolated_tenants.checks import check_cross_database_relations
from django_isolated_tenants.models import MasterModel, TenantModel


class CheckMaster(MasterModel):
    class Meta:
        app_label = "check_models"


class CheckTenant(TenantModel):
    master = models.ForeignKey(CheckMaster, on_delete=models.CASCADE)

    class Meta:
        app_label = "check_models"


class SelfTenant(TenantModel):
    parent = models.ForeignKey("self", null=True, on_delete=models.CASCADE)

    class Meta:
        app_label = "check_models"


def test_cross_database_relation_is_reported() -> None:
    with patch("django.apps.apps.get_models", return_value=[CheckMaster, CheckTenant]):
        errors = check_cross_database_relations()
    assert [(error.id, error.obj) for error in errors] == [("isolated_tenants.E001", None)]
    assert "CheckTenant.master" in errors[0].msg


def test_self_relations_are_allowed() -> None:
    with patch("django.apps.apps.get_models", return_value=[SelfTenant]):
        assert check_cross_database_relations() == []
