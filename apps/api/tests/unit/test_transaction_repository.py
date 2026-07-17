from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from sqlalchemy.dialects import postgresql

from moneyflow.models import Transaction, TransactionDirection, TransactionType
from moneyflow.transactions.repository import TransactionRepository


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
