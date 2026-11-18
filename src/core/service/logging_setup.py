"""JSON logging setup for deterministic machine-readable logs."""

from __future__ import annotations

import json
import logging
import tempfile
from collections import deque
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from threading import Lock

_LOG_BUFFER: deque[dict] = deque(maxlen=2000)
_LOG_LOCK = Lock()
MAX_LOG_FILE_BYTES = 10 * 1024 * 1024
DEFAULT_LOG_FILE_PATH = Path("data") / "logs" / "log.txt"


class JsonFormatter(logging.Formatter):
    """Emit log records as compact JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": _record_timestamp(record),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }

        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=True)


class InMemoryLogHandler(logging.Handler):
    """Collect recent logs for in-app log viewer."""

    def emit(self, record: logging.LogRecord) -> None:
        payload = {
            "ts": _record_timestamp(record),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        with _LOG_LOCK:
            _LOG_BUFFER.append(payload)


def _record_timestamp(record: logging.LogRecord) -> str:
    # Every handler for a LogRecord must emit the same timestamp; otherwise the
    # backend cannot reliably deduplicate file-backed and in-memory copies.
    return datetime.fromtimestamp(record.created, timezone.utc).isoformat()


def get_recent_logs(limit: int = 200) -> list[dict]:
    safe_limit = max(1, min(1000, int(limit)))
    with _LOG_LOCK:
        items = list(_LOG_BUFFER)
    return items[-safe_limit:]


def configure_logging(
    level: str,
    log_path: Path | str = DEFAULT_LOG_FILE_PATH,
    max_bytes: int = MAX_LOG_FILE_BYTES,
) -> None:
    root = logging.getLogger()
    for existing_handler in list(root.handlers):
        root.removeHandler(existing_handler)
        try:
            existing_handler.close()
        except Exception:
            pass

    formatter = JsonFormatter()

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    resolved_log_path = _resolve_writable_log_path(Path(log_path))
    file_handler = RotatingFileHandler(
        resolved_log_path,
        maxBytes=max_bytes,
        backupCount=1,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    root.addHandler(handler)
    root.addHandler(file_handler)
    root.addHandler(InMemoryLogHandler())
    root.setLevel(level)


def _resolve_writable_log_path(preferred_path: Path) -> Path:
    candidates = [
        preferred_path,
        Path("data") / "logs" / "log.txt",
        Path.home() / ".lanlauncherng" / "logs" / "log.txt",
        Path(tempfile.gettempdir()) / "lanlauncherng" / "logs" / "log.txt",
    ]
    for candidate in candidates:
        try:
            candidate.parent.mkdir(parents=True, exist_ok=True)
            with candidate.open("a", encoding="utf-8"):
                pass
            return candidate
        except (OSError, PermissionError):
            continue
    return preferred_path


def set_log_level(level: str) -> None:
    logging.getLogger().setLevel(level.upper())
