from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from typing import Any

import pytest

from moneyflow.categories.schemas import CategoryDecision, CategoryInput
from moneyflow.models import (
    CategorySource,
    Transaction,
    TransactionDirection,
    TransactionType,
)
from moneyflow.telegram.batch_parser import (
    BatchParseResult,
    ParsedTransactionLine,
    RejectedInputLine,
)
from moneyflow.telegram.ingestion import BatchIngestionResult, BatchIngestionService
from moneyflow.transactions.repository import StoredTransaction


class FakeSession:
    def __init__(self, *, commit_error: Exception | None = None) -> None:
        self.commit_attempts = 0
        self.commits = 0
        self.rollbacks = 0
        self._commit_error = commit_error

    async def commit(self) -> None:
        self.commit_attempts += 1
        if self._commit_error is not None:
            raise self._commit_error
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


class RecordingResolver:
    def __init__(self, decisions: dict[str, CategoryDecision]) -> None:
        self.decisions = decisions
        self.calls: list[tuple[CategoryInput, ...]] = []

    async def resolve(self, items: tuple[CategoryInput, ...]) -> dict[str, CategoryDecision]:
        self.calls.append(items)
        return self.decisions


class FakeRepository:
    def __init__(
        self,
        *,
        existing: dict[str, Transaction] | None = None,
        fail_on_call: int | None = None,
    ) -> None:
        self.existing = dict(existing or {})
        self.fail_on_call = fail_on_call
        self.calls: list[Transaction] = []

    async def add_with_status(self, transaction: Transaction) -> StoredTransaction:
        self.calls.append(transaction)
        if len(self.calls) == self.fail_on_call:
            raise RuntimeError("persistence failed")
        assert transaction.source_event_id is not None
        existing = self.existing.get(transaction.source_event_id)
        if existing is not None:
            return StoredTransaction(existing, created=False)
        self.existing[transaction.source_event_id] = transaction
        return StoredTransaction(transaction, created=True)


def line(
    line_number: int,
    description: str,
    *,
    transaction_type: TransactionType = TransactionType.EXPENSE,
) -> ParsedTransactionLine:
    return ParsedTransactionLine(
        line_number=line_number,
        description=description,
        amount_kopecks=35_000 * line_number,
        occurred_at=datetime(2026, 7, 18, 9, 30, tzinfo=UTC),
        transaction_type=transaction_type,
        direction=TransactionDirection.NORMAL,
        source_event_id=f"telegram:42:{line_number}",
    )


def decision(
    code: str,
    source: CategorySource = CategorySource.RULES,
    confidence: int = 95,
    needs_review: bool = False,
) -> CategoryDecision:
    return CategoryDecision(code, source, confidence, needs_review)


def existing_transaction(item: ParsedTransactionLine) -> Transaction:
    category_code = (
        "income.salary" if item.transaction_type is TransactionType.INCOME else "expense.cafes"
    )
    return Transaction(
        owner=1,
        type=item.transaction_type,
        direction=item.direction,
        amount_kopecks=item.amount_kopecks,
        occurred_at=item.occurred_at,
        description=f"existing {item.description}",
        source="telegram",
        source_event_id=item.source_event_id,
        category_code=category_code,
        category_source=CategorySource.RULES,
        category_confidence=95,
        needs_category_review=False,
    )


def service(
    session: FakeSession,
    resolver: RecordingResolver,
    repository: FakeRepository,
) -> BatchIngestionService:
    return BatchIngestionService(
        session,
        telegram_user_id=1,
        resolver=resolver,
        repository=repository,
    )


async def test_valid_lines_resolve_once_commit_once_and_preserve_rejections() -> None:
    coffee = line(2, "кофе")
    salary = line(3, "зарплата", transaction_type=TransactionType.INCOME)
    rejected = RejectedInputLine(4, "непонятно", "укажите сумму")
    resolver = RecordingResolver(
        {
            "2": decision("expense.cafes"),
            "3": decision("income.salary", CategorySource.AI, 83, True),
        }
    )
    session = FakeSession()
    repository = FakeRepository()

    result = await service(session, resolver, repository).ingest(
        BatchParseResult(items=(coffee, salary), rejected=(rejected,))
    )

    assert resolver.calls == [
        (
            CategoryInput("2", "кофе", TransactionType.EXPENSE),
            CategoryInput("3", "зарплата", TransactionType.INCOME),
        )
    ]
    assert [row.description for row in result.saved] == ["кофе", "зарплата"]
    assert result.duplicates == ()
    assert result.rejected == (rejected,)
    assert session.commits == 1
    assert session.commit_attempts == 1
    assert session.rollbacks == 0

    stored_salary = repository.calls[1]
    assert stored_salary.category_code == "income.salary"
    assert stored_salary.category_source is CategorySource.AI
    assert stored_salary.category_confidence == 83
    assert stored_salary.needs_category_review is True


async def test_duplicate_status_and_order_are_reported_with_one_batch_commit() -> None:
    first = line(2, "кофе")
    second = line(3, "зарплата", transaction_type=TransactionType.INCOME)
    third = line(4, "такси")
    existing_first = existing_transaction(first)
    existing_third = existing_transaction(third)
    repository = FakeRepository(
        existing={
            first.source_event_id: existing_first,
            third.source_event_id: existing_third,
        }
    )
    resolver = RecordingResolver(
        {
            "2": decision("expense.cafes"),
            "3": decision("income.salary"),
            "4": decision("expense.transport"),
        }
    )
    session = FakeSession()

    result = await service(session, resolver, repository).ingest(
        BatchParseResult(items=(first, second, third), rejected=())
    )

    assert [row.source_event_id for row in result.saved] == [second.source_event_id]
    assert result.duplicates == (existing_first, existing_third)
    assert [row.source_event_id for row in repository.calls] == [
        first.source_event_id,
        second.source_event_id,
        third.source_event_id,
    ]
    assert session.commit_attempts == 1
    assert session.commits == 1


async def test_all_duplicates_still_use_exactly_one_commit() -> None:
    coffee = line(2, "кофе")
    salary = line(3, "зарплата", transaction_type=TransactionType.INCOME)
    repository = FakeRepository(
        existing={
            coffee.source_event_id: existing_transaction(coffee),
            salary.source_event_id: existing_transaction(salary),
        }
    )
    resolver = RecordingResolver({"2": decision("expense.cafes"), "3": decision("income.salary")})
    session = FakeSession()

    result = await service(session, resolver, repository).ingest(
        BatchParseResult(items=(coffee, salary), rejected=())
    )

    assert result.saved == ()
    assert [row.source_event_id for row in result.duplicates] == [
        coffee.source_event_id,
        salary.source_event_id,
    ]
    assert session.commit_attempts == 1
    assert session.commits == 1


async def test_persistence_error_rolls_back_and_reraises_without_commit() -> None:
    coffee = line(2, "кофе")
    salary = line(3, "зарплата", transaction_type=TransactionType.INCOME)
    resolver = RecordingResolver({"2": decision("expense.cafes"), "3": decision("income.salary")})
    session = FakeSession()
    repository = FakeRepository(fail_on_call=2)

    with pytest.raises(RuntimeError, match="persistence failed"):
        await service(session, resolver, repository).ingest(
            BatchParseResult(items=(coffee, salary), rejected=())
        )

    assert session.commit_attempts == 0
    assert session.commits == 0
    assert session.rollbacks == 1


async def test_commit_error_rolls_back_and_reraises_without_second_commit() -> None:
    coffee = line(2, "кофе")
    resolver = RecordingResolver({"2": decision("expense.cafes")})
    session = FakeSession(commit_error=RuntimeError("commit failed"))

    with pytest.raises(RuntimeError, match="commit failed"):
        await service(session, resolver, FakeRepository()).ingest(
            BatchParseResult(items=(coffee,), rejected=())
        )

    assert session.commit_attempts == 1
    assert session.commits == 0
    assert session.rollbacks == 1


async def test_empty_batch_resolves_once_without_persistence_or_transaction_boundary() -> None:
    rejected = RejectedInputLine(1, "?", "укажите сумму")
    resolver = RecordingResolver({})
    session = FakeSession()
    repository = FakeRepository()

    result = await service(session, resolver, repository).ingest(
        BatchParseResult(items=(), rejected=(rejected,))
    )

    assert result == BatchIngestionResult(saved=(), duplicates=(), rejected=(rejected,))
    assert resolver.calls == [()]
    assert repository.calls == []
    assert session.commit_attempts == 0
    assert session.rollbacks == 0


def test_result_is_frozen_and_uses_immutable_tuples() -> None:
    result = BatchIngestionResult(saved=(), duplicates=(), rejected=())
    assert isinstance(result.saved, tuple)
    assert isinstance(result.duplicates, tuple)
    assert isinstance(result.rejected, tuple)
    with pytest.raises(FrozenInstanceError):
        result.saved = (Any,)  # type: ignore[misc]
