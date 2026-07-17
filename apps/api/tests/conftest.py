import os
from collections.abc import AsyncIterator, Mapping

import pytest_asyncio
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


def validated_test_database_url(environ: Mapping[str, str]) -> str:
    if environ.get("ENVIRONMENT") != "test":
        raise RuntimeError("destructive integration tests require ENVIRONMENT=test")

    raw_database_url = environ.get("TEST_DATABASE_URL")
    if not raw_database_url:
        raise RuntimeError("destructive integration tests require explicit TEST_DATABASE_URL")

    database_url = make_url(raw_database_url)
    database_name = database_url.database
    if database_url.get_backend_name() != "postgresql":
        raise RuntimeError("destructive integration tests require PostgreSQL")
    if database_name is None or not database_name.endswith(("_test", "_e2e")):
        raise RuntimeError("test database name must end in _test or _e2e")
    return raw_database_url


@pytest_asyncio.fixture(scope="session")
async def engine() -> AsyncIterator[AsyncEngine]:
    database_url = validated_test_database_url(os.environ)
    test_engine = create_async_engine(database_url, hide_parameters=True)
    yield test_engine
    await test_engine.dispose()
