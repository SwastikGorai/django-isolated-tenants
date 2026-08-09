import pytest
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.db.migrations.state import ModelState, ProjectState

from django_isolated_tenants import MasterModel, Tenant, TenantContextMissing, tenant_context
from django_isolated_tenants.connections import register_database, remove_database
from django_isolated_tenants.models import TenantModel
from django_isolated_tenants.router import TenantRouter
from tests.provider import database


class ExplicitTenant(TenantModel):
    class Meta:
        app_label = "shop"


class ExplicitMaster(MasterModel):
    class Meta:
        app_label = "control"


class UnmarkedModel(models.Model):
    class Meta:
        app_label = "legacy"


def object_on(model: type[models.Model], alias: str | None) -> models.Model:
    value = model()
    value._state.db = alias
    return value


def test_router_is_fail_closed_and_shared_models_use_master() -> None:
    router = TenantRouter()
    assert router.db_for_read(ContentType) == "default"
    with pytest.raises(TenantContextMissing):
        router.db_for_read(ExplicitTenant)
    with tenant_context(Tenant("id", "tenant_a")):
        assert router.db_for_read(ExplicitTenant) == "tenant_a"
        assert router.db_for_write(ExplicitTenant) == "tenant_a"
    assert router.db_for_read(UnmarkedModel) is None
    assert router.db_for_write(UnmarkedModel) is None


def test_router_rejects_replica_writes_and_decides_known_relations() -> None:
    router = TenantRouter()
    with tenant_context(Tenant("id", "tenant_a_replica")), pytest.raises(TenantContextMissing):
        router.db_for_write(ExplicitTenant)
    assert router.allow_relation(object_on(ExplicitTenant, "a"), object_on(ExplicitTenant, "a")) is True
    assert router.allow_relation(object_on(ExplicitTenant, "a"), object_on(ExplicitTenant, "b")) is False
    assert router.allow_relation(object_on(UnmarkedModel, "a"), object_on(ExplicitTenant, "a")) is None
    assert router.allow_migrate("a", "shop") is None


def test_explicit_scopes_control_migrations_and_unmarked_models_defer() -> None:
    router = TenantRouter()
    assert router.allow_migrate("default", "control", "explicitmaster", model=ExplicitMaster) is True
    assert router.allow_migrate("default", "shop", "explicittenant", model=ExplicitTenant) is False
    assert router.allow_migrate("default", "legacy", "unmarkedmodel", model=UnmarkedModel) is None
    register_database(database("tenant_a"))
    try:
        assert router.allow_migrate("tenant_a", "shop", "explicittenant", model=ExplicitTenant) is True
        assert router.allow_migrate("tenant_a", "control", "explicitmaster", model=ExplicitMaster) is False
        assert router.allow_migrate("tenant_a", "legacy", "unmarkedmodel", model=UnmarkedModel) is None
    finally:
        remove_database("tenant_a")


def test_model_scope_markers_survive_migration_state_rendering() -> None:
    state = ProjectState()
    state.add_model(ModelState.from_model(ExplicitMaster))
    state.add_model(ModelState.from_model(ExplicitTenant))
    rendered_master = state.apps.get_model("control", "ExplicitMaster")
    rendered_tenant = state.apps.get_model("shop", "ExplicitTenant")
    router = TenantRouter()
    assert router.allow_migrate("default", "control", "explicitmaster", model=rendered_master) is True
    assert router.allow_migrate("default", "shop", "explicittenant", model=rendered_tenant) is False
