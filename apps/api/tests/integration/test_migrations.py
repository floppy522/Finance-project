from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


async def test_initial_migration_creates_required_tables(engine: AsyncEngine) -> None:
    async with engine.connect() as connection:
        result = await connection.execute(
            text("select tablename from pg_tables where schemaname='public'")
        )
    assert set(result.scalars()) >= {
        "alembic_version",
        "login_tokens",
        "transactions",
        "user_settings",
        "web_sessions",
    }


async def test_category_migration_creates_seeded_catalog(engine: AsyncEngine) -> None:
    async with engine.connect() as connection:
        tables = set(
            (
                await connection.execute(
                    text("select tablename from pg_tables where schemaname='public'")
                )
            ).scalars()
        )
        rows = (
            await connection.execute(
                text(
                    "select code, transaction_type, name_ru, sort_order, is_active "
                    "from categories order by transaction_type, sort_order"
                )
            )
        ).all()

    assert {"categories", "category_corrections"} <= tables
    assert rows == [
        ("expense.groceries", "expense", "Продукты", 1, True),
        ("expense.cafes", "expense", "Кафе и рестораны", 2, True),
        ("expense.transport", "expense", "Транспорт", 3, True),
        ("expense.housing", "expense", "Жильё", 4, True),
        ("expense.health", "expense", "Здоровье", 5, True),
        ("expense.shopping", "expense", "Покупки", 6, True),
        ("expense.entertainment", "expense", "Развлечения", 7, True),
        ("expense.subscriptions", "expense", "Подписки", 8, True),
        ("expense.travel", "expense", "Путешествия", 9, True),
        ("expense.education", "expense", "Образование", 10, True),
        ("expense.gifts", "expense", "Подарки", 11, True),
        ("expense.other", "expense", "Прочее", 12, True),
        ("income.salary", "income", "Зарплата", 1, True),
        ("income.investments", "income", "Инвестиционный доход", 2, True),
        ("income.refunds", "income", "Возвраты", 3, True),
        ("income.gifts", "income", "Подарки", 4, True),
        ("income.other", "income", "Прочее", 5, True),
    ]
