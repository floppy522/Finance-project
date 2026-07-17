import json
import logging
from datetime import UTC, datetime

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.types import ASGIApp, Message, Receive, Scope, Send


_OPTIONAL_FIELDS = (
    "event",
    "request_id",
    "source",
    "outcome",
    "latency_ms",
    "error_type",
)


class JsonFormatter(logging.Formatter):
    """Format a log record without copying arbitrary record attributes."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat().replace(
                "+00:00", "Z"
            ),
            "level": record.levelname,
            "logger": record.name,
        }
        for field in _OPTIONAL_FIELDS:
            if hasattr(record, field):
                payload[field] = getattr(record, field)
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _json_handler(name: str) -> logging.Handler:
    handler = logging.StreamHandler()
    handler.name = name
    handler.setFormatter(JsonFormatter())
    return handler


def configure_logging() -> None:
    """Replace application and server handlers with privacy-safe JSON output."""

    root_logger = logging.getLogger()
    root_logger.handlers = [_json_handler("root-json")]
    root_logger.setLevel(logging.INFO)

    for name in ("moneyflow", "uvicorn", "uvicorn.error"):
        logger = logging.getLogger(name)
        logger.handlers = [_json_handler(f"{name}-json")]
        logger.setLevel(logging.INFO)
        logger.propagate = False

    access_logger = logging.getLogger("uvicorn.access")
    access_logger.handlers = [_json_handler("uvicorn.access-json")]
    access_logger.propagate = False
    access_logger.disabled = True


class PrivacyExceptionMiddleware:
    """Keep uncaught HTTP exceptions out of Uvicorn's traceback logger."""

    def __init__(self, app: ASGIApp) -> None:
        self._app = app
        self._logger = logging.getLogger("moneyflow.exceptions")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        response_started = False

        async def privacy_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self._app(scope, receive, privacy_send)
        except Exception as error:
            if scope["type"] != "http":
                raise
            self._logger.error(
                "internal_error",
                extra={
                    "event": "internal_error",
                    "error_type": type(error).__name__,
                },
            )
            if not response_started:
                response = JSONResponse(
                    status_code=500,
                    content={"detail": "internal server error"},
                )
                await response(scope, receive, send)


def install_exception_boundary(app: FastAPI) -> None:
    app.add_middleware(PrivacyExceptionMiddleware)

    async def invalid_request_handler(
        request: Request,
        error: Exception,
    ) -> JSONResponse:
        del request
        logging.getLogger("moneyflow.exceptions").warning(
            "request_rejected",
            extra={
                "event": "request_rejected",
                "error_type": type(error).__name__,
            },
        )
        return JSONResponse(
            status_code=422,
            content={"detail": "invalid request"},
        )

    app.add_exception_handler(RequestValidationError, invalid_request_handler)
    app.add_exception_handler(ValidationError, invalid_request_handler)
