import uuid

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from moneyflow.categories.schemas import CorrectionExample
from moneyflow.models import Category, CategoryCorrection, TransactionType


class CategoryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_active(self, transaction_type: TransactionType) -> list[Category]:
        rows = await self._session.scalars(
            select(Category)
            .where(
                Category.transaction_type == transaction_type,
                Category.is_active.is_(True),
            )
            .order_by(Category.sort_order, Category.code)
        )
        return list(rows.all())


class CategoryCorrectionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_type(
        self, owner: int, transaction_type: TransactionType
    ) -> list[CorrectionExample]:
        rows = await self._session.scalars(
            select(CategoryCorrection)
            .where(
                CategoryCorrection.owner == owner,
                CategoryCorrection.transaction_type == transaction_type,
            )
            .order_by(CategoryCorrection.updated_at.desc(), CategoryCorrection.id)
        )
        return [
            CorrectionExample(row.normalized_description, row.category_code) for row in rows.all()
        ]

    async def upsert(
        self,
        *,
        owner: int,
        transaction_type: TransactionType,
        normalized_description: str,
        category_code: str,
    ) -> None:
        statement = insert(CategoryCorrection).values(
            id=uuid.uuid4(),
            owner=owner,
            transaction_type=transaction_type,
            normalized_description=normalized_description,
            category_code=category_code,
        )
        statement = statement.on_conflict_do_update(
            index_elements=["owner", "transaction_type", "normalized_description"],
            set_={
                "category_code": statement.excluded.category_code,
                "updated_at": func.now(),
            },
        )
        await self._session.execute(statement)
