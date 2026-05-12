import json
import logging
from datetime import datetime, UTC

from app.core.story_logger import get_story_log_router


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if hasattr(record, "extra_payload"):
            payload["extra"] = record.extra_payload
        return json.dumps(payload, ensure_ascii=False)


def configure_logging() -> None:
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(JsonFormatter())

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.handlers.clear()
    root_logger.addHandler(stream_handler)
    root_logger.addHandler(get_story_log_router())


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
