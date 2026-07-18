from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.dialects import postgresql

from moneyflow.categories.repository import CategoryRepository
from moneyflow.models import TransactionType


async def test_list_active_excludes_inactive_and_orders_catalog() -> None:
    session = MagicMock()
    rows = MagicMock()
    rows.all.return_value = []
    session.scalars = AsyncMock(return_value=rows)

    assert await CategoryRepository(session).list_active(TransactionType.EXPENSE) == []

    statement = session.scalars.await_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert "categories.transaction_type =" in sql
    assert "categories.is_active IS true" in sql
    assert "ORDER BY categories.sort_order, categories.code" in sql
    assert compiled.params["transaction_type_1"] is TransactionType.EXPENSE


async def test_find_active_scopes_lookup_to_code_and_transaction_type() -> None:
    session = MagicMock()
    rows = MagicMock()
    rows.one_or_none.return_value = None
    session.scalars = AsyncMock(return_value=rows)

    assert (
        await CategoryRepository(session).find_active(
            "expense.groceries",
            TransactionType.EXPENSE,
        )
        is None
    )

    statement = session.scalars.await_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert "categories.code =" in sql
    assert "categories.transaction_type =" in sql
    assert "categories.is_active IS true" in sql
    assert compiled.params["code_1"] == "expense.groceries"
    assert compiled.params["transaction_type_1"] is TransactionType.EXPENSE


async def test_find_active_can_validate_filter_without_transaction_type() -> None:
    session = MagicMock()
    rows = MagicMock()
    rows.one_or_none.return_value = None
    session.scalars = AsyncMock(return_value=rows)

    assert await CategoryRepository(session).find_active("expense.groceries") is None

    statement = session.scalars.await_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "categories.code =" in sql
    assert "categories.transaction_type =" not in sql
    assert "categories.is_active IS true" in sql
