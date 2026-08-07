"""category catalog and transaction metadata

Revision ID: a841bc64e210
Revises: c56238feadc4
Create Date: 2026-07-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "a841bc64e210"
down_revision: str | None = "c56238feadc4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

transaction_type = postgresql.ENUM(
    "expense", "income", "saving", name="transaction_type", create_type=False
)
category_source = postgresql.ENUM(
    "learned", "rules", "ai", "manual", "fallback", name="category_source"
)

CATEGORY_ROWS = (
    ("expense.groceries", "expense", "Продукты", 1),
    ("expense.cafes", "expense", "Кафе и рестораны", 2),
    ("expense.transport", "expense", "Транспорт", 3),
    ("expense.housing", "expense", "Жильё", 4),
    ("expense.health", "expense", "Здоровье", 5),
    ("expense.shopping", "expense", "Покупки", 6),
    ("expense.entertainment", "expense", "Развлечения", 7),
    ("expense.subscriptions", "expense", "Подписки", 8),
    ("expense.travel", "expense", "Путешествия", 9),
    ("expense.education", "expense", "Образование", 10),
    ("expense.gifts", "expense", "Подарки", 11),
    ("expense.other", "expense", "Прочее", 12),
    ("income.salary", "income", "Зарплата", 1),
    ("income.investments", "income", "Инвестиционный доход", 2),
    ("income.refunds", "income", "Возвраты", 3),
    ("income.gifts", "income", "Подарки", 4),
    ("income.other", "income", "Прочее", 5),
)


def upgrade() -> None:
    category_source.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "categories",
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("transaction_type", transaction_type, nullable=False),
        sa.Column("name_ru", sa.String(length=80), nullable=False),
        sa.Column("sort_order", sa.SmallInteger(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.PrimaryKeyConstraint("code"),
        sa.UniqueConstraint(
            "code", "transaction_type", name="uq_categories_code_transaction_type"
        ),
    )
    categories = sa.table(
        "categories",
        sa.column("code", sa.String()),
        sa.column("transaction_type", transaction_type),
        sa.column("name_ru", sa.String()),
        sa.column("sort_order", sa.SmallInteger()),
        sa.column("is_active", sa.Boolean()),
    )
    op.bulk_insert(
        categories,
        [
            {
                "code": code,
                "transaction_type": row_type,
                "name_ru": name_ru,
                "sort_order": sort_order,
                "is_active": True,
            }
            for code, row_type, name_ru, sort_order in CATEGORY_ROWS
        ],
    )

    op.add_column(
        "transactions", sa.Column("category_code", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "transactions", sa.Column("category_source", category_source, nullable=True)
    )
    op.add_column(
        "transactions", sa.Column("category_confidence", sa.SmallInteger(), nullable=True)
    )
    op.add_column(
        "transactions", sa.Column("needs_category_review", sa.Boolean(), nullable=True)
    )
    op.execute(
        """
        UPDATE transactions
        SET category_code = CASE type::text
            WHEN 'expense' THEN 'expense.other'
            WHEN 'income' THEN 'income.other'
        END,
        category_source = 'fallback', category_confidence = 0,
        needs_category_review = true
        WHERE type::text IN ('expense', 'income')
        """
    )
    op.create_foreign_key(
        "fk_transactions_category_type",
        "transactions",
        "categories",
        ["category_code", "type"],
        ["code", "transaction_type"],
    )
    op.create_check_constraint(
        "ck_transactions_category_metadata_complete",
        "transactions",
        "(type = 'saving' AND category_code IS NULL AND category_source IS NULL "
        "AND category_confidence IS NULL AND needs_category_review IS NULL) OR "
        "(type IN ('expense', 'income') AND category_code IS NOT NULL "
        "AND category_source IS NOT NULL AND category_confidence IS NOT NULL "
        "AND category_confidence BETWEEN 0 AND 100 "
        "AND needs_category_review IS NOT NULL)",
    )

    op.create_table(
        "category_corrections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner", sa.BigInteger(), nullable=False),
        sa.Column("transaction_type", transaction_type, nullable=False),
        sa.Column("normalized_description", sa.Text(), nullable=False),
        sa.Column("category_code", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["category_code"], ["categories.code"]),
        sa.ForeignKeyConstraint(
            ["owner"], ["user_settings.telegram_user_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "owner",
            "transaction_type",
            "normalized_description",
            name="uq_category_corrections_owner_type_description",
        ),
    )


def downgrade() -> None:
    op.drop_table("category_corrections")
    op.drop_constraint(
        "ck_transactions_category_metadata_complete", "transactions", type_="check"
    )
    op.drop_constraint("fk_transactions_category_type", "transactions", type_="foreignkey")
    op.drop_column("transactions", "needs_category_review")
    op.drop_column("transactions", "category_confidence")
    op.drop_column("transactions", "category_source")
    op.drop_column("transactions", "category_code")
    op.drop_table("categories")
    category_source.drop(op.get_bind(), checkfirst=True)
