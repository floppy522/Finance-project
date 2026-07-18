from collections.abc import Coroutine
from datetime import UTC
from typing import Any, Protocol
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from moneyflow.models import CategorySource, Transaction, TransactionType
from moneyflow.transactions.repository import TransactionRepository
from moneyflow.transactions.schemas import CreateTransactionCommand


class Repository(Protocol):
    async def add(self, transaction: Transaction) -> Transaction: ...

    async def list_recent(self, telegram_user_id: int, limit: int) -> list[Transaction]: ...


class Session(Protocol):
    def commit(self) -> Coroutine[Any, Any, None]: ...


class TransactionService:
    def __init__(
        self,
        session: AsyncSession | Session,
        telegram_user_id: int,
        *,
        repository: Repository | None = None,
    ) -> None:
        self._session = session
        self._telegram_user_id = telegram_user_id
        self._repository = repository or TransactionRepository(session)  # type: ignore[arg-type]

    async def create(self, command: CreateTransactionCommand) -> Transaction:
        transaction = self.build(command)
        stored = await self._repository.add(transaction)
        await self._session.commit()
        return stored

    def build(self, command: CreateTransactionCommand) -> Transaction:
        if command.amount_kopecks <= 0:
            raise ValueError("amount_kopecks must be positive")
        description = command.description.strip()
        if not description:
            raise ValueError("description must not be empty")

        occurred_at = command.occurred_at
        if occurred_at.tzinfo is None:
            occurred_at = occurred_at.replace(tzinfo=UTC)
        else:
            occurred_at = occurred_at.astimezone(UTC)

        category_code = None
        category_source = None
        category_confidence = None
        needs_review = None
        if command.transaction_type in {TransactionType.EXPENSE, TransactionType.INCOME}:
            category_code = command.category_code or f"{command.transaction_type.value}.other"
            category_source = command.category_source or CategorySource.FALLBACK
            category_confidence = (
                command.category_confidence if command.category_confidence is not None else 0
            )
            needs_review = (
                command.needs_category_review if command.needs_category_review is not None else True
            )

        return Transaction(
            id=uuid4(),
            owner=self._telegram_user_id,
            type=command.transaction_type,
            direction=command.direction,
            amount_kopecks=command.amount_kopecks,
            occurred_at=occurred_at,
            description=description,
            source=command.source,
            source_event_id=command.source_event_id,
            category_code=category_code,
            category_source=category_source,
            category_confidence=category_confidence,
            needs_category_review=needs_review,
        )

    async def list_recent(self, limit: int = 100) -> list[Transaction]:
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        return await self._repository.list_recent(self._telegram_user_id, limit)
