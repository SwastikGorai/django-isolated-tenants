SECRET_KEY = "test"
INSTALLED_APPS = ["django.contrib.contenttypes", "django_isolated_tenants"]
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
ISOLATED_TENANTS = {
    "PROVIDER": "tests.provider.provider",
    "SHARED_MODELS": ["contenttypes.contenttype"],
    "EXCLUDED_PATHS": [r"^/health/$"],
}
USE_TZ = True
