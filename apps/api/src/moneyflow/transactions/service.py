from collections.abc import Coroutine
from datetime import UTC
from typing import Any, Protocol
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from moneyflow.models import Transaction
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

        transaction = Transaction(
            id=uuid4(),
            owner=self._telegram_user_id,
            type=command.transaction_type,
            direction=command.direction,
            amount_kopecks=command.amount_kopecks,
            occurred_at=occurred_at,
            description=description,
            source=command.source,
            source_event_id=command.source_event_id,
        )
        stored = await self._repository.add(transaction)
        await self._session.commit()
        return stored

    async def list_recent(self, limit: int = 100) -> list[Transaction]:
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        return await self._repository.list_recent(self._telegram_user_id, limit)
