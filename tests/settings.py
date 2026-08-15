SECRET_KEY = "test"
INSTALLED_APPS = ["django.contrib.contenttypes", "django_isolated_tenants", "tests.e2e.sample_app"]
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
DATABASE_ROUTERS = ["django_isolated_tenants.router.TenantRouter"]
ISOLATED_TENANTS = {
    "PROVIDER": "tests.provider.provider",
    "MASTER_MODELS": ["contenttypes.contenttype"],
    "EXCLUDED_PATHS": [r"^/health/$"],
}
USE_TZ = True
