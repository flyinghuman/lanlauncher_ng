"""Tests for DB backup/rollback helpers."""

from __future__ import annotations

import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from src.core.db.rollback import (
    create_db_backup,
    latest_db_backup,
    list_db_backups,
    restore_db_backup,
)


class DbRollbackTests(unittest.TestCase):
    def _write_schema_db(self, db_path: Path, schema_version: int) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path)
        try:
            with conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS schema_migrations (
                        version INTEGER PRIMARY KEY,
                        applied_at TEXT NOT NULL
                    );
                    """
                )
                conn.execute("DELETE FROM schema_migrations")
                conn.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, datetime('now'))",
                    (schema_version,),
                )
        finally:
            conn.close()

    def test_create_and_restore_backup_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "data" / "lanlauncher.db"
            self._write_schema_db(db_path, schema_version=3)

            backup_path = create_db_backup(str(db_path), app_version="0.3.2")
            self.assertIsNotNone(backup_path)
            assert backup_path is not None
            self.assertTrue(backup_path.exists())

            self._write_schema_db(db_path, schema_version=7)
            restore_db_backup(str(db_path), str(backup_path))
            backups = list_db_backups(str(db_path))
            self.assertTrue(backups)
            self.assertEqual(backups[0]["schema_version"], 3)
            self.assertEqual(backups[0]["app_version"], "0.3.2")

    def test_latest_backup_returns_newest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "data" / "lanlauncher.db"
            self._write_schema_db(db_path, schema_version=5)

            first = create_db_backup(str(db_path))
            time.sleep(1.1)
            self._write_schema_db(db_path, schema_version=7)
            second = create_db_backup(str(db_path))

            self.assertIsNotNone(first)
            self.assertIsNotNone(second)
            latest = latest_db_backup(str(db_path))
            self.assertEqual(latest, second)
            latest_for_schema5 = latest_db_backup(str(db_path), target_schema_version=5)
            self.assertEqual(latest_for_schema5, first)

    def test_latest_backup_returns_none_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "data" / "lanlauncher.db"
            self.assertIsNone(latest_db_backup(str(db_path)))


if __name__ == "__main__":
    unittest.main()
