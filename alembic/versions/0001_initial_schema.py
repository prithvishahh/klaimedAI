"""Initial schema + append-only audit log + least-privilege grants.

Revision ID: 0001
Revises:
Create Date: 2026-07-13

Creates all Phase 0 tables, then applies the two compliance-critical database
controls that cannot live in application code:

  * an **append-only** audit log — a trigger raises on any UPDATE/DELETE of
    ``audit_log`` (defense in depth alongside the role grants);
  * **least-privilege grants** — the runtime ``rcm_app`` role gets full DML on
    working tables but only SELECT/INSERT on ``audit_log`` and
    ``guardrail_block`` (it cannot rewrite history).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from rcm.models import Base

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_APPEND_ONLY_TABLES = ("audit_log", "guardrail_block")

# NB: no '%' anywhere in these statements — psycopg treats '%' as a parameter
# marker. Dynamic identifiers use quote_ident() concatenation, and the trigger
# message is a constant.
_TRIGGER_FN_SQL = """
CREATE OR REPLACE FUNCTION rcm_prevent_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_log is append-only; UPDATE/DELETE is not permitted';
END;
$$ LANGUAGE plpgsql;
"""

_TRIGGER_SQL = """
CREATE TRIGGER audit_log_append_only
    BEFORE UPDATE OR DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION rcm_prevent_mutation();
"""

# Grants run only if the app role exists (it won't in some ephemeral CI DBs).
_GRANTS_SQL = """
DO $$
DECLARE t text;
BEGIN
    IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'rcm_app') THEN
        -- Full DML on working tables.
        FOR t IN
            SELECT tablename FROM pg_tables
            WHERE schemaname = 'public'
              AND tablename NOT IN ('audit_log', 'guardrail_block')
        LOOP
            EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON public.'
                || quote_ident(t) || ' TO rcm_app';
        END LOOP;
        -- Append-only compliance tables: no UPDATE/DELETE grant.
        GRANT SELECT, INSERT ON public.audit_log TO rcm_app;
        GRANT SELECT, INSERT ON public.guardrail_block TO rcm_app;
    END IF;
END
$$;
"""


def upgrade() -> None:
    bind = op.get_bind()
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    # Create all mapped tables from the SQLAlchemy metadata.
    Base.metadata.create_all(bind=bind)
    op.execute(_TRIGGER_FN_SQL)
    op.execute(_TRIGGER_SQL)
    op.execute(_GRANTS_SQL)


def downgrade() -> None:
    bind = op.get_bind()
    op.execute("DROP TRIGGER IF EXISTS audit_log_append_only ON audit_log")
    op.execute("DROP FUNCTION IF EXISTS rcm_prevent_mutation()")
    Base.metadata.drop_all(bind=bind)
