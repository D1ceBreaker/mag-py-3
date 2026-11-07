import json
import logging
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from valutatrade_hub.infra.settings import SettingsLoader


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        event = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
            **getattr(record, "event", {}),
        }
        return json.dumps(event, ensure_ascii=False, default=str)


class TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.fromtimestamp(record.created, UTC).isoformat()
        context = " ".join(
            f"{key}={value!r}" for key, value in getattr(record, "event", {}).items()
        )
        return (
            f"{record.levelname} {timestamp} {record.getMessage()} {context}".rstrip()
        )


def configure_logging() -> None:
    settings = SettingsLoader()
    directory = Path(str(settings.get("log_dir"))).expanduser()
    directory.mkdir(parents=True, exist_ok=True)
    formatter = (
        JsonFormatter() if settings.get("log_format") == "json" else TextFormatter()
    )
    for name, filename in (("actions", "actions.log"), ("parser", "parser.log")):
        logger = logging.getLogger(f"valutatrade.{name}")
        for old_handler in logger.handlers[:]:
            old_handler.close()
            logger.removeHandler(old_handler)
        handler = RotatingFileHandler(
            directory / filename,
            maxBytes=int(settings.get("log_max_bytes")),
            backupCount=int(settings.get("log_backup_count")),
            encoding="utf-8",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
