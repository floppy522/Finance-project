from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from aiogram.types import Update
from sqlalchemy.exc import SQLAlchemyError

from moneyflow.config import Settings
from moneyflow.categories.schemas import CategoryInput
from moneyflow.models import CategorySource, Transaction, TransactionDirection, TransactionType
from moneyflow.telegram.batch_parser import BatchParseResult
from moneyflow.telegram.ingestion import BatchIngestionResult
from moneyflow.telegram.router import handle_text_update
from moneyflow.telegram.webhook import get_batch_ingestion_service, get_category_provider


MESSAGE_TIME = datetime(2026, 7, 18, 9, 30, tzinfo=UTC)


def make_update(
    text: str,
    *,
    update_id: int = 42,
    chat_id: int = 1,
    chat_type: str = "private",
    user_id: int = 1,
    message_time: datetime = MESSAGE_TIME,
) -> Update:
    return Update.model_validate(
        {
            "update_id": update_id,
            "message": {
                "message_id": update_id,
                "date": int(message_time.timestamp()),
                "chat": {"id": chat_id, "type": chat_type},
                "from": {
                    "id": user_id,
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


class FailingIngestionService:
    async def ingest(self, parse_result: BatchParseResult) -> BatchIngestionResult:
        del parse_result
        pytest.fail("short-circuited update reached batch ingestion")


class RecordingIngestionService:
    def __init__(self, result: BatchIngestionResult | None = None) -> None:
        self.result = result
        self.calls: list[BatchParseResult] = []

    async def ingest(self, parse_result: BatchParseResult) -> BatchIngestionResult:
        self.calls.append(parse_result)
        return self.result or BatchIngestionResult((), (), parse_result.rejected)


class FailingDatabaseIngestionService:
    async def ingest(self, parse_result: BatchParseResult) -> BatchIngestionResult:
        del parse_result
        raise SQLAlchemyError(
            "amount=98765 description=Секрет token=login-secret session=session-secret"
        )


class RecordingLoginService:
    def __init__(self) -> None:
        self.revoked_owners: list[int] = []
        self.issued_for: list[int] = []

    async def issue_login_token(self, telegram_user_id: int) -> str:
        self.issued_for.append(telegram_user_id)
        return "one-time-secret"

    async def revoke_all_sessions(self, telegram_user_id: int) -> None:
        self.revoked_owners.append(telegram_user_id)


def transaction(
    *,
    description: str,
    amount_kopecks: int,
    occurred_at: datetime,
    transaction_type: TransactionType,
    category_code: str,
    source_event_id: str,
) -> Transaction:
    return Transaction(
        owner=1,
        type=transaction_type,
        direction=TransactionDirection.NORMAL,
        amount_kopecks=amount_kopecks,
        occurred_at=occurred_at,
        description=description,
        source="telegram",
        source_event_id=source_event_id,
        category_code=category_code,
        category_source=CategorySource.RULES,
        category_confidence=95,
        needs_category_review=False,
    )


@pytest.mark.parametrize(
    ("chat_id", "chat_type", "user_id"),
    [
        (-100, "group", 1),
        (-101, "supergroup", 1),
        (-102, "channel", 1),
        (2, "private", 1),
        (2, "private", 2),
    ],
)
@pytest.mark.parametrize("text", ["/login", "/logout", "кофе 350"])
async def test_updates_outside_owner_private_chat_short_circuit_before_commands_parser_and_ingestion(
    chat_id: int,
    chat_type: str,
    user_id: int,
    text: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = RecordingBot()

    def fail_parser(*args: object, **kwargs: object) -> None:
        del args, kwargs
        pytest.fail("unauthorized update reached batch parser")

    monkeypatch.setattr("moneyflow.telegram.router.parse_batch_message", fail_parser)
    login_service = SimpleNamespace(
        issue_login_token=lambda *args: pytest.fail("unauthorized update reached login"),
        revoke_all_sessions=lambda *args: pytest.fail("unauthorized update reached logout"),
    )

    await handle_text_update(
        make_update(text, chat_id=chat_id, chat_type=chat_type, user_id=user_id),
        bot=bot,
        settings=Settings(authorized_telegram_user_id=1),
        owner_timezone="Europe/Moscow",
        ingestion_service=FailingIngestionService(),  # type: ignore[arg-type]
        login_service=login_service,  # type: ignore[arg-type]
    )

    assert bot.messages == []


@pytest.mark.parametrize("command", ["/login", "/logout", "/revoke_sessions"])
async def test_commands_short_circuit_before_batch_parser_and_ingestion(
    command: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = RecordingBot()
    login_service = RecordingLoginService()

    def fail_parser(*args: object, **kwargs: object) -> None:
        del args, kwargs
        pytest.fail("command reached batch parser")

    monkeypatch.setattr("moneyflow.telegram.router.parse_batch_message", fail_parser)

    await handle_text_update(
        make_update(command),
        bot=bot,
        settings=Settings(authorized_telegram_user_id=1, public_web_url="https://money.test"),
        owner_timezone="Europe/Moscow",
        ingestion_service=FailingIngestionService(),  # type: ignore[arg-type]
        login_service=login_service,  # type: ignore[arg-type]
    )

    if command == "/login":
        assert login_service.issued_for == [1]
        assert bot.messages == [(1, "https://money.test/login?token=one-time-secret")]
    else:
        assert login_service.revoked_owners == [1]
        assert bot.messages == [(1, "Все веб-сессии завершены.")]


async def test_parser_receives_exact_telegram_message_timestamp_timezone_update_and_line_ids() -> (
    None
):
    bot = RecordingBot()
    ingestion = RecordingIngestionService()

    await handle_text_update(
        make_update("кофе 350\nтакси 780", update_id=77),
        bot=bot,
        settings=Settings(authorized_telegram_user_id=1),
        owner_timezone="America/New_York",
        ingestion_service=ingestion,  # type: ignore[arg-type]
        login_service=RecordingLoginService(),  # type: ignore[arg-type]
    )

    parsed = ingestion.calls[0]
    assert [item.occurred_at for item in parsed.items] == [MESSAGE_TIME, MESSAGE_TIME]
    assert [item.line_number for item in parsed.items] == [1, 2]
    assert [item.source_event_id for item in parsed.items] == [
        "telegram:77:1",
        "telegram:77:2",
    ]


@pytest.mark.parametrize(
    ("count", "expected"),
    [
        (1, "1 операция"),
        (2, "2 операции"),
        (5, "5 операций"),
        (11, "11 операций"),
        (21, "21 операция"),
    ],
)
async def test_saved_summary_uses_russian_plural_forms(count: int, expected: str) -> None:
    rows = tuple(
        transaction(
            description=f"кофе {index}",
            amount_kopecks=35_000,
            occurred_at=MESSAGE_TIME,
            transaction_type=TransactionType.EXPENSE,
            category_code="expense.cafes",
            source_event_id=f"telegram:42:{index}",
        )
        for index in range(1, count + 1)
    )
    bot = RecordingBot()

    await handle_text_update(
        make_update("непонятно"),
        bot=bot,
        settings=Settings(authorized_telegram_user_id=1),
        owner_timezone="Europe/Moscow",
        ingestion_service=RecordingIngestionService(BatchIngestionResult(rows, (), ())),  # type: ignore[arg-type]
        login_service=RecordingLoginService(),  # type: ignore[arg-type]
    )

    assert f"Сохранено: {expected}" in bot.messages[0][1]


async def test_batch_summary_formats_dates_amount_signs_categories_rejections_and_duplicates() -> (
    None
):
    saved = transaction(
        description="кофе",
        amount_kopecks=35_000,
        occurred_at=datetime(2026, 7, 15, 9, tzinfo=UTC),
        transaction_type=TransactionType.EXPENSE,
        category_code="expense.cafes",
        source_event_id="telegram:42:2",
    )
    duplicate = transaction(
        description="зарплата",
        amount_kopecks=15_000_000,
        occurred_at=datetime(2026, 7, 16, 9, tzinfo=UTC),
        transaction_type=TransactionType.INCOME,
        category_code="income.salary",
        source_event_id="telegram:42:3",
    )
    bot = RecordingBot()

    await handle_text_update(
        make_update("15 июля\nкофе 350\nзарплата +150000\nнепонятно"),
        bot=bot,
        settings=Settings(authorized_telegram_user_id=1),
        owner_timezone="Europe/Moscow",
        ingestion_service=RecordingIngestionService(  # type: ignore[arg-type]
            BatchIngestionResult(
                (saved,),
                (duplicate,),
                # Preserve the actual parser rejection so original line and number are exercised.
                (),
            )
        ),
        login_service=RecordingLoginService(),  # type: ignore[arg-type]
    )

    # Injecting saved/duplicate statuses must not discard parser rejections.
    text = bot.messages[0][1]
    assert "Сохранено: 1 операция" in text
    assert "15 июля 2026" in text
    assert "−350,00 ₽ · Кафе и рестораны · кофе" in text
    assert "Ранее сохранено: 1 операция" in text
    assert "16 июля 2026" in text
    assert "+150 000,00 ₽ · Зарплата · зарплата" in text


async def test_batch_summary_lists_actual_parser_rejection_with_original_line() -> None:
    bot = RecordingBot()
    ingestion = RecordingIngestionService()

    await handle_text_update(
        make_update("15 июля\nкофе 350\n  непонятно  "),
        bot=bot,
        settings=Settings(authorized_telegram_user_id=1),
        owner_timezone="Europe/Moscow",
        ingestion_service=ingestion,  # type: ignore[arg-type]
        login_service=RecordingLoginService(),  # type: ignore[arg-type]
    )

    text = bot.messages[0][1]
    assert "Не распознано: 1 строка" in text
    assert "строка 3:   непонятно   — укажите сумму" in text


async def test_saved_summary_groups_non_contiguous_items_by_displayed_local_date() -> None:
    rows = (
        transaction(
            description="кофе",
            amount_kopecks=35_000,
            occurred_at=datetime(2026, 7, 15, 9, tzinfo=UTC),
            transaction_type=TransactionType.EXPENSE,
            category_code="expense.cafes",
            source_event_id="telegram:42:1",
        ),
        transaction(
            description="такси",
            amount_kopecks=78_000,
            occurred_at=datetime(2026, 7, 16, 9, tzinfo=UTC),
            transaction_type=TransactionType.EXPENSE,
            category_code="expense.transport",
            source_event_id="telegram:42:2",
        ),
        transaction(
            description="ужин",
            amount_kopecks=125_000,
            occurred_at=datetime(2026, 7, 15, 12, tzinfo=UTC),
            transaction_type=TransactionType.EXPENSE,
            category_code="expense.cafes",
            source_event_id="telegram:42:3",
        ),
    )
    bot = RecordingBot()

    await handle_text_update(
        make_update("кофе 350"),
        bot=bot,
        settings=Settings(authorized_telegram_user_id=1),
        owner_timezone="Europe/Moscow",
        ingestion_service=RecordingIngestionService(BatchIngestionResult(rows, (), ())),  # type: ignore[arg-type]
        login_service=RecordingLoginService(),  # type: ignore[arg-type]
    )

    text = bot.messages[0][1]
    assert text.count("15 июля 2026") == 1
    assert text.index("кофе") < text.index("ужин") < text.index("16 июля 2026")


async def test_summary_includes_only_first_20_result_lines_and_accurate_remaining_count() -> None:
    input_lines = [f"непонятная строка {'x' * index}" for index in range(1, 26)]
    bot = RecordingBot()

    await handle_text_update(
        make_update("\n".join(input_lines)),
        bot=bot,
        settings=Settings(authorized_telegram_user_id=1),
        owner_timezone="Europe/Moscow",
        ingestion_service=RecordingIngestionService(),  # type: ignore[arg-type]
        login_service=RecordingLoginService(),  # type: ignore[arg-type]
    )

    text = bot.messages[0][1]
    assert "Не распознано: 25 строк" in text
    assert f"строка 20: непонятная строка {'x' * 20} — укажите сумму" in text
    assert "строка 21:" not in text
    assert text.endswith("…и ещё 5")
    assert len(text) <= 4096


async def test_database_exception_sends_exact_generic_message_without_leaking_exception(
    caplog: pytest.LogCaptureFixture,
) -> None:
    bot = RecordingBot()

    with caplog.at_level("INFO", logger="moneyflow.telegram.router"):
        await handle_text_update(
            make_update("Секрет 98765"),
            bot=bot,
            settings=Settings(authorized_telegram_user_id=1),
            owner_timezone="Europe/Moscow",
            ingestion_service=FailingDatabaseIngestionService(),  # type: ignore[arg-type]
            login_service=RecordingLoginService(),  # type: ignore[arg-type]
        )

    assert bot.messages == [
        (
            1,
            "Не удалось сохранить операции из-за временной ошибки. Попробуйте ещё раз позже.",
        )
    ]
    rendered = " ".join(record.getMessage() for record in caplog.records)
    for private in ("98765", "Секрет", "login-secret", "session-secret"):
        assert private not in rendered


async def test_factory_created_category_provider_is_closed_in_async_dependency_finally(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Provider:
        def __init__(self) -> None:
            self.close_calls = 0

        async def aclose(self) -> None:
            self.close_calls += 1

    provider = Provider()
    factory_calls = 0

    async def classify(
        items: object,
        examples: object,
    ) -> dict[str, object]:
        del items, examples
        return {}

    provider.classify = classify  # type: ignore[attr-defined]

    def factory(settings: Settings) -> Provider:
        nonlocal factory_calls
        del settings
        factory_calls += 1
        return provider

    monkeypatch.setattr(
        "moneyflow.telegram.webhook.build_category_provider",
        factory,
    )
    dependency = get_category_provider(Settings(openai_api_key="not-a-real-secret"))

    lazy_provider = await anext(dependency)
    assert factory_calls == 0

    await lazy_provider.classify(
        (CategoryInput("1", "неизвестное", TransactionType.EXPENSE),),
        {},
    )
    await dependency.aclose()

    assert factory_calls == 1
    assert provider.close_calls == 1


async def test_batch_ingestion_dependency_wires_owner_scoped_repositories_and_is_overrideable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = object()
    provider = object()
    correction_repository = object()
    transaction_repository = object()
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "moneyflow.telegram.webhook.CategoryCorrectionRepository",
        lambda received_session: (
            captured.setdefault("correction_session", received_session),
            correction_repository,
        )[1],
    )
    monkeypatch.setattr(
        "moneyflow.telegram.webhook.TransactionRepository",
        lambda received_session: (
            captured.setdefault("transaction_session", received_session),
            transaction_repository,
        )[1],
    )

    def resolver_factory(**kwargs: object) -> object:
        captured["resolver_kwargs"] = kwargs
        return "resolver"

    def service_factory(*args: object, **kwargs: object) -> object:
        captured["service_args"] = args
        captured["service_kwargs"] = kwargs
        return "service"

    monkeypatch.setattr("moneyflow.telegram.webhook.CategoryResolver", resolver_factory)
    monkeypatch.setattr("moneyflow.telegram.webhook.BatchIngestionService", service_factory)

    result = await get_batch_ingestion_service(
        session,  # type: ignore[arg-type]
        Settings(authorized_telegram_user_id=991),
        provider,  # type: ignore[arg-type]
    )

    assert result == "service"
    assert captured == {
        "correction_session": session,
        "transaction_session": session,
        "resolver_kwargs": {
            "owner": 991,
            "correction_repository": correction_repository,
            "provider": provider,
        },
        "service_args": (session, 991),
        "service_kwargs": {
            "resolver": "resolver",
            "repository": transaction_repository,
        },
    }
