import hashlib
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from moneyflow.auth.service import LoginService
from moneyflow.db import get_session
from moneyflow.main import create_app
from moneyflow.models import LoginToken, UserSettings, WebSession


NOW = datetime(2026, 7, 17, 12, tzinfo=UTC)


@pytest_asyncio.fixture
async def session_factory(
    engine: AsyncEngine,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as cleanup_session:
        await cleanup_session.execute(delete(WebSession))
        await cleanup_session.execute(delete(LoginToken))
        await cleanup_session.execute(delete(UserSettings))
        cleanup_session.add(UserSettings(telegram_user_id=1))
        await cleanup_session.commit()
    yield factory
    async with factory() as cleanup_session:
        await cleanup_session.execute(delete(WebSession))
        await cleanup_session.execute(delete(LoginToken))
        await cleanup_session.execute(delete(UserSettings))
        await cleanup_session.commit()


@pytest_asyncio.fixture
async def session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with session_factory() as auth_session:
        yield auth_session
        await auth_session.rollback()


def service(session: AsyncSession, *, minute: int = 0) -> LoginService:
    return LoginService(session, clock=lambda: NOW + timedelta(minutes=minute))


async def test_login_token_is_single_use(session: AsyncSession) -> None:
    login = await service(session).issue_login_token(1)
    web_session = await service(session, minute=1).exchange_login_token(login)
    assert await service(session, minute=1).authenticate_session(web_session) == 1
    with pytest.raises(PermissionError, match="invalid credentials"):
        await service(session, minute=1).exchange_login_token(login)


async def test_login_token_expires_at_exactly_ten_minutes(session: AsyncSession) -> None:
    login = await service(session).issue_login_token(1)
    with pytest.raises(PermissionError, match="invalid credentials"):
        await service(session, minute=10).exchange_login_token(login)


async def test_revoke_all_sessions(session: AsyncSession) -> None:
    login = await service(session).issue_login_token(1)
    web_session = await service(session, minute=1).exchange_login_token(login)
    await service(session, minute=2).revoke_all_sessions(1)
    with pytest.raises(PermissionError, match="invalid credentials"):
        await service(session, minute=2).authenticate_session(web_session)


async def test_database_stores_hashes_not_raw_credentials(session: AsyncSession) -> None:
    login = await service(session).issue_login_token(1)
    web_session = await service(session).exchange_login_token(login)

    stored_login = await session.scalar(select(LoginToken))
    stored_session = await session.scalar(select(WebSession))
    assert stored_login is not None
    assert stored_session is not None
    assert stored_login.token_hash == hashlib.sha256(login.encode()).hexdigest()
    assert stored_session.token_hash == hashlib.sha256(web_session.encode()).hexdigest()
    assert login not in {stored_login.token_hash, stored_session.token_hash}
    assert web_session not in {stored_login.token_hash, stored_session.token_hash}


@pytest_asyncio.fixture
async def client(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncClient]:
    app = create_app()

    async def override_get_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as route_session:
            yield route_session

    app.dependency_overrides[get_session] = override_get_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as auth_client:
        yield auth_client


async def test_exchange_sets_constrained_http_only_cookie(
    client: AsyncClient, session: AsyncSession
) -> None:
    login_token = await service(session).issue_login_token(1)
    response = await client.post("/api/auth/exchange", json={"token": login_token})

    assert response.status_code == 204
    cookie = response.headers["set-cookie"]
    assert cookie.startswith("moneyflow_session=")
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert "Path=/" in cookie
    assert "Max-Age=2592000" in cookie
    assert "Secure" not in cookie


async def test_me_and_revoke_session(client: AsyncClient, session: AsyncSession) -> None:
    login_token = await service(session).issue_login_token(1)
    assert (await client.post("/api/auth/exchange", json={"token": login_token})).status_code == 204
    assert (await client.get("/api/auth/me")).json() == {"telegram_user_id": 1}

    response = await client.delete("/api/auth/sessions")

    assert response.status_code == 204
    assert 'moneyflow_session=""' in response.headers["set-cookie"]
    assert (await client.get("/api/auth/me")).status_code == 401


async def test_bad_exchange_is_opaque(client: AsyncClient) -> None:
    response = await client.post("/api/auth/exchange", json={"token": "unknown"})
    assert response.status_code == 401
    assert response.json() == {"detail": "invalid credentials"}


async def test_transactions_require_session(client: AsyncClient) -> None:
    assert (await client.get("/api/transactions")).status_code == 401
