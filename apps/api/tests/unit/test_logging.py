import json
import logging
from io import StringIO
from types import SimpleNamespace

import pytest
from aiogram.types import Update
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from moneyflow.config import Settings, get_settings
from moneyflow.db import engine
from moneyflow.logging import JsonFormatter, configure_logging
from moneyflow.main import create_app
from moneyflow.telegram.router import handle_text_update
from moneyflow.telegram.webhook import get_bot, receive_webhook


class CapturingHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


class FakeBot:
    async def send_message(self, chat_id: int, text: str) -> None:
        del chat_id, text


class FakeTransactionService:
    async def create(self, command: object) -> SimpleNamespace:
        del command
        return SimpleNamespace(amount_kopecks=35000, description="Coffee")


def make_update(*, user_id: int, text: str, update_id: int = 42) -> Update:
    return Update.model_validate(
        {
            "update_id": update_id,
            "message": {
                "message_id": update_id,
                "date": 1_768_651_200,
                "chat": {"id": user_id, "type": "private"},
                "from": {
                    "id": user_id,
                    "is_bot": False,
                    "first_name": "Test",
                },
                "text": text,
            },
        }
    )


def capture_logger(
    name: str, monkeypatch: pytest.MonkeyPatch
) -> CapturingHandler:
    logger = logging.getLogger(name)
    handler = CapturingHandler()
    monkeypatch.setattr(logger, "handlers", [handler])
    monkeypatch.setattr(logger, "propagate", False)
    monkeypatch.setattr(logger, "level", logging.INFO)
    return handler


def test_json_formatter_omits_every_non_allowlisted_field() -> None:
    record = logging.makeLogRecord(
        {
            "name": "moneyflow.telegram",
            "levelno": logging.INFO,
            "levelname": "INFO",
            "msg": "raw private message: coffee 350",
            "event": "transaction_created",
            "request_id": "request-123",
            "source": "telegram",
            "outcome": "accepted",
            "latency_ms": 12,
            "error_type": None,
            "amount_kopecks": 35000,
            "description": "Coffee",
            "telegram_text": "coffee 350",
            "token": "login-secret",
        }
    )

    payload = json.loads(JsonFormatter().format(record))

    assert set(payload) == {
        "timestamp",
        "level",
        "logger",
        "event",
        "request_id",
        "source",
        "outcome",
        "latency_ms",
        "error_type",
    }
    assert payload["event"] == "transaction_created"
    rendered = json.dumps(payload)
    assert "35000" not in rendered
    assert "Coffee" not in rendered
    assert "coffee 350" not in rendered
    assert "login-secret" not in rendered


def test_json_formatter_omits_absent_optional_fields_and_message() -> None:
    record = logging.makeLogRecord(
        {
            "name": "moneyflow.telegram",
            "levelno": logging.WARNING,
            "levelname": "WARNING",
            "msg": "this must not be emitted",
            "event": "parser_rejected",
        }
    )

    payload = json.loads(JsonFormatter().format(record))

    assert set(payload) == {"timestamp", "level", "logger", "event"}
    assert payload["level"] == "WARNING"
    assert "this must not be emitted" not in json.dumps(payload)


def test_configure_logging_installs_one_json_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    moneyflow_logger = logging.getLogger("moneyflow")
    monkeypatch.setattr(moneyflow_logger, "handlers", [])

    configure_logging()
    configure_logging()

    installed_handlers = [
        handler
        for handler in moneyflow_logger.handlers
        if getattr(handler, "name", None) == "moneyflow-json"
    ]
    assert len(installed_handlers) == 1
    assert isinstance(installed_handlers[0].formatter, JsonFormatter)
    assert moneyflow_logger.propagate is False


def test_database_engine_hides_statement_parameters() -> None:
    assert engine.sync_engine.hide_parameters is True


def test_configure_logging_sanitizes_root_and_uvicorn_handlers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (None, "uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        monkeypatch.setattr(logger, "handlers", [logging.StreamHandler()])
        if name is not None:
            monkeypatch.setattr(logger, "propagate", True)

    configure_logging()

    for name in (None, "uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        assert len(logger.handlers) == 1
        assert isinstance(logger.handlers[0].formatter, JsonFormatter)
        if name is not None:
            assert logger.propagate is False
    assert logging.getLogger("uvicorn.access").disabled is True


async def test_unhandled_exception_is_generic_and_logs_no_private_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_app()
    output = StringIO()
    handler = logging.StreamHandler(output)
    handler.setFormatter(JsonFormatter())
    moneyflow_logger = logging.getLogger("moneyflow")
    monkeypatch.setattr(moneyflow_logger, "handlers", [handler])
    monkeypatch.setattr(moneyflow_logger, "propagate", False)

    @app.get("/fault")
    async def fault() -> None:
        raise RuntimeError(
            "amount=98765 description=Секрет message=Скрытая-покупка token=login-secret"
        )

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/fault")

    assert response.status_code == 500
    assert response.json() == {"detail": "internal server error"}
    rendered = output.getvalue()
    assert "internal_error" in rendered
    assert "RuntimeError" in rendered
    for private_field in ("amount", "description", "message", "token"):
        assert private_field not in rendered
    for private_value in ("98765", "Секрет", "Скрытая-покупка", "login-secret"):
        assert private_value not in rendered


async def test_malformed_telegram_update_is_sanitized_in_response_and_logs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: Settings(
        telegram_webhook_secret="expected"
    )
    app.dependency_overrides[get_bot] = lambda: FakeBot()
    output = StringIO()
    handler = logging.StreamHandler(output)
    handler.setFormatter(JsonFormatter())
    moneyflow_logger = logging.getLogger("moneyflow")
    monkeypatch.setattr(moneyflow_logger, "handlers", [handler])
    monkeypatch.setattr(moneyflow_logger, "propagate", False)
    private_values = ("98765", "Секрет", "Скрытая-покупка", "login-secret")
    payload = {
        "update_id": 44,
        "message": {
            "message_id": 44,
            "date": 1_768_651_200,
            "chat": {"id": 1, "type": "private"},
            "from": {"id": 1, "is_bot": False, "first_name": "Owner"},
            "text": {
                "amount": private_values[0],
                "description": private_values[1],
                "message": private_values[2],
                "token": private_values[3],
            },
        },
    }

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/telegram/webhook",
            headers={"X-Telegram-Bot-Api-Secret-Token": "expected"},
            json=payload,
        )

    assert response.status_code == 422
    assert response.json() == {"detail": "invalid request"}
    rendered = output.getvalue()
    assert "request_rejected" in rendered
    for private_field in ("amount", "description", "message", "token"):
        assert private_field not in rendered
    for private_value in private_values:
        assert private_value not in rendered


async def test_wrong_webhook_secret_logs_only_rejection_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handler = capture_logger("moneyflow.telegram.webhook", monkeypatch)

    with pytest.raises(HTTPException):
        await receive_webhook(
            payload={"private": "telegram text"},
            bot=FakeBot(),
            settings=Settings(telegram_webhook_secret="expected"),
            transaction_service=FakeTransactionService(),  # type: ignore[arg-type]
            login_service=object(),  # type: ignore[arg-type]
            secret_token="wrong",
        )

    assert [record.event for record in handler.records] == ["webhook_rejected"]
    assert "telegram text" not in JsonFormatter().format(handler.records[0])


@pytest.mark.parametrize(
    ("update", "expected_event"),
    [
        (make_update(user_id=2, text="private 350"), "foreign_user_rejected"),
        (make_update(user_id=1, text="not-an-expense"), "parser_rejected"),
        (make_update(user_id=1, text="coffee 350"), "transaction_created"),
    ],
)
async def test_telegram_router_logs_named_events_without_message_text(
    update: Update,
    expected_event: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handler = capture_logger("moneyflow.telegram.router", monkeypatch)

    await handle_text_update(
        update,
        bot=FakeBot(),
        settings=Settings(authorized_telegram_user_id=1),
        transaction_service=FakeTransactionService(),  # type: ignore[arg-type]
        login_service=object(),  # type: ignore[arg-type]
    )

    assert [record.event for record in handler.records] == [expected_event]
    rendered = JsonFormatter().format(handler.records[0])
    assert update.message is not None
    assert update.message.text not in rendered
