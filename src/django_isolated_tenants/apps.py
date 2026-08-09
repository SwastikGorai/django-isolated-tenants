from django.apps import AppConfig


class IsolatedTenantsConfig(AppConfig):
    name: str = "django_isolated_tenants"
    verbose_name: str = "Isolated tenants"

    def ready(self) -> None:
        from . import checks  # noqa: F401
