#!/usr/bin/env bash
# Local Postgres helper for running the FULL suite without Docker.
#
# This machine already has a system PostgreSQL 12 on :5432, so we run a
# Homebrew Postgres (with pgvector) on :5433 instead and point the app there.
# (In CI / with Docker, use docker-compose.yml on :5432 — see README.)
#
# Usage:
#   scripts/dev_db.sh start   # start pg on :5433, create rcm db/roles/extension
#   scripts/dev_db.sh migrate # alembic upgrade head
#   scripts/dev_db.sh reset   # drop + recreate + migrate (clean slate)
#   scripts/dev_db.sh stop    # stop the cluster
#   scripts/dev_db.sh env     # print the env exports to eval in your shell
set -euo pipefail

PG_PREFIX="${RCM_PG_PREFIX:-/opt/homebrew/opt/postgresql@17}"
PG_DATA="${RCM_PG_DATA:-/opt/homebrew/var/postgresql@17}"
PG_PORT="${RCM_PG_PORT:-5433}"
PG_LOG="${RCM_PG_LOG:-/opt/homebrew/var/log/postgresql-rcm-${PG_PORT}.log}"
SUPERUSER="${RCM_PG_SUPERUSER:-$(whoami)}"
export PATH="$PG_PREFIX/bin:$PATH"
export LC_ALL="en_US.UTF-8" LANG="en_US.UTF-8" PGCONNECT_TIMEOUT=5

PSQL_SU=(psql -h localhost -p "$PG_PORT" -U "$SUPERUSER")

print_env() {
  cat <<EOF
export RCM_MASTER_KEY="\${RCM_MASTER_KEY:-\$(python -m rcm.core.crypto keygen)}"
export RCM_EMBEDDING_DIM=64
export RCM_DATABASE_URL="postgresql+psycopg://rcm_app:rcm_app_pw@localhost:${PG_PORT}/rcm"
export RCM_MIGRATION_DATABASE_URL="postgresql+psycopg://rcm_migrator:rcm_migrator_pw@localhost:${PG_PORT}/rcm"
EOF
}

start() {
  pg_ctl -D "$PG_DATA" status >/dev/null 2>&1 || \
    pg_ctl -D "$PG_DATA" -o "-p $PG_PORT" -l "$PG_LOG" start
  for _ in $(seq 1 20); do pg_isready -h localhost -p "$PG_PORT" -q && break; sleep 1; done
  "${PSQL_SU[@]}" -d postgres -qv ON_ERROR_STOP=1 <<'SQL'
DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='rcm_migrator') THEN
    CREATE ROLE rcm_migrator LOGIN PASSWORD 'rcm_migrator_pw' CREATEDB; END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='rcm_app') THEN
    CREATE ROLE rcm_app LOGIN PASSWORD 'rcm_app_pw'; END IF;
END $$;
SQL
  "${PSQL_SU[@]}" -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='rcm'" \
    | grep -q 1 || createdb -h localhost -p "$PG_PORT" -U "$SUPERUSER" -O rcm_migrator rcm
  "${PSQL_SU[@]}" -d rcm -qc \
    "CREATE EXTENSION IF NOT EXISTS vector; GRANT USAGE ON SCHEMA public TO rcm_app;"
  echo "pg ready on :$PG_PORT — db 'rcm', roles rcm_app/rcm_migrator, pgvector enabled"
}

case "${1:-}" in
  start) start ;;
  stop)  pg_ctl -D "$PG_DATA" stop -m fast ;;
  migrate)
    export RCM_MIGRATION_DATABASE_URL="postgresql+psycopg://rcm_migrator:rcm_migrator_pw@localhost:${PG_PORT}/rcm"
    : "${RCM_MASTER_KEY:?set RCM_MASTER_KEY (python -m rcm.core.crypto keygen)}"
    alembic upgrade head ;;
  reset)
    dropdb -h localhost -p "$PG_PORT" -U "$SUPERUSER" --if-exists rcm
    createdb -h localhost -p "$PG_PORT" -U "$SUPERUSER" -O rcm_migrator rcm
    "${PSQL_SU[@]}" -d rcm -qc \
      "CREATE EXTENSION IF NOT EXISTS vector; GRANT USAGE ON SCHEMA public TO rcm_app;"
    export RCM_MIGRATION_DATABASE_URL="postgresql+psycopg://rcm_migrator:rcm_migrator_pw@localhost:${PG_PORT}/rcm"
    : "${RCM_MASTER_KEY:?set RCM_MASTER_KEY}"; alembic upgrade head
    echo "reset complete" ;;
  env) print_env ;;
  *) echo "usage: $0 {start|stop|migrate|reset|env}" >&2; exit 2 ;;
esac
