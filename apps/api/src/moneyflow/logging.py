import json
import logging
from datetime import UTC, datetime


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


def configure_logging() -> None:
    """Install exactly one privacy-safe handler for MoneyFlow application logs."""

    logger = logging.getLogger("moneyflow")
    handler = next(
        (candidate for candidate in logger.handlers if candidate.name == "moneyflow-json"),
        None,
    )
    if handler is None:
        handler = logging.StreamHandler()
        handler.name = "moneyflow-json"
    handler.setFormatter(JsonFormatter())
    logger.handlers = [handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False
