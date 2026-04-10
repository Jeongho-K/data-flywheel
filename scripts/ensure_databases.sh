#!/bin/sh
# Idempotently ensure every database listed in POSTGRES_MULTIPLE_DATABASES
# exists in the running PostgreSQL instance.
#
# Unlike scripts/create-multiple-databases.sh (which only runs on a fresh
# data volume via /docker-entrypoint-initdb.d/), this script is designed
# to run on EVERY startup as a one-shot sidecar. It uses the PG* env
# vars to connect to an already-running PostgreSQL and creates any
# missing databases. Safe to re-run — existing databases are left alone.
#
# Required env:
#   PGHOST, PGPORT, PGUSER, PGPASSWORD
#   POSTGRES_MULTIPLE_DATABASES  — comma-separated database names

set -eu

: "${POSTGRES_MULTIPLE_DATABASES:?POSTGRES_MULTIPLE_DATABASES not set}"
: "${PGUSER:?PGUSER not set}"

echo "ensure_databases: ensuring [$POSTGRES_MULTIPLE_DATABASES]"

# Wait briefly for Postgres if the healthcheck hasn't caught up yet.
for i in 1 2 3 4 5 6 7 8 9 10; do
    if psql -d postgres -c 'SELECT 1' >/dev/null 2>&1; then
        break
    fi
    echo "ensure_databases: waiting for postgres ($i/10)..."
    sleep 2
done

for db in $(echo "$POSTGRES_MULTIPLE_DATABASES" | tr ',' ' '); do
    db_trimmed=$(echo "$db" | tr -d '[:space:]')
    [ -z "$db_trimmed" ] && continue
    exists=$(psql -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname = '$db_trimmed'" || echo "")
    if [ "$exists" = "1" ]; then
        echo "ensure_databases: '$db_trimmed' already exists"
    else
        echo "ensure_databases: creating '$db_trimmed'"
        psql -d postgres -v ON_ERROR_STOP=1 -c "CREATE DATABASE \"$db_trimmed\";"
        psql -d postgres -v ON_ERROR_STOP=1 -c "GRANT ALL PRIVILEGES ON DATABASE \"$db_trimmed\" TO \"$PGUSER\";"
    fi
done

echo "ensure_databases: done"
