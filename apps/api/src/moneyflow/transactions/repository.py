from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from moneyflow.models import Transaction


class TransactionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_by_source_event(
        self, source: str, source_event_id: str
    ) -> Transaction | None:
        rows = await self._session.scalars(
            select(Transaction).where(
                Transaction.source == source,
                Transaction.source_event_id == source_event_id,
            )
        )
        return rows.one_or_none()

    async def add(self, transaction: Transaction) -> Transaction:
        if transaction.source_event_id is None:
            self._session.add(transaction)
            await self._session.flush()
            await self._session.refresh(transaction)
            return transaction

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
            )
            .on_conflict_do_nothing(index_elements=["source", "source_event_id"])
            .returning(Transaction)
        )
        inserted = (await self._session.execute(statement)).scalar_one_or_none()
        if inserted is not None:
            return inserted

        winner = await self.find_by_source_event(
            transaction.source, transaction.source_event_id
        )
        if winner is None:
            raise RuntimeError("idempotent transaction insert did not produce a winner")
        return winner

    async def list_recent(self, telegram_user_id: int, limit: int) -> list[Transaction]:
        rows = await self._session.scalars(
            select(Transaction)
            .where(Transaction.owner == telegram_user_id)
            .order_by(Transaction.occurred_at.desc(), Transaction.created_at.desc())
            .limit(limit)
        )
        return list(rows)
