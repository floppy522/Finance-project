from types import SimpleNamespace

import pytest
from aiogram.types import Update

from moneyflow.config import Settings
from moneyflow.telegram.router import handle_text_update


def make_update(
    text: str,
    *,
    chat_id: int = 1,
    chat_type: str = "private",
) -> Update:
    return Update.model_validate(
        {
            "update_id": 42,
            "message": {
                "message_id": 42,
                "date": 1_768_651_200,
                "chat": {"id": chat_id, "type": chat_type},
                "from": {
                    "id": 1,
                    "is_bot": False,
                    "first_name": "Owner",
                },
                "text": text,
            },
        }
    )


class RecordingBot:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str]] = []

    async def send_message(self, chat_id: int, text: str) -> None:
        self.messages.append((chat_id, text))


class FailingTransactionService:
    async def create(self, command: object) -> SimpleNamespace:
        del command
        pytest.fail("unauthorized chat reached transaction processing")


class RecordingLoginService:
    def __init__(self) -> None:
        self.revoked_owners: list[int] = []

    async def issue_login_token(self, telegram_user_id: int) -> str:
        del telegram_user_id
        pytest.fail("unauthorized chat reached command processing")

    async def revoke_all_sessions(self, telegram_user_id: int) -> None:
        self.revoked_owners.append(telegram_user_id)


@pytest.mark.parametrize(
    ("chat_id", "chat_type"),
    [(-100, "group"), (-101, "supergroup"), (-102, "channel"), (2, "private")],
)
async def test_commands_are_ignored_outside_owner_private_chat(
    chat_id: int,
    chat_type: str,
) -> None:
    bot = RecordingBot()
    login_service = RecordingLoginService()

    await handle_text_update(
        make_update("/login", chat_id=chat_id, chat_type=chat_type),
        bot=bot,
        settings=Settings(authorized_telegram_user_id=1),
        transaction_service=FailingTransactionService(),  # type: ignore[arg-type]
        login_service=login_service,  # type: ignore[arg-type]
    )

    assert bot.messages == []
    assert login_service.revoked_owners == []


async def test_logout_revokes_owner_sessions_and_confirms() -> None:
    bot = RecordingBot()
    login_service = RecordingLoginService()

    await handle_text_update(
        make_update("/logout"),
        bot=bot,
        settings=Settings(authorized_telegram_user_id=1),
        transaction_service=FailingTransactionService(),  # type: ignore[arg-type]
        login_service=login_service,  # type: ignore[arg-type]
    )

    assert login_service.revoked_owners == [1]
    assert bot.messages == [(1, "Все веб-сессии завершены.")]
