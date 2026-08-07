from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from moneyflow.categories.schemas import CategoryDecision, CategoryInput
from moneyflow.models import (
    CategorySource,
    Transaction,
    TransactionDirection,
    TransactionType,
    UserSettings,
)
from moneyflow.telegram.batch_parser import BatchParseResult, ParsedTransactionLine
from moneyflow.telegram.ingestion import BatchIngestionService


OWNER = 50505


class RecordingResolver:
    def __init__(self, decisions: dict[str, CategoryDecision]) -> None:
        self.decisions = decisions
        self.calls: list[tuple[CategoryInput, ...]] = []

    async def resolve(self, items: tuple[CategoryInput, ...]) -> dict[str, CategoryDecision]:
        self.calls.append(items)
        return self.decisions


@pytest_asyncio.fixture
async def session_factory(
    engine: AsyncEngine,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as cleanup_session:
        await cleanup_session.execute(delete(Transaction).where(Transaction.owner == OWNER))
        await cleanup_session.execute(
            delete(UserSettings).where(UserSettings.telegram_user_id == OWNER)
        )
        cleanup_session.add(UserSettings(telegram_user_id=OWNER))
        await cleanup_session.commit()

    yield factory

    async with factory() as cleanup_session:
        await cleanup_session.execute(delete(Transaction).where(Transaction.owner == OWNER))
        await cleanup_session.execute(
            delete(UserSettings).where(UserSettings.telegram_user_id == OWNER)
        )
        await cleanup_session.commit()


def parsed_line(
    line_number: int,
    description: str,
    transaction_type: TransactionType,
) -> ParsedTransactionLine:
    return ParsedTransactionLine(
        line_number=line_number,
        description=description,
        amount_kopecks=line_number * 10_000,
        occurred_at=datetime(2026, 7, 18, 12, tzinfo=UTC),
        transaction_type=transaction_type,
        direction=TransactionDirection.NORMAL,
        source_event_id=f"telegram:42:{line_number}",
    )


async def test_redelivery_reports_duplicates_and_keeps_exactly_two_database_rows(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    coffee = parsed_line(2, "кофе", TransactionType.EXPENSE)
    salary = parsed_line(3, "зарплата", TransactionType.INCOME)
    parsed = BatchParseResult(items=(coffee, salary), rejected=())
    resolver = RecordingResolver(
        {
            "2": CategoryDecision("expense.cafes", CategorySource.RULES, 95, False),
            "3": CategoryDecision("income.salary", CategorySource.RULES, 95, False),
        }
    )

    async with session_factory() as session:
        service = BatchIngestionService(session, OWNER, resolver=resolver)
        first = await service.ingest(parsed)
        second = await service.ingest(parsed)

    async with session_factory() as assertion_session:
        rows = list(
            (
                await assertion_session.scalars(
                    select(Transaction)
                    .where(Transaction.owner == OWNER)
                    .order_by(Transaction.source_event_id)
                )
            ).all()
        )

    assert [row.source_event_id for row in first.saved] == [
        "telegram:42:2",
        "telegram:42:3",
    ]
    assert first.duplicates == ()
    assert second.saved == ()
    assert [row.source_event_id for row in second.duplicates] == [
        "telegram:42:2",
        "telegram:42:3",
    ]
    assert [row.source_event_id for row in rows] == ["telegram:42:2", "telegram:42:3"]
    assert len(resolver.calls) == 2


async def test_database_error_rolls_back_all_valid_rows(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    coffee = parsed_line(2, "кофе", TransactionType.EXPENSE)
    salary = parsed_line(3, "зарплата", TransactionType.INCOME)
    resolver = RecordingResolver(
        {
            "2": CategoryDecision("expense.cafes", CategorySource.RULES, 95, False),
            "3": CategoryDecision("expense.cafes", CategorySource.RULES, 95, False),
        }
    )

    async with session_factory() as session:
        with pytest.raises(IntegrityError):
            await BatchIngestionService(session, OWNER, resolver=resolver).ingest(
                BatchParseResult(items=(coffee, salary), rejected=())
            )

    async with session_factory() as assertion_session:
        count = await assertion_session.scalar(
            select(func.count()).select_from(Transaction).where(Transaction.owner == OWNER)
        )
    assert count == 0
