from __future__ import annotations

import json
import logging
import os
import tempfile
import unittest
from pathlib import Path

from src.core.service.logging_setup import (
    InMemoryLogHandler,
    JsonFormatter,
    MAX_LOG_FILE_BYTES,
    get_recent_logs,
    configure_logging,
)


class LoggingSetupTests(unittest.TestCase):
    def setUp(self) -> None:
        self._root = logging.getLogger()
        self._original_handlers = list(self._root.handlers)
        self._original_level = self._root.level

    def tearDown(self) -> None:
        self._close_active_handlers()
        for handler in self._original_handlers:
            self._root.addHandler(handler)
        self._root.setLevel(self._original_level)

    def _close_active_handlers(self) -> None:
        for handler in list(self._root.handlers):
            self._root.removeHandler(handler)
            try:
                handler.close()
            except Exception:
                pass

    def test_configure_logging_writes_to_disk(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "logs" / "log.txt"

            configure_logging("INFO", log_path=log_path)
            logging.getLogger("tests.logging").info("file logging smoke test")
            for handler in logging.getLogger().handlers:
                handler.flush()

            self.assertTrue(log_path.exists())
            content = log_path.read_text(encoding="utf-8")
            self.assertIn("file logging smoke test", content)
            self._close_active_handlers()

    def test_configure_logging_uses_ten_mb_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "logs" / "log.txt"

            configure_logging("INFO", log_path=log_path)
            file_handlers = [
                handler
                for handler in logging.getLogger().handlers
                if hasattr(handler, "maxBytes")
            ]
            self.assertTrue(file_handlers, "missing rotating file handler")
            self.assertEqual(file_handlers[0].maxBytes, MAX_LOG_FILE_BYTES)
            self._close_active_handlers()

    def test_handlers_use_record_timestamp_for_deduplication(self) -> None:
        record = logging.LogRecord(
            name="tests.logging",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="same record",
            args=(),
            exc_info=None,
        )
        formatter_payload = json.loads(JsonFormatter().format(record))
        handler = InMemoryLogHandler()
        handler.emit(record)
        memory_payload = get_recent_logs(1)[0]

        self.assertEqual(formatter_payload["ts"], memory_payload["ts"])
        self.assertEqual(formatter_payload["msg"], memory_payload["msg"])

    @unittest.skipUnless(os.name == "posix", "Permission-path test uses Linux /proc")
    def test_configure_logging_falls_back_when_primary_path_unwritable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            preferred = Path("/proc/lanlauncherng/log.txt")
            fallback = Path(temp_dir) / "data" / "logs" / "log.txt"
            cwd = Path.cwd()
            try:
                os.chdir(temp_dir)
                configure_logging("INFO", log_path=preferred)
                logging.getLogger("tests.logging").info("fallback logging smoke test")
                for handler in logging.getLogger().handlers:
                    handler.flush()
                self.assertTrue(fallback.exists())
                self.assertIn(
                    "fallback logging smoke test",
                    fallback.read_text(encoding="utf-8"),
                )
            finally:
                os.chdir(cwd)
                self._close_active_handlers()


if __name__ == "__main__":
    unittest.main()
