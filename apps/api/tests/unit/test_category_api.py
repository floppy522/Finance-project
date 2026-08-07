from datetime import UTC, datetime
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from moneyflow.categories import schemas as category_schemas
from moneyflow.categories.routes import get_category_service
from moneyflow.categories.service import InvalidCategoryError, TransactionNotFoundError
from moneyflow.main import create_app
from moneyflow.models import (
    Category,
    Transaction,
    TransactionDirection,
    TransactionType,
)
from moneyflow.transactions import schemas as transaction_schemas
from moneyflow.transactions.routes import get_transaction_service


class FakeCategoryService:
    def __init__(
        self,
        *,
        categories: list[Category] | None = None,
        updated: Transaction | None = None,
        error: Exception | None = None,
    ) -> None:
        self.categories = categories or []
        self.updated = updated
        self.error = error
        self.list_calls: list[TransactionType] = []
        self.filter_calls: list[str] = []
        self.update_calls: list[tuple[object, str]] = []

    async def list_active(self, transaction_type: TransactionType) -> list[Category]:
        self.list_calls.append(transaction_type)
        if self.error is not None:
            raise self.error
        return self.categories

    async def validate_filter_category(self, category_code: str) -> None:
        self.filter_calls.append(category_code)
        if self.error is not None:
            raise self.error

    async def update_transaction_category(
        self,
        transaction_id: object,
        category_code: str,
    ) -> Transaction:
        self.update_calls.append((transaction_id, category_code))
        if self.error is not None:
            raise self.error
        assert self.updated is not None
        return self.updated


class FakeTransactionService:
    def __init__(self) -> None:
        self.list_calls: list[tuple[int, str | None, bool | None]] = []

    async def list_recent(
        self,
        limit: int = 100,
        category_code: str | None = None,
        needs_category_review: bool | None = None,
    ) -> list[Transaction]:
        self.list_calls.append((limit, category_code, needs_category_review))
        return []


def test_category_api_dto_contract_is_available() -> None:
    assert category_schemas.CategoryResponse
    assert transaction_schemas.UpdateTransactionCategoryRequest


def test_category_response_exposes_only_public_catalog_fields() -> None:
    response = category_schemas.CategoryResponse.model_validate(
        Category(
            code="expense.groceries",
            transaction_type=TransactionType.EXPENSE,
            name_ru="Продукты",
            sort_order=1,
            is_active=True,
        )
    )

    assert response.model_dump(mode="json") == {
        "code": "expense.groceries",
        "transaction_type": "expense",
        "name_ru": "Продукты",
    }


def test_category_update_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        transaction_schemas.UpdateTransactionCategoryRequest.model_validate(
            {
                "category_code": "expense.groceries",
                "owner": 999,
                "category_confidence": 7,
            }
        )


def test_transaction_response_preserves_nullable_saving_category_metadata() -> None:
    saving = Transaction(
        id=uuid4(),
        owner=71,
        type=TransactionType.SAVING,
        direction=TransactionDirection.NORMAL,
        amount_kopecks=100_000,
        occurred_at=datetime(2026, 7, 18, tzinfo=UTC),
        created_at=datetime(2026, 7, 18, tzinfo=UTC),
        description="Накопления",
        source="web",
        source_event_id=None,
        category_code=None,
        category_source=None,
        category_confidence=None,
        needs_category_review=None,
    )

    response = transaction_schemas.TransactionResponse.model_validate(saving)

    assert (
        response.category_code,
        response.category_source,
        response.category_confidence,
        response.needs_category_review,
    ) == (None, None, None, None)


def test_transaction_response_exposes_server_derived_historical_category_name() -> None:
    transaction = Transaction(
        id=uuid4(),
        owner=71,
        type=TransactionType.EXPENSE,
        direction=TransactionDirection.NORMAL,
        amount_kopecks=100_000,
        occurred_at=datetime(2026, 7, 18, tzinfo=UTC),
        created_at=datetime(2026, 7, 18, tzinfo=UTC),
        description="Архивная покупка",
        source="web",
        source_event_id=None,
        category_code="expense.archived",
        category_source="manual",
        category_confidence=100,
        needs_category_review=False,
    )
    transaction.category_name_ru = "Архивная категория"

    response = transaction_schemas.TransactionResponse.model_validate(transaction)

    assert response.category_code == "expense.archived"
    assert response.category_name_ru == "Архивная категория"


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/api/categories?transaction_type=expense"),
        ("PATCH", f"/api/transactions/{uuid4()}/category"),
    ],
)
async def test_category_review_endpoints_require_session_authentication(
    method: str,
    path: str,
) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=create_app()),
        base_url="http://test",
    ) as client:
        response = await client.request(
            method,
            path,
            json={"category_code": "expense.groceries"} if method == "PATCH" else None,
        )

    assert response.status_code == 401


async def test_lists_categories_using_requested_type_and_public_shape() -> None:
    fake = FakeCategoryService(
        categories=[
            Category(
                code="expense.groceries",
                transaction_type=TransactionType.EXPENSE,
                name_ru="Продукты",
                sort_order=1,
                is_active=True,
            )
        ]
    )
    app = create_app()
    app.dependency_overrides[get_category_service] = lambda: fake

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/api/categories?transaction_type=expense")

    assert response.status_code == 200
    assert response.json() == [
        {
            "code": "expense.groceries",
            "transaction_type": "expense",
            "name_ru": "Продукты",
        }
    ]
    assert fake.list_calls == [TransactionType.EXPENSE]


async def test_rejects_unsupported_category_catalog_type() -> None:
    fake = FakeCategoryService(error=InvalidCategoryError("invalid category"))
    app = create_app()
    app.dependency_overrides[get_category_service] = lambda: fake

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/api/categories?transaction_type=saving")

    assert response.status_code == 422


async def test_transaction_filters_are_validated_and_preserve_limit() -> None:
    categories = FakeCategoryService()
    transactions = FakeTransactionService()
    app = create_app()
    app.dependency_overrides[get_category_service] = lambda: categories
    app.dependency_overrides[get_transaction_service] = lambda: transactions

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get(
            "/api/transactions",
            params={
                "limit": "37",
                "category_code": "expense.groceries",
                "needs_category_review": "false",
            },
        )

    assert response.status_code == 200
    assert response.json() == []
    assert categories.filter_calls == ["expense.groceries"]
    assert transactions.list_calls == [(37, "expense.groceries", False)]


async def test_invalid_category_filter_is_422_without_transaction_query() -> None:
    categories = FakeCategoryService(error=InvalidCategoryError("invalid category"))
    transactions = FakeTransactionService()
    app = create_app()
    app.dependency_overrides[get_category_service] = lambda: categories
    app.dependency_overrides[get_transaction_service] = lambda: transactions

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get(
            "/api/transactions?category_code=missing&needs_category_review=true"
        )

    assert response.status_code == 422
    assert transactions.list_calls == []


def updated_transaction() -> Transaction:
    return Transaction(
        id=uuid4(),
        owner=71,
        type=TransactionType.EXPENSE,
        direction=TransactionDirection.NORMAL,
        amount_kopecks=35_000,
        occurred_at=datetime(2026, 7, 18, tzinfo=UTC),
        created_at=datetime(2026, 7, 18, tzinfo=UTC),
        description="Кофе",
        source="telegram",
        source_event_id="telegram:71",
        category_code="expense.groceries",
        category_source="manual",
        category_confidence=100,
        needs_category_review=False,
    )


async def test_manual_patch_returns_updated_category_metadata() -> None:
    updated = updated_transaction()
    fake = FakeCategoryService(updated=updated)
    app = create_app()
    app.dependency_overrides[get_category_service] = lambda: fake

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.patch(
            f"/api/transactions/{updated.id}/category",
            json={"category_code": "expense.groceries"},
        )

    assert response.status_code == 200
    assert response.json()["category_source"] == "manual"
    assert response.json()["category_confidence"] == 100
    assert response.json()["needs_category_review"] is False
    assert fake.update_calls == [(updated.id, "expense.groceries")]


@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (TransactionNotFoundError("transaction not found"), 404),
        (InvalidCategoryError("invalid category"), 422),
    ],
)
async def test_manual_patch_maps_domain_errors(
    error: Exception,
    expected_status: int,
) -> None:
    fake = FakeCategoryService(error=error)
    app = create_app()
    app.dependency_overrides[get_category_service] = lambda: fake

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.patch(
            f"/api/transactions/{uuid4()}/category",
            json={"category_code": "expense.groceries"},
        )

    assert response.status_code == expected_status


async def test_manual_patch_rejects_overposting() -> None:
    fake = FakeCategoryService(updated=updated_transaction())
    app = create_app()
    app.dependency_overrides[get_category_service] = lambda: fake

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.patch(
            f"/api/transactions/{uuid4()}/category",
            json={"category_code": "expense.groceries", "owner": 999},
        )

    assert response.status_code == 422
    assert fake.update_calls == []
