from dataclasses import MISSING, FrozenInstanceError, fields
from datetime import UTC, datetime
from typing import Any, get_type_hints

import pytest

from moneyflow.models import CategorySource, Transaction, TransactionDirection, TransactionType
from moneyflow.transactions.schemas import CreateTransactionCommand
from moneyflow.transactions.service import TransactionService


class FakeSession:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


class FakeTransactionRepository:
    async def add(self, transaction: Transaction) -> Transaction:
        transaction.created_at = datetime.now(UTC)
        return transaction

    async def list_recent(self, telegram_user_id: int, limit: int) -> list[Transaction]:
        return []


def command(**changes: Any) -> CreateTransactionCommand:
    values = {
        "transaction_type": TransactionType.EXPENSE,
        "direction": TransactionDirection.NORMAL,
        "amount_kopecks": 35_000,
        "occurred_at": datetime(2026, 7, 17, 12, tzinfo=UTC),
        "description": "Кофе",
        "source": "telegram",
        "source_event_id": "telegram:default",
    }
    values.update(changes)
    return CreateTransactionCommand(**values)


def service(session: FakeSession | None = None) -> TransactionService:
    return TransactionService(
        session or FakeSession(), 1, repository=FakeTransactionRepository()
    )


def test_create_transaction_command_matches_stable_contract() -> None:
    hints = get_type_hints(CreateTransactionCommand)
    command_fields = {field.name: field for field in fields(CreateTransactionCommand)}

    assert hints["occurred_at"] is datetime
    assert hints["source_event_id"] == str | None
    assert command_fields["occurred_at"].default is MISSING
    assert command_fields["source_event_id"].default is MISSING
    for name in (
        "category_code",
        "category_source",
        "category_confidence",
        "needs_category_review",
    ):
        assert command_fields[name].default is None
    with pytest.raises(TypeError, match="source_event_id"):
        CreateTransactionCommand(
            transaction_type=TransactionType.EXPENSE,
            direction=TransactionDirection.NORMAL,
            amount_kopecks=35_000,
            occurred_at=datetime(2026, 7, 17, 12, tzinfo=UTC),
            description="Кофе",
            source="telegram",
        )

    instance = command()
    with pytest.raises(FrozenInstanceError):
        instance.amount_kopecks = 1


async def test_create_without_category_uses_review_fallback() -> None:
    created = await service().create(command())
    assert created.category_code == "expense.other"
    assert created.category_source is CategorySource.FALLBACK
    assert created.category_confidence == 0
    assert created.needs_category_review is True


async def test_create_saving_without_category_keeps_metadata_empty() -> None:
    created = await service().create(command(transaction_type=TransactionType.SAVING))
    assert created.category_code is None
    assert created.category_source is None
    assert created.category_confidence is None
    assert created.needs_category_review is None


async def test_zero_amount_is_rejected() -> None:
    with pytest.raises(ValueError, match="amount_kopecks must be positive"):
        await service().create(command(amount_kopecks=0))


async def test_description_must_not_be_blank() -> None:
    with pytest.raises(ValueError, match="description must not be empty"):
        await service().create(command(description="   "))


async def test_create_normalizes_naive_occurred_at_to_utc_and_commits_once() -> None:
    session = FakeSession()
    created = await service(session).create(
        command(occurred_at=datetime(2026, 7, 17, 12))
    )
    assert created.occurred_at == datetime(2026, 7, 17, 12, tzinfo=UTC)
    assert session.commits == 1


@pytest.mark.parametrize("limit", [0, 501])
async def test_list_limit_must_be_between_1_and_500(limit: int) -> None:
    with pytest.raises(ValueError, match="limit must be between 1 and 500"):
        await service().list_recent(limit=limit)
