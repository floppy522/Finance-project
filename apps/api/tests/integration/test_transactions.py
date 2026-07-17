import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from moneyflow.main import create_app
from moneyflow.models import Transaction, TransactionDirection, TransactionType
from moneyflow.transactions.schemas import CreateTransactionCommand
from moneyflow.transactions.routes import get_transaction_service
from moneyflow.transactions.service import TransactionService


class FakeSession:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


class FakeTransactionRepository:
    def __init__(self) -> None:
        self.rows: list[Transaction] = []
        self._lock = asyncio.Lock()

    async def add(self, transaction: Transaction) -> Transaction:
        async with self._lock:
            if transaction.source_event_id is not None:
                for row in self.rows:
                    if (row.source, row.source_event_id) == (
                        transaction.source,
                        transaction.source_event_id,
                    ):
                        return row
            transaction.id = uuid4()
            transaction.created_at = datetime.now(UTC)
            self.rows.append(transaction)
            return transaction

    async def list_recent(self, telegram_user_id: int, limit: int) -> list[Transaction]:
        matching = [row for row in self.rows if row.owner == telegram_user_id]
        return sorted(matching, key=lambda row: row.occurred_at, reverse=True)[:limit]


def command(
    *,
    amount_kopecks: int = 35_000,
    source_event_id: str | None = "telegram:default",
    occurred_at: datetime = datetime(2026, 7, 17, 12),
    description: str = "Кофе",
) -> CreateTransactionCommand:
    return CreateTransactionCommand(
        transaction_type=TransactionType.EXPENSE,
        direction=TransactionDirection.NORMAL,
        amount_kopecks=amount_kopecks,
        occurred_at=occurred_at,
        description=description,
        source="telegram",
        source_event_id=source_event_id,
    )


def service(
    session: FakeSession, repository: FakeTransactionRepository
) -> TransactionService:
    return TransactionService(session, 1, repository=repository)


async def test_create_stores_350_rubles_as_35000_kopecks() -> None:
    session = FakeSession()
    created = await service(session, FakeTransactionRepository()).create(
        command(amount_kopecks=35_000)
    )
    assert created.amount_kopecks == 35_000


async def test_zero_amount_is_rejected() -> None:
    with pytest.raises(ValueError, match="amount_kopecks must be positive"):
        await service(FakeSession(), FakeTransactionRepository()).create(
            command(amount_kopecks=0)
        )


async def test_same_telegram_event_is_idempotent() -> None:
    session = FakeSession()
    repository = FakeTransactionRepository()
    first = await service(session, repository).create(
        command(source_event_id="telegram:100")
    )
    second = await service(session, repository).create(
        command(source_event_id="telegram:100")
    )
    assert second.id == first.id


async def test_concurrent_delivery_is_idempotent() -> None:
    repository = FakeTransactionRepository()
    first, second = await asyncio.gather(
        service(FakeSession(), repository).create(
            command(source_event_id="telegram:concurrent")
        ),
        service(FakeSession(), repository).create(
            command(source_event_id="telegram:concurrent")
        ),
    )
    assert first.id == second.id


async def test_recent_list_is_newest_first() -> None:
    session = FakeSession()
    repository = FakeTransactionRepository()
    await service(session, repository).create(
        command(source_event_id="telegram:100", occurred_at=datetime(2026, 7, 17, 12))
    )
    await service(session, repository).create(
        command(source_event_id="telegram:101", occurred_at=datetime(2026, 7, 18, 12))
    )
    assert [row.source_event_id for row in await service(session, repository).list_recent()] == [
        "telegram:101",
        "telegram:100",
    ]


async def test_create_normalizes_occurred_at_to_utc_and_commits_once() -> None:
    session = FakeSession()
    created = await service(session, FakeTransactionRepository()).create(command())
    assert created.occurred_at == datetime(2026, 7, 17, 12, tzinfo=UTC)
    assert session.commits == 1


async def test_description_must_not_be_blank() -> None:
    with pytest.raises(ValueError, match="description must not be empty"):
        await service(FakeSession(), FakeTransactionRepository()).create(
            command(description="   ")
        )


@pytest.mark.parametrize("limit", [0, 501])
async def test_list_limit_must_be_between_1_and_500(limit: int) -> None:
    with pytest.raises(ValueError, match="limit must be between 1 and 500"):
        await service(FakeSession(), FakeTransactionRepository()).list_recent(limit=limit)


async def test_create_returns_201() -> None:
    app = create_app()
    app.dependency_overrides[get_transaction_service] = lambda: service(
        FakeSession(), FakeTransactionRepository()
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/transactions",
            json={
                "transaction_type": "expense",
                "direction": "normal",
                "amount_kopecks": 35_000,
                "occurred_at": "2026-07-17T12:00:00Z",
                "description": "Кофе",
            },
        )
    assert response.status_code == 201
    assert response.json()["amount_kopecks"] == 35_000


async def test_list_returns_an_array() -> None:
    app = create_app()
    app.dependency_overrides[get_transaction_service] = lambda: service(
        FakeSession(), FakeTransactionRepository()
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/transactions")
    assert isinstance(response.json(), list)
