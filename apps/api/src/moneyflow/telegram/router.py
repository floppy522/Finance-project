import logging
from datetime import UTC, datetime
from typing import Protocol

from aiogram.types import Update

from moneyflow.auth.service import LoginService
from moneyflow.config import Settings
from moneyflow.telegram.parser import FORMAT_INSTRUCTION, parse_simple_expense
from moneyflow.transactions.service import TransactionService


logger = logging.getLogger(__name__)


class BotClient(Protocol):
    async def send_message(self, chat_id: int, text: str) -> object: ...


def _format_amount(amount_kopecks: int) -> str:
    rubles, kopecks = divmod(amount_kopecks, 100)
    return f"{rubles},{kopecks:02d}"


async def handle_text_update(
    update: Update,
    *,
    bot: BotClient,
    settings: Settings,
    transaction_service: TransactionService,
    login_service: LoginService,
) -> None:
    message = update.message
    if message is None:
        return

    from_user = message.from_user
    if from_user is None or from_user.id != settings.authorized_telegram_user_id:
        logger.warning(
            "foreign_user_rejected",
            extra={
                "event": "foreign_user_rejected",
                "request_id": str(update.update_id),
                "source": "telegram",
                "outcome": "rejected",
            },
        )
        return

    if message.chat.type != "private" or message.chat.id != from_user.id:
        return

    text = message.text
    if text is None:
        return

    if text == "/login":
        token = await login_service.issue_login_token(from_user.id)
        login_url = f"{settings.public_web_url.rstrip('/')}/login?token={token}"
        await bot.send_message(chat_id=message.chat.id, text=login_url)
        return

    if text in {"/logout", "/revoke_sessions"}:
        await login_service.revoke_all_sessions(from_user.id)
        await bot.send_message(
            chat_id=message.chat.id,
            text="Все веб-сессии завершены.",
        )
        return

    try:
        command = parse_simple_expense(
            text,
            datetime.now(UTC),
            f"telegram:{update.update_id}",
        )
    except ValueError:
        logger.info(
            "parser_rejected",
            extra={
                "event": "parser_rejected",
                "request_id": str(update.update_id),
                "source": "telegram",
                "outcome": "rejected",
            },
        )
        await bot.send_message(chat_id=message.chat.id, text=FORMAT_INSTRUCTION)
        return

    transaction = await transaction_service.create(command)
    logger.info(
        "transaction_created",
        extra={
            "event": "transaction_created",
            "request_id": str(update.update_id),
            "source": "telegram",
            "outcome": "created",
        },
    )
    await bot.send_message(
        chat_id=message.chat.id,
        text=(
            f"Записал: {_format_amount(transaction.amount_kopecks)} ₽ — "
            f"{transaction.description}"
        ),
    )
