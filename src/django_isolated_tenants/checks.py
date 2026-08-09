"""Django system checks for unsupported cross-database relations."""

from typing import Any

from django.core import checks
from django.db.models import ForeignKey, ManyToManyField, OneToOneField

from .classification import ModelScope, classify_model


@checks.register(checks.Tags.models)
def check_cross_database_relations(app_configs: Any = None, **kwargs: Any) -> list[checks.Error]:
    from django.apps import apps

    models = apps.get_models(app_configs)
    errors: list[checks.Error] = []
    for model in models:
        source_scope = classify_model(model._meta.app_label, model._meta.model_name, model)
        for field in model._meta.get_fields():
            if not isinstance(field, (ForeignKey, OneToOneField, ManyToManyField)) or not getattr(
                field, "concrete", False
            ):
                continue
            related = getattr(field, "remote_field", None)
            target = getattr(related, "model", None)
            if target is None or target is model:
                continue
            target_scope = classify_model(target._meta.app_label, target._meta.model_name, target)
            if ModelScope.DEFAULT not in {source_scope, target_scope} and source_scope is not target_scope:
                errors.append(
                    checks.Error(
                        f"{model._meta.label}.{field.name} relates {target._meta.label} across "
                        "master and tenant databases.",
                        hint="Use a scalar identifier and application-level lookup instead of a database relation.",
                        id="isolated_tenants.E001",
                    )
                )
    return errors
