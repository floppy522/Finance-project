from collections.abc import AsyncIterator

import pytest_asyncio
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from moneyflow.categories.repository import CategoryCorrectionRepository
from moneyflow.models import CategoryCorrection, Transaction, TransactionType, UserSettings


OWNER = 101


@pytest_asyncio.fixture
async def session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as cleanup_session:
        await cleanup_session.execute(
            delete(CategoryCorrection).where(CategoryCorrection.owner == OWNER)
        )
        await cleanup_session.execute(delete(Transaction).where(Transaction.owner == OWNER))
        await cleanup_session.execute(delete(UserSettings))
        cleanup_session.add(UserSettings(telegram_user_id=OWNER))
        await cleanup_session.commit()

    async with factory() as test_session:
        yield test_session
        await test_session.rollback()

    async with factory() as cleanup_session:
        await cleanup_session.execute(
            delete(CategoryCorrection).where(CategoryCorrection.owner == OWNER)
        )
        await cleanup_session.execute(delete(Transaction).where(Transaction.owner == OWNER))
        await cleanup_session.execute(delete(UserSettings))
        await cleanup_session.commit()


async def test_upsert_replaces_same_owner_type_description_without_second_row(
    session: AsyncSession,
) -> None:
    repository = CategoryCorrectionRepository(session)
    await repository.upsert(
        owner=OWNER,
        transaction_type=TransactionType.EXPENSE,
        normalized_description="кофе",
        category_code="expense.cafes",
    )
    await session.commit()
    await repository.upsert(
        owner=OWNER,
        transaction_type=TransactionType.EXPENSE,
        normalized_description="кофе",
        category_code="expense.groceries",
    )
    await session.commit()

    rows = (
        await session.scalars(
            select(CategoryCorrection).where(
                CategoryCorrection.owner == OWNER,
                CategoryCorrection.transaction_type == TransactionType.EXPENSE,
                CategoryCorrection.normalized_description == "кофе",
            )
        )
    ).all()
    assert len(rows) == 1
    assert rows[0].category_code == "expense.groceries"


async def test_reads_never_cross_transaction_type(session: AsyncSession) -> None:
    repository = CategoryCorrectionRepository(session)
    await repository.upsert(
        owner=OWNER,
        transaction_type=TransactionType.EXPENSE,
        normalized_description="кофе",
        category_code="expense.cafes",
    )
    await repository.upsert(
        owner=OWNER,
        transaction_type=TransactionType.INCOME,
        normalized_description="зарплата",
        category_code="income.salary",
    )
    await session.commit()

    assert [
        item.normalized_description
        for item in await repository.list_for_type(OWNER, TransactionType.EXPENSE)
    ] == ["кофе"]
    count = await session.scalar(select(func.count()).select_from(CategoryCorrection))
    assert count == 2
