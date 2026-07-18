from collections.abc import Coroutine, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from moneyflow.categories.schemas import CategoryDecision, CategoryInput
from moneyflow.models import Transaction
from moneyflow.telegram.batch_parser import BatchParseResult, RejectedInputLine
from moneyflow.transactions.repository import StoredTransaction, TransactionRepository
from moneyflow.transactions.schemas import CreateTransactionCommand
from moneyflow.transactions.service import TransactionService


@dataclass(frozen=True, slots=True)
class BatchIngestionResult:
    saved: tuple[Transaction, ...]
    duplicates: tuple[Transaction, ...]
    rejected: tuple[RejectedInputLine, ...]


class CategoryResolver(Protocol):
    async def resolve(self, items: Sequence[CategoryInput]) -> Mapping[str, CategoryDecision]: ...


class BatchTransactionRepository(Protocol):
    async def add_with_status(self, transaction: Transaction) -> StoredTransaction: ...


class Session(Protocol):
    def commit(self) -> Coroutine[Any, Any, None]: ...

    def rollback(self) -> Coroutine[Any, Any, None]: ...


class BatchIngestionService:
    def __init__(
        self,
        session: AsyncSession | Session,
        telegram_user_id: int,
        *,
        resolver: CategoryResolver,
        repository: BatchTransactionRepository | None = None,
    ) -> None:
        self._session = session
        self._resolver = resolver
        self._repository = (
            repository if repository is not None else TransactionRepository(session)  # type: ignore[arg-type]
        )
        self._transaction_service = TransactionService(session, telegram_user_id)

    async def ingest(self, parse_result: BatchParseResult) -> BatchIngestionResult:
        category_inputs = tuple(
            CategoryInput(
                item_id=str(item.line_number),
                description=item.description,
                transaction_type=item.transaction_type,
            )
            for item in parse_result.items
        )
        decisions = await self._resolver.resolve(category_inputs)

        transactions = tuple(
            self._transaction_service.build(
                CreateTransactionCommand(
                    transaction_type=item.transaction_type,
                    direction=item.direction,
                    amount_kopecks=item.amount_kopecks,
                    occurred_at=item.occurred_at,
                    description=item.description,
                    source="telegram",
                    source_event_id=item.source_event_id,
                    category_code=decisions[str(item.line_number)].category_code,
                    category_source=decisions[str(item.line_number)].source,
                    category_confidence=decisions[str(item.line_number)].confidence,
                    needs_category_review=decisions[str(item.line_number)].needs_review,
                )
            )
            for item in parse_result.items
        )

        if not transactions:
            return BatchIngestionResult((), (), parse_result.rejected)

        saved: list[Transaction] = []
        duplicates: list[Transaction] = []
        try:
            for transaction in transactions:
                stored = await self._repository.add_with_status(transaction)
                target = saved if stored.created else duplicates
                target.append(stored.transaction)
            await self._session.commit()
        except Exception:
            await self._session.rollback()
            raise

        return BatchIngestionResult(
            saved=tuple(saved),
            duplicates=tuple(duplicates),
            rejected=parse_result.rejected,
        )
