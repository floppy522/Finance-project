from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import uuid4

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from moneyflow.auth.routes import get_current_user_id
from moneyflow.db import get_session
from moneyflow.main import create_app
from moneyflow.models import (
    Category,
    CategoryCorrection,
    CategorySource,
    Transaction,
    TransactionDirection,
    TransactionType,
    UserSettings,
)
from moneyflow.transactions.schemas import CreateTransactionCommand
from moneyflow.transactions.service import TransactionService


OWNER = 701
OTHER_OWNER = 702
INACTIVE_TEST_CATEGORY = "expense.education"


@pytest_asyncio.fixture
async def session_factory(
    engine: AsyncEngine,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        await session.execute(delete(CategoryCorrection).where(CategoryCorrection.owner == OWNER))
        await session.execute(delete(Transaction).where(Transaction.owner == OWNER))
        await session.execute(delete(UserSettings))
        await session.execute(
            update(Category).where(Category.code == INACTIVE_TEST_CATEGORY).values(is_active=True)
        )
        session.add(UserSettings(telegram_user_id=OWNER))
        await session.commit()

    yield factory

    async with factory() as session:
        await session.execute(delete(CategoryCorrection).where(CategoryCorrection.owner == OWNER))
        await session.execute(delete(Transaction).where(Transaction.owner == OWNER))
        await session.execute(delete(UserSettings))
        await session.execute(
            update(Category).where(Category.code == INACTIVE_TEST_CATEGORY).values(is_active=True)
        )
        await session.commit()


@pytest_asyncio.fixture
async def client(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncClient]:
    app = create_app()

    async def override_get_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as route_session:
            yield route_session

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_current_user_id] = lambda: OWNER
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as test_client:
        yield test_client


async def create_transaction(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    owner: int = OWNER,
    description: str = "Кофе",
    transaction_type: TransactionType = TransactionType.EXPENSE,
    category_code: str | None = None,
    needs_category_review: bool | None = None,
) -> Transaction:
    async with session_factory() as session:
        return await TransactionService(session, owner).create(
            CreateTransactionCommand(
                transaction_type=transaction_type,
                direction=TransactionDirection.NORMAL,
                amount_kopecks=35_000,
                occurred_at=datetime(2026, 7, 18, tzinfo=UTC),
                description=description,
                source="test",
                source_event_id=f"test:{uuid4()}",
                category_code=category_code,
                category_source=(CategorySource.RULES if category_code else None),
                category_confidence=95 if category_code else None,
                needs_category_review=needs_category_review,
            )
        )


async def test_lists_active_expense_categories_in_sort_order(
    client: AsyncClient,
) -> None:
    response = await client.get("/api/categories?transaction_type=expense")

    assert response.status_code == 200
    payload = response.json()
    assert payload[0] == {
        "code": "expense.groceries",
        "transaction_type": "expense",
        "name_ru": "Продукты",
    }
    assert [item["code"] for item in payload][-1] == "expense.other"


async def test_inactive_category_is_excluded_from_catalog(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await session.execute(
            update(Category).where(Category.code == INACTIVE_TEST_CATEGORY).values(is_active=False)
        )
        await session.commit()

    response = await client.get("/api/categories?transaction_type=expense")

    assert response.status_code == 200
    assert INACTIVE_TEST_CATEGORY not in {item["code"] for item in response.json()}


async def test_manual_patch_updates_transaction_and_upserts_normalized_correction(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    transaction = await create_transaction(
        session_factory,
        description="  ВкусВилл, Ёлочная!  ",
    )

    first = await client.patch(
        f"/api/transactions/{transaction.id}/category",
        json={"category_code": "expense.groceries"},
    )
    second = await client.patch(
        f"/api/transactions/{transaction.id}/category",
        json={"category_code": "expense.cafes"},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["category_source"] == "manual"
    assert second.json()["category_confidence"] == 100
    assert second.json()["needs_category_review"] is False
    async with session_factory() as session:
        rows = (
            await session.scalars(
                select(CategoryCorrection).where(
                    CategoryCorrection.owner == OWNER,
                    CategoryCorrection.transaction_type == TransactionType.EXPENSE,
                    CategoryCorrection.normalized_description == "вкусвилл елочная",
                )
            )
        ).all()
    assert len(rows) == 1
    assert rows[0].category_code == "expense.cafes"


async def test_missing_transaction_returns_404(
    client: AsyncClient,
) -> None:
    missing_response = await client.patch(
        f"/api/transactions/{uuid4()}/category",
        json={"category_code": "expense.groceries"},
    )

    assert missing_response.status_code == 404


async def test_incompatible_and_inactive_categories_are_rejected_without_update(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    transaction = await create_transaction(session_factory)
    async with session_factory() as session:
        await session.execute(
            update(Category).where(Category.code == INACTIVE_TEST_CATEGORY).values(is_active=False)
        )
        await session.commit()

    incompatible = await client.patch(
        f"/api/transactions/{transaction.id}/category",
        json={"category_code": "income.salary"},
    )
    inactive = await client.patch(
        f"/api/transactions/{transaction.id}/category",
        json={"category_code": INACTIVE_TEST_CATEGORY},
    )

    assert incompatible.status_code == inactive.status_code == 422
    async with session_factory() as session:
        stored = await session.get(Transaction, transaction.id)
        correction_count = await session.scalar(
            select(func.count())
            .select_from(CategoryCorrection)
            .where(CategoryCorrection.owner == OWNER)
        )
    assert stored is not None
    assert stored.category_code == "expense.other"
    assert correction_count == 0


async def test_filters_are_composable_and_keep_limit(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    matching = await create_transaction(
        session_factory,
        description="Продукты",
        category_code="expense.groceries",
        needs_category_review=False,
    )
    await create_transaction(session_factory, description="Неизвестно")
    response = await client.get(
        "/api/transactions",
        params={
            "limit": 1,
            "category_code": "expense.groceries",
            "needs_category_review": "false",
        },
    )

    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [str(matching.id)]


async def test_invalid_or_inactive_filter_is_rejected(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await session.execute(
            update(Category).where(Category.code == INACTIVE_TEST_CATEGORY).values(is_active=False)
        )
        await session.commit()

    missing = await client.get("/api/transactions?category_code=expense.missing")
    inactive = await client.get(
        "/api/transactions",
        params={"category_code": INACTIVE_TEST_CATEGORY},
    )

    assert missing.status_code == inactive.status_code == 422


async def test_saving_rows_keep_nullable_category_fields_in_list(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    saving = await create_transaction(
        session_factory,
        transaction_type=TransactionType.SAVING,
        description="Резерв",
    )

    response = await client.get("/api/transactions")

    assert response.status_code == 200
    payload = next(item for item in response.json() if item["id"] == str(saving.id))
    assert payload["category_code"] is None
    assert payload["category_source"] is None
    assert payload["category_confidence"] is None
    assert payload["needs_category_review"] is None


async def test_manual_patch_rejects_unknown_fields(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    transaction = await create_transaction(session_factory)

    response = await client.patch(
        f"/api/transactions/{transaction.id}/category",
        json={"category_code": "expense.groceries", "owner": OTHER_OWNER},
    )

    assert response.status_code == 422
