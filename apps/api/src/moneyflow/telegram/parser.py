import re
from datetime import UTC, datetime
from decimal import Decimal

from moneyflow.models import TransactionDirection, TransactionType
from moneyflow.transactions.schemas import CreateTransactionCommand


FORMAT_INSTRUCTION = "Формат: описание сумма. Например: кофе 350"
_SIMPLE_EXPENSE = re.compile(
    r"^(?P<description>[^\d]+?)\s+(?P<amount>\d+(?:[.,]\d{1,2})?)$"
)


def parse_simple_expense(
    text: str, now: datetime, source_event_id: str
) -> CreateTransactionCommand:
    match = _SIMPLE_EXPENSE.fullmatch(text.strip())
    if match is None:
        raise ValueError(FORMAT_INSTRUCTION)

    description = match.group("description").strip()
    if not description or description.endswith("-"):
        raise ValueError(FORMAT_INSTRUCTION)

    amount_rubles = Decimal(match.group("amount").replace(",", "."))
    amount_kopecks = int(amount_rubles * 100)
    if amount_kopecks <= 0:
        raise ValueError(FORMAT_INSTRUCTION)

    occurred_at = now.replace(tzinfo=UTC) if now.tzinfo is None else now.astimezone(UTC)
    return CreateTransactionCommand(
        transaction_type=TransactionType.EXPENSE,
        direction=TransactionDirection.NORMAL,
        amount_kopecks=amount_kopecks,
        occurred_at=occurred_at,
        description=description,
        source="telegram",
        source_event_id=source_event_id,
    )
