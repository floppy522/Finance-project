import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from moneyflow.db import get_session
from moneyflow.main import create_app
from moneyflow.models import Transaction, TransactionDirection, TransactionType, UserSettings
from moneyflow.transactions.schemas import CreateTransactionCommand
from moneyflow.transactions.service import TransactionService


@pytest_asyncio.fixture
async def session_factory(
    engine: AsyncEngine,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        await session.execute(delete(Transaction))
        await session.execute(delete(UserSettings))
        session.add(UserSettings(telegram_user_id=1))
        await session.commit()

    yield factory

    async with factory() as session:
        await session.execute(delete(Transaction))
        await session.execute(delete(UserSettings))
        await session.commit()


@pytest_asyncio.fixture
async def session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with session_factory() as transaction_session:
        yield transaction_session
        await transaction_session.rollback()


def command(
    *,
    amount_kopecks: int = 35_000,
    source_event_id: str | None = "telegram:default",
    occurred_at: datetime = datetime(2026, 7, 17, 12, tzinfo=UTC),
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


def service(session: AsyncSession) -> TransactionService:
    return TransactionService(session, 1)


async def test_create_stores_350_rubles_as_35000_kopecks(session: AsyncSession) -> None:
    created = await service(session).create(command(amount_kopecks=35_000))
    assert created.amount_kopecks == 35_000


async def test_same_telegram_event_is_idempotent(session: AsyncSession) -> None:
    first = await service(session).create(command(source_event_id="telegram:100"))
    second = await service(session).create(command(source_event_id="telegram:100"))
    assert second.id == first.id
    count = await session.scalar(select(func.count()).select_from(Transaction))
    assert count == 1


async def test_concurrent_delivery_is_idempotent(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as first_session, session_factory() as second_session:
        first, second = await asyncio.gather(
            service(first_session).create(
                command(source_event_id="telegram:concurrent")
            ),
            service(second_session).create(
                command(source_event_id="telegram:concurrent")
            ),
        )

    async with session_factory() as assertion_session:
        count = await assertion_session.scalar(
            select(func.count())
            .select_from(Transaction)
            .where(
                Transaction.source == "telegram",
                Transaction.source_event_id == "telegram:concurrent",
            )
        )

    assert first.id == second.id
    assert count == 1


async def test_recent_list_is_newest_first(session: AsyncSession) -> None:
    await service(session).create(
        command(source_event_id="telegram:100", occurred_at=datetime(2026, 7, 17, tzinfo=UTC))
    )
    await service(session).create(
        command(source_event_id="telegram:101", occurred_at=datetime(2026, 7, 18, tzinfo=UTC))
    )
    assert [row.source_event_id for row in await service(session).list_recent()] == [
        "telegram:101",
        "telegram:100",
    ]


async def test_create_returns_201(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    app = create_app()

    async def override_get_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as route_session:
            yield route_session

    app.dependency_overrides[get_session] = override_get_session
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
    async with session_factory() as assertion_session:
        assert await assertion_session.scalar(
            select(func.count()).select_from(Transaction)
        ) == 1


async def test_list_returns_an_array(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    app = create_app()

    async def override_get_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as route_session:
            yield route_session

    app.dependency_overrides[get_session] = override_get_session
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/transactions")

    assert response.status_code == 200
    assert isinstance(response.json(), list)
