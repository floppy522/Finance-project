from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from moneyflow.models import Transaction


@dataclass(frozen=True, slots=True)
class StoredTransaction:
    transaction: Transaction
    created: bool


class TransactionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_by_source_event(self, source: str, source_event_id: str) -> Transaction | None:
        rows = await self._session.scalars(
            select(Transaction).where(
                Transaction.source == source,
                Transaction.source_event_id == source_event_id,
            )
        )
        return rows.one_or_none()

    async def add(self, transaction: Transaction) -> Transaction:
        return (await self.add_with_status(transaction)).transaction

    async def add_with_status(self, transaction: Transaction) -> StoredTransaction:
        if transaction.source_event_id is None:
            self._session.add(transaction)
            await self._session.flush()
            await self._session.refresh(transaction)
            return StoredTransaction(transaction, created=True)

        statement = (
            insert(Transaction)
            .values(
                id=transaction.id,
                owner=transaction.owner,
                type=transaction.type,
                direction=transaction.direction,
                amount_kopecks=transaction.amount_kopecks,
                occurred_at=transaction.occurred_at,
                description=transaction.description,
                source=transaction.source,
                source_event_id=transaction.source_event_id,
                category_code=transaction.category_code,
                category_source=transaction.category_source,
                category_confidence=transaction.category_confidence,
                needs_category_review=transaction.needs_category_review,
            )
            .on_conflict_do_nothing(index_elements=["source", "source_event_id"])
            .returning(Transaction)
        )
        inserted = (await self._session.execute(statement)).scalar_one_or_none()
        if inserted is not None:
            return StoredTransaction(inserted, created=True)

        winner = await self.find_by_source_event(transaction.source, transaction.source_event_id)
        if winner is None:
            raise RuntimeError("idempotent transaction insert did not produce a winner")
        return StoredTransaction(winner, created=False)

    async def find_owned(self, transaction_id: UUID, owner: int) -> Transaction | None:
        rows = await self._session.scalars(
            select(Transaction).where(
                Transaction.id == transaction_id,
                Transaction.owner == owner,
            )
        )
        return rows.one_or_none()

    async def list_recent(
        self,
        telegram_user_id: int,
        limit: int,
        category_code: str | None = None,
        needs_category_review: bool | None = None,
    ) -> list[Transaction]:
        statement = select(Transaction).where(Transaction.owner == telegram_user_id)
        if category_code is not None:
            statement = statement.where(Transaction.category_code == category_code)
        if needs_category_review is not None:
            statement = statement.where(
                Transaction.needs_category_review.is_(needs_category_review)
            )
        rows = await self._session.scalars(
            statement.order_by(
                Transaction.occurred_at.desc(), Transaction.created_at.desc()
            ).limit(limit)
        )
        return list(rows)
