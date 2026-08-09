"""Pure model-scope classification used by routers and checks."""

from enum import StrEnum
from typing import Any

from .conf import get_settings


class ModelScope(StrEnum):
    MASTER = "master"
    TENANT = "tenant"
    DEFAULT = "default"


def _label(app_label: str, model_name: str | None = None) -> str:
    return f"{app_label}.{model_name}".lower() if model_name else app_label.lower()


def _marked_scope(model: Any) -> ModelScope | None:
    meta = getattr(model, "_meta", None)
    if meta is None:
        return None
    for manager in getattr(meta, "managers", ()):
        value = getattr(manager, "_isolated_tenants_model_scope", None)
        if value in {ModelScope.MASTER, ModelScope.TENANT}:
            return ModelScope(value)
    return None


def classify_model(
    app_label: str,
    model_name: str | None = None,
    model: Any | None = None,
) -> ModelScope:
    config = get_settings()
    app = app_label.lower()
    label = _label(app_label, model_name or getattr(getattr(model, "_meta", None), "model_name", None))
    if app in config.master_apps:
        return ModelScope.MASTER
    if label in config.master_models:
        return ModelScope.MASTER
    if model is not None:
        marked = _marked_scope(model)
        if marked is not None:
            return marked
    return ModelScope.DEFAULT


__all__ = ["ModelScope", "classify_model"]
