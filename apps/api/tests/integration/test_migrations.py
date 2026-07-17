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
