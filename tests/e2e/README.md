# PostgreSQL end-to-end suite

This directory contains a small Django application that uses the package the
same way a consuming project does. The PostgreSQL suite verifies:

- host/request metadata resolving two independent tenants;
- ORM creates and queries staying inside the selected tenant database;
- master models remaining available on the control-plane database;
- excluded health endpoints and unknown-tenant fail-closed responses;
- service-layer work using explicit tenant context;
- tenant-aware Celery dispatch and all-tenant fan-out in eager mode;
- fleet migrations, migration reporting, and schema-layout inspection.

The normal CI job provisions two disposable PostgreSQL databases and sets the
required environment variables. Local runs skip these tests unless
`RUN_POSTGRES_E2E=1` is set. The required connection variables are:

- `E2E_POSTGRES_DB_ACME`
- `E2E_POSTGRES_DB_GLOBEX`
- `E2E_POSTGRES_USER`
- `E2E_POSTGRES_PASSWORD`
- `E2E_POSTGRES_HOST`
- `E2E_POSTGRES_PORT`

On Windows, run the complete suite through WSL. Docker Desktop must have WSL
integration enabled, and the selected distribution must provide `make`,
`docker`, and `uv`:

```console
wsl -e bash -lc 'cd /mnt/d/Projects/Work/M/PKGE/django-isolated-tenants && make test'
```

The Makefile starts PostgreSQL on `127.0.0.1:55432`, waits for its health
check, runs the E2E suite, and removes the container and its temporary data.
Use `make services-up`, `make services-logs`, and `make services-down` when
debugging. Override the host port with `make test-e2e POSTGRES_PORT=55433`.

To use PostgreSQL managed outside Compose, set the variables above and run:

```console
uv run pytest -m postgres_e2e -q
```

The databases must be disposable. The suite migrates them and deletes rows
from its own sample application tables between scenarios.
