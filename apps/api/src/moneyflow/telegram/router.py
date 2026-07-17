from datetime import UTC, datetime
from typing import Protocol

from aiogram.types import Update

from moneyflow.auth.service import LoginService
from moneyflow.config import Settings
from moneyflow.telegram.parser import FORMAT_INSTRUCTION, parse_simple_expense
from moneyflow.transactions.service import TransactionService


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
        return

    text = message.text
    if text is None:
        return

    if text == "/login":
        token = await login_service.issue_login_token(from_user.id)
        login_url = f"{settings.public_web_url.rstrip('/')}/login?token={token}"
        await bot.send_message(chat_id=message.chat.id, text=login_url)
        return

    try:
        command = parse_simple_expense(
            text,
            datetime.now(UTC),
            f"telegram:{update.update_id}",
        )
    except ValueError:
        await bot.send_message(chat_id=message.chat.id, text=FORMAT_INSTRUCTION)
        return

    transaction = await transaction_service.create(command)
    await bot.send_message(
        chat_id=message.chat.id,
        text=(
            f"Записал: {_format_amount(transaction.amount_kopecks)} ₽ — "
            f"{transaction.description}"
        ),
    )
