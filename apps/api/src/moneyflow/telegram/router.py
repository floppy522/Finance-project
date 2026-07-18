import logging
from collections.abc import Sequence
from contextlib import AbstractAsyncContextManager
from datetime import UTC, date
from typing import Protocol
from zoneinfo import ZoneInfo

from aiogram.types import Update
from sqlalchemy.exc import SQLAlchemyError

from moneyflow.auth.service import LoginService
from moneyflow.categories.catalog import CATEGORY_BY_CODE
from moneyflow.config import Settings
from moneyflow.models import Transaction, TransactionType
from moneyflow.telegram.batch_parser import RejectedInputLine, parse_batch_message
from moneyflow.telegram.ingestion import BatchIngestionResult, BatchIngestionService


logger = logging.getLogger(__name__)

_MAX_RESULT_LINES = 20
_TELEGRAM_MESSAGE_LIMIT = 4096
_DATABASE_ERROR_MESSAGE = (
    "Не удалось сохранить операции из-за временной ошибки. Попробуйте ещё раз позже."
)
_MONTH_NAMES = (
    "",
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)


class BotClient(Protocol):
    async def send_message(self, chat_id: int, text: str) -> object: ...


class OwnerTimezoneLoader(Protocol):
    async def __call__(self) -> str: ...


class IngestionServiceFactory(Protocol):
    def __call__(self) -> AbstractAsyncContextManager[BatchIngestionService]: ...


async def handle_text_update(
    update: Update,
    *,
    bot: BotClient,
    settings: Settings,
    owner_timezone_loader: OwnerTimezoneLoader,
    ingestion_service_factory: IngestionServiceFactory,
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

    parse_result = None
    try:
        owner_timezone = await owner_timezone_loader()
        parse_result = parse_batch_message(
            text,
            message.date,
            owner_timezone,
            update.update_id,
        )
        async with ingestion_service_factory() as ingestion_service:
            result = await ingestion_service.ingest(parse_result)
    except SQLAlchemyError:
        logger.error(
            "batch_persistence_failed",
            extra={
                "event": "batch_persistence_failed",
                "request_id": str(update.update_id),
                "source": "telegram",
                "outcome": "failed",
                "item_count": len(parse_result.items) if parse_result is not None else 0,
                "rejected_count": (len(parse_result.rejected) if parse_result is not None else 0),
            },
        )
        await bot.send_message(chat_id=message.chat.id, text=_DATABASE_ERROR_MESSAGE)
        return

    logger.info(
        "batch_processed",
        extra={
            "event": "batch_processed",
            "request_id": str(update.update_id),
            "source": "telegram",
            "outcome": "accepted",
            "item_count": len(parse_result.items),
            "saved_count": len(result.saved),
            "duplicate_count": len(result.duplicates),
            "rejected_count": len(result.rejected),
        },
    )
    await bot.send_message(
        chat_id=message.chat.id,
        text=_format_batch_summary(result, owner_timezone),
    )


def _format_batch_summary(result: BatchIngestionResult, timezone: str) -> str:
    total_results = len(result.saved) + len(result.duplicates) + len(result.rejected)
    if total_results == 0:
        return "Не распознано ни одной операции."

    for rendered_count in range(min(total_results, _MAX_RESULT_LINES), -1, -1):
        summary = _render_batch_summary(result, timezone, rendered_count)
        if len(summary) <= _TELEGRAM_MESSAGE_LIMIT:
            return summary
    raise RuntimeError("summary headings exceed Telegram message limit")


def _render_batch_summary(
    result: BatchIngestionResult,
    timezone: str,
    rendered_count: int,
) -> str:
    remaining_slots = rendered_count
    sections: list[str] = []
    for title, transactions in (
        ("Сохранено", result.saved),
        ("Ранее сохранено", result.duplicates),
    ):
        selected = transactions[:remaining_slots]
        remaining_slots -= len(selected)
        if transactions:
            sections.append(
                _format_transaction_section(
                    title,
                    transactions,
                    selected,
                    timezone,
                )
            )

    selected_rejections = result.rejected[:remaining_slots]
    if result.rejected:
        sections.append(_format_rejection_section(result.rejected, selected_rejections))

    total_results = len(result.saved) + len(result.duplicates) + len(result.rejected)
    omitted_count = total_results - rendered_count
    if omitted_count:
        sections.append(f"…и ещё {omitted_count}")

    return "\n\n".join(sections)


def _format_transaction_section(
    title: str,
    all_transactions: Sequence[Transaction],
    selected: Sequence[Transaction],
    timezone: str,
) -> str:
    lines = [f"{title}: {_pluralized(len(all_transactions), 'операция', 'операции', 'операций')}"]
    zone = ZoneInfo(timezone)
    grouped: dict[date, list[Transaction]] = {}
    for transaction in selected:
        occurred_at = transaction.occurred_at
        if occurred_at.tzinfo is None:
            occurred_at = occurred_at.replace(tzinfo=UTC)
        local_date = occurred_at.astimezone(zone).date()
        grouped.setdefault(local_date, []).append(transaction)
    for local_date, transactions in grouped.items():
        lines.append(f"{local_date.day} {_MONTH_NAMES[local_date.month]} {local_date.year}")
        lines.extend(_format_transaction(transaction) for transaction in transactions)
    return "\n".join(lines)


def _format_transaction(transaction: Transaction) -> str:
    sign = "+" if transaction.type is TransactionType.INCOME else "−"
    category = CATEGORY_BY_CODE.get(transaction.category_code or "")
    category_name = category.name_ru if category is not None else "Без категории"
    return (
        f"{sign}{_format_amount(transaction.amount_kopecks)} ₽ · "
        f"{category_name} · {transaction.description}"
    )


def _format_rejection_section(
    all_rejections: Sequence[RejectedInputLine],
    selected: Sequence[RejectedInputLine],
) -> str:
    lines = ["Не распознано: " + _pluralized(len(all_rejections), "строка", "строки", "строк")]
    lines.extend(
        f"строка {rejection.line_number}: {rejection.text} — {rejection.reason}"
        for rejection in selected
    )
    return "\n".join(lines)


def _pluralized(count: int, one: str, few: str, many: str) -> str:
    last_two = count % 100
    if 11 <= last_two <= 14:
        form = many
    else:
        last = count % 10
        form = one if last == 1 else few if 2 <= last <= 4 else many
    return f"{count} {form}"


def _format_amount(amount_kopecks: int) -> str:
    rubles, kopecks = divmod(amount_kopecks, 100)
    return f"{rubles:,}".replace(",", " ") + f",{kopecks:02d}"
