from django.apps import AppConfig


class SampleAppConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "tests.e2e.sample_app"
    label = "e2e_sample_app"
