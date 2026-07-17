import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TransactionType(enum.StrEnum):
    EXPENSE = "expense"
    INCOME = "income"
    SAVING = "saving"


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


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        CheckConstraint("amount_kopecks > 0", name="ck_transactions_amount_kopecks_positive"),
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
