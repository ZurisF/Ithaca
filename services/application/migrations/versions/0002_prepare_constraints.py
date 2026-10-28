"""Enforce task identity and opaque local source handles.

Revision ID: 0002_prepare_constraints
Revises: 0001_core_schema
"""

from alembic import op

revision = "0002_prepare_constraints"
down_revision = "0001_core_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE app.interview_sessions
        ADD CONSTRAINT session_source_handle_opaque
        CHECK (source_handle IS NULL OR source_handle ~ '^[A-Za-z0-9_-]{43}$')
    """)
    op.execute("""
        CREATE UNIQUE INDEX post_tasks_natural
        ON app.post_tasks (session_id, kind, COALESCE(turn_no, 0))
    """)


def downgrade() -> None:
    op.execute("DROP INDEX app.post_tasks_natural")
    op.execute("ALTER TABLE app.interview_sessions DROP CONSTRAINT session_source_handle_opaque")
