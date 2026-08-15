#!/bin/sh
set -eu

psql --set ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-SQL
    CREATE DATABASE isolated_tenants_acme;
    CREATE DATABASE isolated_tenants_globex;
SQL
