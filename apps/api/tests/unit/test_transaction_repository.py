from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from sqlalchemy.dialects import postgresql

from moneyflow.models import Transaction, TransactionDirection, TransactionType
from moneyflow.transactions.repository import StoredTransaction, TransactionRepository


async def test_idempotent_insert_compiles_for_postgresql() -> None:
    transaction = Transaction(
        id=uuid4(),
        owner=1,
        type=TransactionType.EXPENSE,
        direction=TransactionDirection.NORMAL,
        amount_kopecks=35_000,
        occurred_at=datetime(2026, 7, 17, 12, tzinfo=UTC),
        description="Кофе",
        source="telegram",
        source_event_id="telegram:compile",
    )
    session = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = transaction
    session.execute = AsyncMock(return_value=result)

    stored = await TransactionRepository(session).add(transaction)
    statement = session.execute.await_args.args[0]
    compiled = str(statement.compile(dialect=postgresql.dialect()))

    assert stored is transaction
    assert "ON CONFLICT (source, source_event_id) DO NOTHING" in compiled
    assert "RETURNING transactions.id" in compiled


async def test_status_aware_insert_marks_returned_row_as_created() -> None:
    transaction = Transaction(
        id=uuid4(),
        owner=1,
        type=TransactionType.EXPENSE,
        direction=TransactionDirection.NORMAL,
        amount_kopecks=35_000,
        occurred_at=datetime(2026, 7, 17, 12, tzinfo=UTC),
        description="Кофе",
        source="telegram",
        source_event_id="telegram:created",
    )
    session = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = transaction
    session.execute = AsyncMock(return_value=result)

    stored = await TransactionRepository(session).add_with_status(transaction)

    assert stored == StoredTransaction(transaction, created=True)


async def test_status_aware_insert_loads_and_marks_conflict_winner_as_duplicate() -> None:
    attempted = Transaction(
        id=uuid4(),
        owner=1,
        type=TransactionType.EXPENSE,
        direction=TransactionDirection.NORMAL,
        amount_kopecks=35_000,
        occurred_at=datetime(2026, 7, 17, 12, tzinfo=UTC),
        description="Кофе",
        source="telegram",
        source_event_id="telegram:duplicate",
    )
    winner = Transaction(
        id=uuid4(),
        owner=1,
        type=TransactionType.EXPENSE,
        direction=TransactionDirection.NORMAL,
        amount_kopecks=35_000,
        occurred_at=datetime(2026, 7, 17, 12, tzinfo=UTC),
        description="Existing coffee",
        source="telegram",
        source_event_id="telegram:duplicate",
    )
    session = MagicMock()
    insert_result = MagicMock()
    insert_result.scalar_one_or_none.return_value = None
    winner_rows = MagicMock()
    winner_rows.one_or_none.return_value = winner
    session.execute = AsyncMock(return_value=insert_result)
    session.scalars = AsyncMock(return_value=winner_rows)

    stored = await TransactionRepository(session).add_with_status(attempted)

    assert stored == StoredTransaction(winner, created=False)


async def test_legacy_add_returns_only_the_transaction() -> None:
    transaction = Transaction(
        id=uuid4(),
        owner=1,
        type=TransactionType.EXPENSE,
        direction=TransactionDirection.NORMAL,
        amount_kopecks=35_000,
        occurred_at=datetime(2026, 7, 17, 12, tzinfo=UTC),
        description="Кофе",
        source="telegram",
        source_event_id="telegram:legacy",
    )
    session = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = transaction
    session.execute = AsyncMock(return_value=result)

    stored = await TransactionRepository(session).add(transaction)

    assert stored is transaction
