from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from moneyflow.categories.service import (
    CategoryService,
    InvalidCategoryError,
    TransactionNotFoundError,
)
from moneyflow.models import (
    Category,
    CategorySource,
    Transaction,
    TransactionDirection,
    TransactionType,
)
from moneyflow.transactions.schemas import TransactionResponse


class FakeSession:
    def __init__(self, *, commit_error: Exception | None = None) -> None:
        self.commit_error = commit_error
        self.commits = 0
        self.rollbacks = 0

    async def commit(self) -> None:
        self.commits += 1
        if self.commit_error is not None:
            raise self.commit_error

    async def rollback(self) -> None:
        self.rollbacks += 1


class ExpiringCategoryNameSession(FakeSession):
    def __init__(self, stored: Transaction) -> None:
        super().__init__()
        self._stored = stored

    async def commit(self) -> None:
        await super().commit()
        self._stored.__dict__.pop("category_name_ru", None)


class FakeCategoryRepository:
    def __init__(self, categories: list[Category] | None = None) -> None:
        self.categories = categories or []
        self.list_calls: list[TransactionType] = []
        self.find_calls: list[tuple[str, TransactionType | None]] = []

    async def list_active(self, transaction_type: TransactionType) -> list[Category]:
        self.list_calls.append(transaction_type)
        return [item for item in self.categories if item.transaction_type is transaction_type]

    async def find_active(
        self,
        code: str,
        transaction_type: TransactionType | None = None,
    ) -> Category | None:
        self.find_calls.append((code, transaction_type))
        return next(
            (
                item
                for item in self.categories
                if item.code == code
                and item.is_active
                and (transaction_type is None or item.transaction_type is transaction_type)
            ),
            None,
        )


class FakeCorrectionRepository:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.upserts: list[dict[str, Any]] = []

    async def upsert(self, **values: Any) -> None:
        self.upserts.append(values)
        if self.error is not None:
            raise self.error


class FakeTransactionRepository:
    def __init__(self, transaction: Transaction | None) -> None:
        self.transaction = transaction
        self.find_calls: list[tuple[UUID, int]] = []

    async def find_owned(self, transaction_id: UUID, owner: int) -> Transaction | None:
        self.find_calls.append((transaction_id, owner))
        return self.transaction


def category(
    code: str = "expense.groceries",
    transaction_type: TransactionType = TransactionType.EXPENSE,
    *,
    is_active: bool = True,
) -> Category:
    return Category(
        code=code,
        transaction_type=transaction_type,
        name_ru="Продукты",
        sort_order=1,
        is_active=is_active,
    )


def transaction(
    transaction_type: TransactionType = TransactionType.EXPENSE,
) -> Transaction:
    return Transaction(
        id=uuid4(),
        owner=71,
        type=transaction_type,
        direction=TransactionDirection.NORMAL,
        amount_kopecks=35_000,
        occurred_at=datetime(2026, 7, 18, tzinfo=UTC),
        description="  ВкусВилл, Ёлочная!  ",
        source="telegram",
        source_event_id="telegram:71",
        category_code=None if transaction_type is TransactionType.SAVING else "expense.other",
        category_source=(
            None if transaction_type is TransactionType.SAVING else CategorySource.FALLBACK
        ),
        category_confidence=None if transaction_type is TransactionType.SAVING else 0,
        needs_category_review=None if transaction_type is TransactionType.SAVING else True,
    )


def service(
    *,
    session: FakeSession | None = None,
    categories: list[Category] | None = None,
    stored_transaction: Transaction | None = None,
    correction_repository: FakeCorrectionRepository | None = None,
) -> tuple[
    CategoryService,
    FakeSession,
    FakeCategoryRepository,
    FakeCorrectionRepository,
    FakeTransactionRepository,
]:
    fake_session = session or FakeSession()
    category_repository = FakeCategoryRepository(categories)
    corrections = correction_repository or FakeCorrectionRepository()
    transactions = FakeTransactionRepository(stored_transaction)
    return (
        CategoryService(
            fake_session,
            71,
            category_repository=category_repository,
            correction_repository=corrections,
            transaction_repository=transactions,
        ),
        fake_session,
        category_repository,
        corrections,
        transactions,
    )


async def test_lists_active_categories_for_supported_transaction_type() -> None:
    expected = category()
    category_service, _, repository, _, _ = service(categories=[expected])

    assert await category_service.list_active(TransactionType.EXPENSE) == [expected]
    assert repository.list_calls == [TransactionType.EXPENSE]


async def test_rejects_saving_category_listing() -> None:
    category_service, _, repository, _, _ = service()

    with pytest.raises(InvalidCategoryError):
        await category_service.list_active(TransactionType.SAVING)
    assert repository.list_calls == []


async def test_filter_validation_accepts_only_active_category() -> None:
    active = category()
    category_service, _, repository, _, _ = service(categories=[active])

    await category_service.validate_filter_category(active.code)

    assert repository.find_calls == [(active.code, None)]


async def test_filter_validation_rejects_missing_or_inactive_category() -> None:
    inactive = category(is_active=False)
    category_service, _, _, _, _ = service(categories=[inactive])

    with pytest.raises(InvalidCategoryError):
        await category_service.validate_filter_category(inactive.code)


async def test_manual_update_is_owner_scoped_sets_exact_metadata_and_learns() -> None:
    stored = transaction()
    chosen = category()
    category_service, fake_session, categories, corrections, transactions = service(
        categories=[chosen],
        stored_transaction=stored,
    )

    updated = await category_service.update_transaction_category(stored.id, chosen.code)

    assert updated is stored
    assert transactions.find_calls == [(stored.id, 71)]
    assert categories.find_calls == [(chosen.code, TransactionType.EXPENSE)]
    assert stored.category_code == chosen.code
    assert stored.category_source is CategorySource.MANUAL
    assert stored.category_confidence == 100
    assert stored.needs_category_review is False
    assert corrections.upserts == [
        {
            "owner": 71,
            "transaction_type": TransactionType.EXPENSE,
            "normalized_description": "вкусвилл елочная",
            "category_code": chosen.code,
        }
    ]
    assert fake_session.commits == 1
    assert fake_session.rollbacks == 0


async def test_manual_update_serializes_new_category_name_after_commit_expiration() -> None:
    stored = transaction()
    stored.created_at = datetime(2026, 7, 18, tzinfo=UTC)
    stored.category_name_ru = "Прочее"
    chosen = category("expense.cafes")
    chosen.name_ru = "Кафе и рестораны"
    fake_session = ExpiringCategoryNameSession(stored)
    category_service, _, _, _, _ = service(
        session=fake_session,
        categories=[chosen],
        stored_transaction=stored,
    )

    updated = await category_service.update_transaction_category(stored.id, chosen.code)
    assert updated.__dict__["category_name_ru"] == "Кафе и рестораны"
    response = TransactionResponse.model_validate(updated)

    assert response.category_code == "expense.cafes"
    assert response.category_name_ru == "Кафе и рестораны"
    assert fake_session.commits == 1
    assert fake_session.rollbacks == 0


async def test_missing_or_foreign_transaction_has_one_not_found_result() -> None:
    transaction_id = uuid4()
    category_service, fake_session, _, corrections, transactions = service(
        categories=[category()],
    )

    with pytest.raises(TransactionNotFoundError):
        await category_service.update_transaction_category(
            transaction_id,
            "expense.groceries",
        )

    assert transactions.find_calls == [(transaction_id, 71)]
    assert corrections.upserts == []
    assert fake_session.commits == 0
    assert fake_session.rollbacks == 1


@pytest.mark.parametrize(
    "chosen",
    [
        category("income.salary", TransactionType.INCOME),
        category(is_active=False),
    ],
)
async def test_rejects_incompatible_or_inactive_category(chosen: Category) -> None:
    stored = transaction()
    category_service, fake_session, categories, corrections, _ = service(
        categories=[chosen],
        stored_transaction=stored,
    )

    with pytest.raises(InvalidCategoryError):
        await category_service.update_transaction_category(stored.id, chosen.code)

    assert categories.find_calls == [(chosen.code, TransactionType.EXPENSE)]
    assert corrections.upserts == []
    assert stored.category_code == "expense.other"
    assert fake_session.commits == 0
    assert fake_session.rollbacks == 1


async def test_saving_category_rejection_keeps_nullable_metadata_unchanged() -> None:
    stored = transaction(TransactionType.SAVING)
    category_service, fake_session, _, corrections, _ = service(
        categories=[category()],
        stored_transaction=stored,
    )

    with pytest.raises(InvalidCategoryError):
        await category_service.update_transaction_category(stored.id, "expense.groceries")

    assert (
        stored.category_code,
        stored.category_source,
        stored.category_confidence,
        stored.needs_category_review,
    ) == (None, None, None, None)
    assert corrections.upserts == []
    assert fake_session.rollbacks == 1


async def test_correction_failure_rolls_back_and_reraises() -> None:
    failure = RuntimeError("write failed")
    corrections = FakeCorrectionRepository(error=failure)
    stored = transaction()
    category_service, fake_session, _, _, _ = service(
        categories=[category()],
        stored_transaction=stored,
        correction_repository=corrections,
    )

    with pytest.raises(RuntimeError, match="write failed"):
        await category_service.update_transaction_category(stored.id, "expense.groceries")

    assert fake_session.commits == 0
    assert fake_session.rollbacks == 1


async def test_commit_failure_rolls_back_and_reraises() -> None:
    fake_session = FakeSession(commit_error=RuntimeError("commit failed"))
    stored = transaction()
    stored.category_name_ru = "Прочее"
    category_service, _, _, corrections, _ = service(
        session=fake_session,
        categories=[category()],
        stored_transaction=stored,
    )

    with pytest.raises(RuntimeError, match="commit failed"):
        await category_service.update_transaction_category(stored.id, "expense.groceries")

    assert len(corrections.upserts) == 1
    assert fake_session.commits == 1
    assert fake_session.rollbacks == 1
    assert stored.category_name_ru == "Прочее"
