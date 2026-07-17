from datetime import UTC, datetime

import pytest

from moneyflow.models import TransactionDirection, TransactionType
from moneyflow.telegram.parser import parse_simple_expense


FIXED_NOW = datetime(2026, 7, 17, 12, tzinfo=UTC)


def test_parses_description_and_rubles() -> None:
    result = parse_simple_expense("кофе 350", FIXED_NOW, "telegram:10")

    assert result.description == "кофе"
    assert result.amount_kopecks == 35_000
    assert result.transaction_type is TransactionType.EXPENSE
    assert result.direction is TransactionDirection.NORMAL
    assert result.occurred_at == FIXED_NOW
    assert result.source == "telegram"
    assert result.source_event_id == "telegram:10"


def test_parses_fractional_rubles_with_decimal_arithmetic() -> None:
    result = parse_simple_expense("кофе 350,25", FIXED_NOW, "telegram:11")

    assert result.amount_kopecks == 35_025


@pytest.mark.parametrize("text", ["", "кофе", "350", "кофе -350", "кофе 0"])
def test_rejects_ambiguous_input(text: str) -> None:
    with pytest.raises(ValueError, match="Формат"):
        parse_simple_expense(text, FIXED_NOW, "telegram:12")
