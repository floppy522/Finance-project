import os
from collections.abc import AsyncIterator

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


@pytest_asyncio.fixture(scope="session")
async def engine() -> AsyncIterator[AsyncEngine]:
    database_url = os.getenv(
        "TEST_DATABASE_URL",
        "postgresql+asyncpg://moneyflow:moneyflow@localhost:5432/moneyflow",
    )
    test_engine = create_async_engine(database_url)
    yield test_engine
    await test_engine.dispose()
