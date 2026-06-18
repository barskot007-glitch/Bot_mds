"""add text library and extended user profile

Revision ID: 9d7e31c2a4b1
Revises: f1bf8828eaf3
Create Date: 2026-06-18 20:30:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "9d7e31c2a4b1"
down_revision: str | None = "f1bf8828eaf3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("participation_history", sa.Text(), nullable=True))

    op.create_table(
        "bot_texts",
        sa.Column("text_key", sa.String(length=64), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("created_by_admin_id", sa.String(length=36), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["created_by_admin_id"],
            ["admins.id"],
            name=op.f("fk_bot_texts_created_by_admin_id_admins"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_bot_texts")),
    )
    with op.batch_alter_table("bot_texts", schema=None) as batch_op:
        batch_op.create_index(
            "ix_bot_texts_key_active_position",
            ["text_key", "is_active", "position"],
            unique=False,
        )
        batch_op.create_index(batch_op.f("ix_bot_texts_text_key"), ["text_key"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("bot_texts", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_bot_texts_text_key"))
        batch_op.drop_index("ix_bot_texts_key_active_position")
    op.drop_table("bot_texts")

    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("participation_history")
