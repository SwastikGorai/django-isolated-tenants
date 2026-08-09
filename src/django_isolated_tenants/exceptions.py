class IsolatedTenantsError(Exception):
    """Base package error."""


class TenantContextMissing(IsolatedTenantsError):
    """Raised when tenant-scoped work has no active tenant."""


class TenantNotResolved(IsolatedTenantsError):
    """Raised when a request cannot be mapped to a tenant."""


class TenantDatabaseInvalid(IsolatedTenantsError):
    """Raised when a provider supplies an unsafe database configuration."""


class TenantTaskMetadataInvalid(IsolatedTenantsError):
    """A task did not contain valid package-owned tenant metadata."""
