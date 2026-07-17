import json
import logging
from types import SimpleNamespace

import pytest
from aiogram.types import Update
from fastapi import HTTPException

from moneyflow.config import Settings
from moneyflow.logging import JsonFormatter, configure_logging
from moneyflow.telegram.router import handle_text_update
from moneyflow.telegram.webhook import receive_webhook


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
