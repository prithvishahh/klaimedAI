-- Bootstrap the database, extension, and least-privilege roles.
-- Runs once on first container start (mounted into docker-entrypoint-initdb.d).
--
-- Two roles (spec §9 least privilege):
--   rcm_migrator : owns the schema, runs Alembic (DDL).
--   rcm_app      : the runtime app role. Table grants (including the
--                  append-only audit_log restriction) are applied by the
--                  Alembic migration, after the tables exist.

CREATE EXTENSION IF NOT EXISTS vector;

DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'rcm_migrator') THEN
    CREATE ROLE rcm_migrator LOGIN PASSWORD 'rcm_migrator_pw';
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'rcm_app') THEN
    CREATE ROLE rcm_app LOGIN PASSWORD 'rcm_app_pw';
  END IF;
END
$$;

-- Migrator owns everything it creates.
ALTER SCHEMA public OWNER TO rcm_migrator;
GRANT ALL ON SCHEMA public TO rcm_migrator;
-- App role may use the schema; per-table DML grants come from the migration.
GRANT USAGE ON SCHEMA public TO rcm_app;
