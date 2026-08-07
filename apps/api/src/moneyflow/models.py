import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    select,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, column_property, mapped_column


class Base(DeclarativeBase):
    pass


class TransactionType(enum.StrEnum):
    EXPENSE = "expense"
    INCOME = "income"
    SAVING = "saving"


class CategorySource(enum.StrEnum):
    LEARNED = "learned"
    RULES = "rules"
    AI = "ai"
    MANUAL = "manual"
    FALLBACK = "fallback"


class TransactionDirection(enum.StrEnum):
    NORMAL = "normal"
    REVERSAL = "reversal"


class UserSettings(Base):
    __tablename__ = "user_settings"
    __table_args__ = (
        CheckConstraint("singleton_slot = 1", name="ck_user_settings_singleton_slot"),
        UniqueConstraint("singleton_slot", name="uq_user_settings_singleton_slot"),
    )

    telegram_user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    singleton_slot: Mapped[int] = mapped_column(
        SmallInteger, default=1, server_default="1", nullable=False
    )
    timezone: Mapped[str] = mapped_column(
        String(64), default="Europe/Moscow", server_default="Europe/Moscow"
    )
    base_currency: Mapped[str] = mapped_column(String(3), default="RUB", server_default="RUB")


class Category(Base):
    __tablename__ = "categories"
    __table_args__ = (
        UniqueConstraint("code", "transaction_type", name="uq_categories_code_transaction_type"),
    )

    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    transaction_type: Mapped[TransactionType] = mapped_column(
        Enum(
            TransactionType,
            name="transaction_type",
            values_callable=lambda items: [x.value for x in items],
        )
    )
    name_ru: Mapped[str] = mapped_column(String(80))
    sort_order: Mapped[int] = mapped_column(SmallInteger)
    is_active: Mapped[bool] = mapped_column(default=True, server_default="true")


class CategoryCorrection(Base):
    __tablename__ = "category_corrections"
    __table_args__ = (
        UniqueConstraint(
            "owner",
            "transaction_type",
            "normalized_description",
            name="uq_category_corrections_owner_type_description",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("user_settings.telegram_user_id", ondelete="CASCADE")
    )
    transaction_type: Mapped[TransactionType] = mapped_column(
        Enum(
            TransactionType,
            name="transaction_type",
            values_callable=lambda items: [x.value for x in items],
        )
    )
    normalized_description: Mapped[str] = mapped_column(Text)
    category_code: Mapped[str] = mapped_column(String(64), ForeignKey("categories.code"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        CheckConstraint("amount_kopecks > 0", name="ck_transactions_amount_kopecks_positive"),
        CheckConstraint(
            "(type = 'saving' AND category_code IS NULL AND category_source IS NULL "
            "AND category_confidence IS NULL AND needs_category_review IS NULL) OR "
            "(type IN ('expense', 'income') AND category_code IS NOT NULL "
            "AND category_source IS NOT NULL AND category_confidence IS NOT NULL "
            "AND category_confidence BETWEEN 0 AND 100 "
            "AND needs_category_review IS NOT NULL)",
            name="ck_transactions_category_metadata_complete",
        ),
        ForeignKeyConstraint(
            ["category_code", "type"],
            ["categories.code", "categories.transaction_type"],
            name="fk_transactions_category_type",
        ),
        UniqueConstraint("source", "source_event_id", name="uq_transactions_source_event"),
        Index("ix_transactions_owner", "owner"),
        Index("ix_transactions_occurred_at", "occurred_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("user_settings.telegram_user_id", ondelete="CASCADE")
    )
    type: Mapped[TransactionType] = mapped_column(
        Enum(
            TransactionType,
            name="transaction_type",
            values_callable=lambda items: [x.value for x in items],
        )
    )
    direction: Mapped[TransactionDirection] = mapped_column(
        Enum(
            TransactionDirection,
            name="transaction_direction",
            values_callable=lambda items: [x.value for x in items],
        ),
        default=TransactionDirection.NORMAL,
        server_default=TransactionDirection.NORMAL.value,
    )
    amount_kopecks: Mapped[int] = mapped_column(BigInteger)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    description: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(64))
    source_event_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    category_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    category_source: Mapped[CategorySource | None] = mapped_column(
        Enum(
            CategorySource,
            name="category_source",
            values_callable=lambda items: [x.value for x in items],
        ),
        nullable=True,
    )
    category_confidence: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    needs_category_review: Mapped[bool | None] = mapped_column(nullable=True)
    category_name_ru: Mapped[str | None] = column_property(
        select(Category.name_ru).where(Category.code == category_code).scalar_subquery()
    )


class LoginToken(Base):
    __tablename__ = "login_tokens"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    owner: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("user_settings.telegram_user_id", ondelete="CASCADE")
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WebSession(Base):
    __tablename__ = "web_sessions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    owner: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("user_settings.telegram_user_id", ondelete="CASCADE")
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
