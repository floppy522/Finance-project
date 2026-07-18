from datetime import UTC, datetime

import pytest

from moneyflow.models import TransactionDirection, TransactionType
from moneyflow.telegram.batch_parser import parse_batch_message


FIXED = datetime(2026, 7, 18, 9, 30, tzinfo=UTC)


def test_parses_date_headers_inline_dates_income_and_bullets() -> None:
    result = parse_batch_message(
        "15 июля\n- кофе 350\n• такси 780\n16.07 зарплата +150 000",
        message_time=FIXED,
        timezone="Europe/Moscow",
        update_id=7001,
    )

    assert [(x.line_number, x.description, x.amount_kopecks) for x in result.items] == [
        (2, "кофе", 35_000),
        (3, "такси", 78_000),
        (4, "зарплата", 15_000_000),
    ]
    assert result.items[0].occurred_at == datetime(2026, 7, 15, 9, tzinfo=UTC)
    assert result.items[2].transaction_type is TransactionType.INCOME
    assert result.items[2].source_event_id == "telegram:7001:4"


@pytest.mark.parametrize("text", ["31.02\nкофе 350", "бензин 40 литров 2500", "кофе 0"])
def test_rejects_unsafe_financial_guesses(text: str) -> None:
    result = parse_batch_message(text, FIXED, "Europe/Moscow", 7002)

    assert result.rejected


def test_uses_today_yesterday_and_year_rollover_for_date_only_values() -> None:
    result = parse_batch_message(
        "сегодня\nкофе 1\nвчера\nтакси 2\n31.12 подарок 3",
        FIXED,
        "Europe/Moscow",
        7003,
    )

    assert [item.occurred_at for item in result.items] == [
        datetime(2026, 7, 18, 9, tzinfo=UTC),
        datetime(2026, 7, 17, 9, tzinfo=UTC),
        datetime(2025, 12, 31, 9, tzinfo=UTC),
    ]


@pytest.mark.parametrize("amount", ["350,50", "350.50"])
def test_parses_decimal_amounts(amount: str) -> None:
    result = parse_batch_message(f"кофе {amount}", FIXED, "Europe/Moscow", 7004)

    assert result.items[0].amount_kopecks == 35_050


def test_explicit_signs_take_precedence_over_income_words() -> None:
    result = parse_batch_message(
        "зарплата -780\nкофе +15",
        FIXED,
        "Europe/Moscow",
        7005,
    )

    assert [(item.transaction_type, item.direction) for item in result.items] == [
        (TransactionType.EXPENSE, TransactionDirection.NORMAL),
        (TransactionType.INCOME, TransactionDirection.NORMAL),
    ]


@pytest.mark.parametrize("description", ["зарплата", "получил перевод", "получила премию", "дивиденды", "возврат"])
def test_recognizes_word_based_income_markers(description: str) -> None:
    result = parse_batch_message(f"{description} 100", FIXED, "Europe/Moscow", 7006)

    assert result.items[0].transaction_type is TransactionType.INCOME


def test_rejects_the_entire_message_when_it_has_more_than_100_non_empty_lines() -> None:
    result = parse_batch_message("\n".join("кофе 1" for _ in range(101)), FIXED, "UTC", 7007)

    assert result.items == ()
    assert len(result.rejected) == 1


def test_ignores_blank_lines_and_star_bullets() -> None:
    result = parse_batch_message("\n* кофе 10\n\n", FIXED, "UTC", 7008)

    assert [(item.line_number, item.description) for item in result.items] == [(2, "кофе")]


def test_uses_message_timestamp_when_an_operation_has_no_explicit_date() -> None:
    result = parse_batch_message("кофе 350", FIXED, "Europe/Moscow", 7009)

    assert result.items[0].occurred_at == FIXED
