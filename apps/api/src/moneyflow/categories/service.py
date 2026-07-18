from collections.abc import Coroutine
from typing import Any, Protocol, cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from moneyflow.categories.normalization import normalize_description
from moneyflow.categories.repository import (
    CategoryCorrectionRepository,
    CategoryRepository,
)
from moneyflow.models import Category, CategorySource, Transaction, TransactionType
from moneyflow.transactions.repository import TransactionRepository


class InvalidCategoryError(ValueError):
    pass


class TransactionNotFoundError(LookupError):
    pass


class Session(Protocol):
    def commit(self) -> Coroutine[Any, Any, None]: ...

    def rollback(self) -> Coroutine[Any, Any, None]: ...


class CategoryReader(Protocol):
    async def list_active(self, transaction_type: TransactionType) -> list[Category]: ...

    async def find_active(
        self,
        code: str,
        transaction_type: TransactionType | None = None,
    ) -> Category | None: ...


class CorrectionWriter(Protocol):
    async def upsert(
        self,
        *,
        owner: int,
        transaction_type: TransactionType,
        normalized_description: str,
        category_code: str,
    ) -> None: ...


class TransactionReader(Protocol):
    async def find_owned(self, transaction_id: UUID, owner: int) -> Transaction | None: ...


class CategoryService:
    def __init__(
        self,
        session: AsyncSession | Session,
        owner: int,
        *,
        category_repository: CategoryReader | None = None,
        correction_repository: CorrectionWriter | None = None,
        transaction_repository: TransactionReader | None = None,
    ) -> None:
        self._session = session
        self._owner = owner
        sqlalchemy_session = cast(AsyncSession, session)
        self._categories = category_repository or CategoryRepository(sqlalchemy_session)
        self._corrections = correction_repository or CategoryCorrectionRepository(
            sqlalchemy_session
        )
        self._transactions = transaction_repository or TransactionRepository(
            sqlalchemy_session
        )

    async def list_active(self, transaction_type: TransactionType) -> list[Category]:
        if transaction_type not in {TransactionType.EXPENSE, TransactionType.INCOME}:
            raise InvalidCategoryError("invalid category")
        return await self._categories.list_active(transaction_type)

    async def validate_filter_category(self, category_code: str) -> None:
        if await self._categories.find_active(category_code) is None:
            raise InvalidCategoryError("invalid category")

    async def update_transaction_category(
        self,
        transaction_id: UUID,
        category_code: str,
    ) -> Transaction:
        try:
            transaction = await self._transactions.find_owned(transaction_id, self._owner)
            if transaction is None:
                raise TransactionNotFoundError("transaction not found")

            category = await self._categories.find_active(category_code, transaction.type)
            if category is None:
                raise InvalidCategoryError("invalid category")

            transaction.category_code = category.code
            transaction.category_source = CategorySource.MANUAL
            transaction.category_confidence = 100
            transaction.needs_category_review = False
            await self._corrections.upsert(
                owner=self._owner,
                transaction_type=transaction.type,
                normalized_description=normalize_description(transaction.description),
                category_code=category.code,
            )
            await self._session.commit()
            return transaction
        except Exception:
            await self._session.rollback()
            raise
