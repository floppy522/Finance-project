from collections.abc import AsyncIterator, Callable
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from moneyflow.config import Settings, get_settings
from moneyflow.db import get_session
from moneyflow.main import create_app
from moneyflow.models import LoginToken, Transaction, UserSettings, WebSession
from moneyflow.telegram.webhook import get_bot


WEBHOOK_SECRET = "test-webhook-secret"


class FakeBot:
    def __init__(self) -> None:
        self.messages: list[str] = []

    async def send_message(self, chat_id: int, text: str) -> None:
        del chat_id
        self.messages.append(text)


def _update_factory(user_id: int) -> Callable[..., dict[str, Any]]:
    def make_update(*, update_id: int, text: str) -> dict[str, Any]:
        return {
            "update_id": update_id,
            "message": {
                "message_id": update_id,
                "date": 1_768_651_200,
                "chat": {"id": user_id, "type": "private"},
                "from": {
                    "id": user_id,
                    "is_bot": False,
                    "first_name": "Owner" if user_id == 1 else "Stranger",
                },
                "text": text,
            },
        }

    return make_update


@pytest.fixture
def authorized_update() -> Callable[..., dict[str, Any]]:
    return _update_factory(1)


@pytest.fixture
def foreign_update() -> Callable[..., dict[str, Any]]:
    return _update_factory(2)


@pytest.fixture
def fake_bot() -> FakeBot:
    return FakeBot()


@pytest_asyncio.fixture
async def session_factory(
    engine: AsyncEngine,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        await session.execute(delete(WebSession))
        await session.execute(delete(LoginToken))
        await session.execute(delete(Transaction))
        await session.execute(delete(UserSettings))
        session.add(UserSettings(telegram_user_id=1))
        await session.commit()

    yield factory

    async with factory() as session:
        await session.execute(delete(WebSession))
        await session.execute(delete(LoginToken))
        await session.execute(delete(Transaction))
        await session.execute(delete(UserSettings))
        await session.commit()


@pytest_asyncio.fixture
async def client(
    session_factory: async_sessionmaker[AsyncSession], fake_bot: FakeBot
) -> AsyncIterator[AsyncClient]:
    app = create_app()

    async def override_get_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_settings] = lambda: Settings(
        telegram_webhook_secret=WEBHOOK_SECRET,
        authorized_telegram_user_id=1,
        public_web_url="http://localhost:5173",
    )
    app.dependency_overrides[get_bot] = lambda: fake_bot
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as webhook_client:
        yield webhook_client


@pytest.fixture
def transaction_count(
    session_factory: async_sessionmaker[AsyncSession],
) -> Callable[[], Any]:
    async def count() -> int:
        async with session_factory() as session:
            value = await session.scalar(select(func.count()).select_from(Transaction))
            return int(value or 0)

    return count


async def post_valid_webhook(
    client: AsyncClient, update: dict[str, Any]
):
    return await client.post(
        "/telegram/webhook",
        headers={"X-Telegram-Bot-Api-Secret-Token": WEBHOOK_SECRET},
        json=update,
    )


async def test_wrong_secret_returns_401(
    client: AsyncClient, authorized_update: Callable[..., dict[str, Any]]
) -> None:
    response = await client.post(
        "/telegram/webhook",
        headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
        json=authorized_update(update_id=10, text="кофе 350"),
    )

    assert response.status_code == 401


async def test_foreign_user_creates_no_transaction(
    client: AsyncClient,
    foreign_update: Callable[..., dict[str, Any]],
    transaction_count: Callable[[], Any],
    fake_bot: FakeBot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_if_parser_is_invoked(*args: object, **kwargs: object) -> None:
        del args, kwargs
        pytest.fail("foreign update reached the parser")

    monkeypatch.setattr(
        "moneyflow.telegram.router.parse_simple_expense", fail_if_parser_is_invoked
    )
    response = await post_valid_webhook(
        client,
        foreign_update(update_id=11, text="private text 350"),
    )

    assert response.status_code == 204
    assert await transaction_count() == 0
    assert fake_bot.messages == []


async def test_repeated_update_creates_one_transaction(
    client: AsyncClient,
    authorized_update: Callable[..., dict[str, Any]],
    transaction_count: Callable[[], Any],
) -> None:
    update = authorized_update(update_id=12, text="кофе 350")

    assert (await post_valid_webhook(client, update)).status_code == 204
    assert (await post_valid_webhook(client, update)).status_code == 204
    assert await transaction_count() == 1


async def test_login_command_returns_one_time_web_link(
    client: AsyncClient,
    authorized_update: Callable[..., dict[str, Any]],
    fake_bot: FakeBot,
) -> None:
    response = await post_valid_webhook(
        client,
        authorized_update(update_id=13, text="/login"),
    )

    assert response.status_code == 204
    assert fake_bot.messages[0].startswith("http://localhost:5173/login?token=")
