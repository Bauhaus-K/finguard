"""audit_records append-only triggers

Revision ID: 0002
Revises: 0001
"""

from collections.abc import Sequence

from alembic import op

from app.db.audit_guards import trigger_statements

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for stmt in trigger_statements(op.get_bind().dialect.name):
        op.execute(stmt)


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS audit_records_no_update")
        op.execute("DROP TRIGGER IF EXISTS audit_records_no_delete")
    elif dialect == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS audit_records_no_modify ON audit_records")
        op.execute("DROP FUNCTION IF EXISTS audit_records_append_only()")
