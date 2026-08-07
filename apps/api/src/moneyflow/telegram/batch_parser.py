import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, localcontext
from zoneinfo import ZoneInfo

from moneyflow.models import CategorySource, TransactionDirection, TransactionType
from moneyflow.transactions.schemas import CreateTransactionCommand


_MAX_NON_EMPTY_LINES = 100
_MAX_AMOUNT_KOPECKS = 2**63 - 1
_MONTHS = {
    "января": 1,
    "февраля": 2,
    "марта": 3,
    "апреля": 4,
    "мая": 5,
    "июня": 6,
    "июля": 7,
    "августа": 8,
    "сентября": 9,
    "октября": 10,
    "ноября": 11,
    "декабря": 12,
}
_DATE_PREFIX = re.compile(
    r"^(?P<date>сегодня|вчера|\d{4}-\d{2}-\d{2}|\d{1,2}\.\d{1,2}(?:\.\d{4})?|"
    r"\d{1,2}\s+(?:января|февраля|марта|апреля|мая|июня|июля|августа|сентября|"
    r"октября|ноября|декабря))(?=$|\s)",
    re.IGNORECASE,
)
_FINAL_AMOUNT = re.compile(
    r"^(?P<description>.+?)\s+(?P<amount>[+-]?(?:\d{1,3}(?: \d{3})+|\d+)(?:[.,]\d{1,2})?)$"
)
_INDEPENDENT_NUMBER = re.compile(r"(?<!\w)\d+(?!\w)")
_INCOME_PREFIX_STEMS = ("зарплат", "дивиденд", "возврат")
_INCOME_EXACT_WORDS = frozenset({"получил", "получила"})


@dataclass(frozen=True, slots=True)
class ParsedTransactionLine:
    line_number: int
    description: str
    amount_kopecks: int
    occurred_at: datetime
    transaction_type: TransactionType
    direction: TransactionDirection
    source_event_id: str

    def to_command(
        self,
        *,
        source_event_id: str | None = None,
        category_code: str | None = None,
        category_source: CategorySource | None = None,
        category_confidence: int | None = None,
        needs_category_review: bool | None = None,
    ) -> CreateTransactionCommand:
        return CreateTransactionCommand(
            transaction_type=self.transaction_type,
            direction=self.direction,
            amount_kopecks=self.amount_kopecks,
            occurred_at=self.occurred_at,
            description=self.description,
            source="telegram",
            source_event_id=source_event_id or self.source_event_id,
            category_code=category_code,
            category_source=category_source,
            category_confidence=category_confidence,
            needs_category_review=needs_category_review,
        )


@dataclass(frozen=True, slots=True)
class RejectedInputLine:
    line_number: int
    text: str
    reason: str


@dataclass(frozen=True, slots=True)
class BatchParseResult:
    items: tuple[ParsedTransactionLine, ...]
    rejected: tuple[RejectedInputLine, ...]


def parse_batch_message(
    text: str,
    message_time: datetime,
    timezone: str,
    update_id: int,
) -> BatchParseResult:
    zone = ZoneInfo(timezone)
    occurred_at = _as_utc(message_time)
    local_message_date = occurred_at.astimezone(zone).date()
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if sum(bool(line.strip()) for line in lines) > _MAX_NON_EMPTY_LINES:
        return BatchParseResult(
            items=(),
            rejected=(RejectedInputLine(0, "", "слишком много непустых строк"),),
        )

    items: list[ParsedTransactionLine] = []
    rejected: list[RejectedInputLine] = []
    active_date: date | None = None
    for line_number, raw_line in enumerate(lines, start=1):
        stripped_line = raw_line.strip()
        if not stripped_line:
            continue
        line = _strip_bullet(stripped_line)
        parsed_date, remainder, date_error = _take_date_prefix(line, local_message_date)
        if date_error:
            rejected.append(RejectedInputLine(line_number, raw_line, "некорректная дата"))
            continue
        if parsed_date is not None and not remainder:
            active_date = parsed_date
            continue

        operation = remainder if parsed_date is not None else line
        item, reason = _parse_operation(
            operation,
            line_number=line_number,
            occurred_at=_noon_utc(parsed_date, zone) if parsed_date else (
                _noon_utc(active_date, zone) if active_date else occurred_at
            ),
            update_id=update_id,
        )
        if item is not None:
            items.append(item)
        else:
            rejected.append(RejectedInputLine(line_number, raw_line, reason))
    return BatchParseResult(items=tuple(items), rejected=tuple(rejected))


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _strip_bullet(line: str) -> str:
    return line[2:].lstrip() if len(line) > 1 and line[0] in "-•*" and line[1].isspace() else line


def _take_date_prefix(line: str, local_message_date: date) -> tuple[date | None, str, bool]:
    match = _DATE_PREFIX.match(line)
    if match is None:
        return None, line, False
    token = match.group("date").casefold()
    try:
        parsed = _parse_date(token, local_message_date)
    except ValueError:
        return None, "", True
    return parsed, line[match.end() :].strip(), False


def _parse_date(token: str, local_message_date: date) -> date:
    if token == "сегодня":
        return local_message_date
    if token == "вчера":
        return local_message_date - timedelta(days=1)
    if "-" in token:
        return date.fromisoformat(token)
    if " " in token:
        day_text, month_text = token.split()
        return _date_with_inferred_year(int(day_text), _MONTHS[month_text], local_message_date)
    pieces = token.split(".")
    day, month = (int(value) for value in pieces[:2])
    if len(pieces) == 3:
        return date(int(pieces[2]), month, day)
    return _date_with_inferred_year(day, month, local_message_date)


def _date_with_inferred_year(day: int, month: int, local_message_date: date) -> date:
    candidate = date(local_message_date.year, month, day)
    if candidate > local_message_date + timedelta(days=31):
        return date(local_message_date.year - 1, month, day)
    return candidate


def _noon_utc(value: date, zone: ZoneInfo) -> datetime:
    return datetime.combine(value, time(hour=12), tzinfo=zone).astimezone(UTC)


def _parse_operation(
    text: str,
    *,
    line_number: int,
    occurred_at: datetime,
    update_id: int,
) -> tuple[ParsedTransactionLine | None, str]:
    match = _FINAL_AMOUNT.fullmatch(text)
    if match is None:
        return None, "укажите сумму"
    description = match.group("description").strip()
    if not description:
        return None, "укажите описание"
    if _INDEPENDENT_NUMBER.search(description):
        return None, "несколько чисел в строке"

    amount_text = match.group("amount")
    sign = amount_text[0] if amount_text[0] in "+-" else ""
    normalized_amount = amount_text.lstrip("+-").replace(" ", "").replace(",", ".")
    with localcontext() as context:
        context.prec = len(normalized_amount.replace(".", "")) + 2
        amount_kopecks = int(Decimal(normalized_amount) * 100)
    if amount_kopecks <= 0:
        return None, "сумма должна быть больше нуля"
    if amount_kopecks > _MAX_AMOUNT_KOPECKS:
        return None, "сумма слишком большая"

    is_income = sign == "+" or (not sign and _has_income_marker(description))
    return (
        ParsedTransactionLine(
            line_number=line_number,
            description=description,
            amount_kopecks=amount_kopecks,
            occurred_at=occurred_at,
            transaction_type=TransactionType.INCOME if is_income else TransactionType.EXPENSE,
            direction=TransactionDirection.NORMAL,
            source_event_id=f"telegram:{update_id}:{line_number}",
        ),
        "",
    )


def _has_income_marker(description: str) -> bool:
    words = re.findall(r"\b\w+\b", description.casefold())
    return any(
        word in _INCOME_EXACT_WORDS or word.startswith(_INCOME_PREFIX_STEMS) for word in words
    )
