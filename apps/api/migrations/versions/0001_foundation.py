"""foundation

Revision ID: c56238feadc4
Revises:
Create Date: 2026-07-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "c56238feadc4"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

transaction_type = sa.Enum("expense", "income", "saving", name="transaction_type")
transaction_direction = sa.Enum("normal", "reversal", name="transaction_direction")


def upgrade() -> None:
    op.create_table(
        "user_settings",
        sa.Column("telegram_user_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("singleton_slot", sa.SmallInteger(), server_default="1", nullable=False),
        sa.Column("timezone", sa.String(length=64), server_default="Europe/Moscow", nullable=False),
        sa.Column("base_currency", sa.String(length=3), server_default="RUB", nullable=False),
        sa.CheckConstraint("singleton_slot = 1", name="ck_user_settings_singleton_slot"),
        sa.PrimaryKeyConstraint("telegram_user_id"),
        sa.UniqueConstraint("singleton_slot", name="uq_user_settings_singleton_slot"),
    )
    op.create_table(
        "login_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("owner", sa.BigInteger(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["owner"], ["user_settings.telegram_user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_table(
        "transactions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner", sa.BigInteger(), nullable=False),
        sa.Column("type", transaction_type, nullable=False),
        sa.Column("direction", transaction_direction, server_default="normal", nullable=False),
        sa.Column("amount_kopecks", sa.BigInteger(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("source_event_id", sa.String(length=255), nullable=True),
        sa.CheckConstraint("amount_kopecks > 0", name="ck_transactions_amount_kopecks_positive"),
        sa.ForeignKeyConstraint(["owner"], ["user_settings.telegram_user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source", "source_event_id", name="uq_transactions_source_event"),
    )
    op.create_index("ix_transactions_occurred_at", "transactions", ["occurred_at"])
    op.create_index("ix_transactions_owner", "transactions", ["owner"])
    op.create_table(
        "web_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("owner", sa.BigInteger(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["owner"], ["user_settings.telegram_user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )


def downgrade() -> None:
    op.drop_table("web_sessions")
    op.drop_index("ix_transactions_owner", table_name="transactions")
    op.drop_index("ix_transactions_occurred_at", table_name="transactions")
    op.drop_table("transactions")
    op.drop_table("login_tokens")
    op.drop_table("user_settings")
    transaction_direction.drop(op.get_bind(), checkfirst=False)
    transaction_type.drop(op.get_bind(), checkfirst=False)
