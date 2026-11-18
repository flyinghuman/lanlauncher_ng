"""Tests for SQLite migration bootstrap."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.core.db.store import open_database


class MigrationBootstrapTests(unittest.TestCase):
    def test_bootstrap_creates_expected_tables(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "app.db"
            db = open_database(str(db_path))

            tables = {
                row[0]
                for row in db.connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            db.connection.close()

            self.assertIn("schema_migrations", tables)
            self.assertIn("app_meta", tables)
            self.assertIn("games", tables)
            self.assertIn("install_state", tables)
            self.assertIn("genres", tables)
            self.assertIn("tools", tables)
            self.assertIn("game_catalog", tables)
            self.assertIn("sync_state", tables)
            self.assertIn("extra_sync_items", tables)
            self.assertIn("game_launch_settings", tables)
            self.assertIn("game_index_catalog_entries", tables)

    def test_bootstrap_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "app.db"
            db1 = open_database(str(db_path))
            db1.connection.close()

            db2 = open_database(str(db_path))
            applied_versions = db2.connection.execute(
                "SELECT COUNT(*) FROM schema_migrations"
            ).fetchone()[0]
            extra_sync_columns = {
                str(row[1])
                for row in db2.connection.execute(
                    "PRAGMA table_info(extra_sync_items)"
                ).fetchall()
            }
            game_catalog_columns = {
                str(row[1])
                for row in db2.connection.execute(
                    "PRAGMA table_info(game_catalog)"
                ).fetchall()
            }
            launch_settings_columns = {
                str(row[1])
                for row in db2.connection.execute(
                    "PRAGMA table_info(game_launch_settings)"
                ).fetchall()
            }
            db2.connection.close()

            self.assertEqual(applied_versions, 14)
            self.assertIn("is_game_provider", extra_sync_columns)
            self.assertIn("game_provider_type", extra_sync_columns)
            self.assertIn("has_game_db", extra_sync_columns)
            self.assertIn("is_seeded_default", extra_sync_columns)
            self.assertIn("packed_image_path", extra_sync_columns)
            self.assertIn("packed_image_password", extra_sync_columns)
            self.assertIn("game_provider_type", game_catalog_columns)
            self.assertIn("linux_leave_terminal_open", launch_settings_columns)


if __name__ == "__main__":
    unittest.main()
