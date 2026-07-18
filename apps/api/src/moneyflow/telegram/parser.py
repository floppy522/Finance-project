from datetime import datetime

from moneyflow.models import TransactionType
from moneyflow.transactions.schemas import CreateTransactionCommand
from moneyflow.telegram.batch_parser import parse_batch_message


FORMAT_INSTRUCTION = "Формат: описание сумма. Например: кофе 350"
def parse_simple_expense(
    text: str, now: datetime, source_event_id: str
) -> CreateTransactionCommand:
    result = parse_batch_message(text, now, "UTC", 0)
    if (
        len(result.items) != 1
        or result.rejected
        or result.items[0].transaction_type is not TransactionType.EXPENSE
    ):
        raise ValueError(FORMAT_INSTRUCTION)
    return result.items[0].to_command(source_event_id=source_event_id)
