# Changelog

## 0.1.0 - 2026-07-19

- Initial release with request routing, dynamic connections, fleet migration commands, and optional Celery propagation.
## Unreleased

- Added explicit `MasterModel` and `TenantModel` bases, master-app classification,
  migration-safe routing, tenant layout inspection, and tenant-aware Celery
  task/fleet APIs.
- PostgreSQL support is available through the optional `postgres` extra (and is
  included by the `test` extra).
