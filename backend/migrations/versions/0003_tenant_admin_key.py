"""tenant admin key

Revision ID: 0003
Revises: 0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("tenants") as batch:
        batch.add_column(sa.Column("admin_key_hash", sa.String(length=64), nullable=True))
        batch.create_unique_constraint("uq_tenants_admin_key_hash", ["admin_key_hash"])


def downgrade() -> None:
    with op.batch_alter_table("tenants") as batch:
        batch.drop_constraint("uq_tenants_admin_key_hash", type_="unique")
        batch.drop_column("admin_key_hash")
