import asyncio
import re

from sqlalchemy import text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import create_async_engine

from moneyflow.config import Settings, get_settings


def validated_e2e_database_url(settings: Settings) -> URL:
    if settings.environment != "test":
        raise RuntimeError("E2E database reset requires ENVIRONMENT=test")

    database_url = make_url(settings.database_url)
    database_name = database_url.database
    if database_name is None or not database_name.endswith("_e2e"):
        raise RuntimeError("E2E database reset requires a database name ending in _e2e")
    if re.fullmatch(r"[A-Za-z0-9_]+", database_name) is None:
        raise RuntimeError("E2E database name may contain only letters, digits, and underscores")
    return database_url


async def prepare_and_reset_database(settings: Settings) -> None:
    database_url = validated_e2e_database_url(settings)
    database_name = database_url.database
    assert database_name is not None

    admin_engine = create_async_engine(
        database_url.set(database="postgres"), isolation_level="AUTOCOMMIT"
    )
    try:
        async with admin_engine.connect() as connection:
            exists = await connection.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :database_name"),
                {"database_name": database_name},
            )
            if exists is None:
                await connection.exec_driver_sql(f'CREATE DATABASE "{database_name}"')
    finally:
        await admin_engine.dispose()

    target_engine = create_async_engine(database_url)
    try:
        async with target_engine.begin() as connection:
            await connection.exec_driver_sql("DROP SCHEMA public CASCADE")
            await connection.exec_driver_sql("CREATE SCHEMA public")
    finally:
        await target_engine.dispose()


async def main() -> None:
    await prepare_and_reset_database(get_settings())


if __name__ == "__main__":
    asyncio.run(main())
