"""add user phone and email

Revision ID: c3a7f54e8d20
Revises: 9d7e31c2a4b1
Create Date: 2026-06-19 02:10:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c3a7f54e8d20"
down_revision: str | None = "9d7e31c2a4b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("phone", sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column("email", sa.String(length=320), nullable=True))
        batch_op.create_index("ix_users_phone", ["phone"], unique=False)
        batch_op.create_index("ix_users_email", ["email"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_index("ix_users_email")
        batch_op.drop_index("ix_users_phone")
        batch_op.drop_column("email")
        batch_op.drop_column("phone")
