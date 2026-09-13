"""Privacy-conscious application logging."""
from __future__ import annotations

import logging
from pathlib import Path


class SensitiveDataFilter(logging.Filter):
    """Avoid writing common credential fields to logs."""

    _blocked = ("password", "token", "api_key", "apikey", "secret", "authorization")

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage().lower()
        if any(item in message for item in self._blocked):
            record.msg = "Sensitive data was omitted from the log"
            record.args = ()
        return True


def configure_logging(log_directory: Path) -> logging.Logger:
    log_directory.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("job_assistant")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    handler = logging.FileHandler(log_directory / "application.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    handler.addFilter(SensitiveDataFilter())
    logger.addHandler(handler)
    return logger
