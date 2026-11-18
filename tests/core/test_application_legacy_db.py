"""Tests for legacy DB path resolution in Application."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from src.core.config.loader import AppConfig
from src.core.db.store import open_database
from src.core.service.app import Application


class ApplicationLegacyDbPathTests(unittest.TestCase):
    def test_prefers_configured_legacy_db_path_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            configured = root / "data" / "legacy" / "game.db"
            configured.parent.mkdir(parents=True, exist_ok=True)
            configured.write_text("stub", encoding="utf-8")

            app = Application(AppConfig(bind_port=0, legacy_db_path=str(configured)))
            try:
                resolved = app._resolve_legacy_db_path()  # noqa: SLF001 private helper
            finally:
                app._server.server_close()  # noqa: SLF001 explicit cleanup for bound test server
            self.assertEqual(resolved, str(configured))

    def test_falls_back_to_old_game_db_for_dev_when_configured_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old_dir = root / "old"
            old_dir.mkdir(parents=True, exist_ok=True)
            fallback = old_dir / "game.db"
            fallback.write_text("stub", encoding="utf-8")

            app = Application(
                AppConfig(bind_port=0, legacy_db_path="data/legacy/game.db")
            )
            previous_cwd = Path.cwd()
            resolved_abs = ""
            try:
                os.chdir(root)
                resolved = app._resolve_legacy_db_path()  # noqa: SLF001 private helper
                resolved_abs = str(Path(resolved).resolve())
            finally:
                os.chdir(previous_cwd)
                app._server.server_close()  # noqa: SLF001 explicit cleanup for bound test server
            self.assertEqual(resolved_abs, str(fallback.resolve()))

    def test_runtime_update_db_path_uses_effective_library_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            library = root / "library"
            app = Application(AppConfig(bind_port=0, library_path=str(library)))
            try:
                resolved = app._resolve_runtime_update_db_path()  # noqa: SLF001 private helper
            finally:
                app._server.server_close()  # noqa: SLF001 explicit cleanup for bound test server
            expected = library / "eti_launcher" / "update" / "game.db"
            self.assertEqual(str(resolved), str(expected))

    def test_runtime_update_db_signature_changes_when_file_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            library = root / "library"
            update_dir = library / "eti_launcher" / "update"
            update_dir.mkdir(parents=True, exist_ok=True)
            update_db = update_dir / "game.db"
            update_db.write_text("v1", encoding="utf-8")

            app = Application(AppConfig(bind_port=0, library_path=str(library)))
            try:
                sig1 = app._runtime_update_db_signature_for_path(update_db)  # noqa: SLF001 private helper
                update_db.write_text("version-two", encoding="utf-8")
                sig2 = app._runtime_update_db_signature_for_path(update_db)  # noqa: SLF001 private helper
            finally:
                app._server.server_close()  # noqa: SLF001 explicit cleanup for bound test server

            self.assertIsNotNone(sig1)
            self.assertIsNotNone(sig2)
            self.assertNotEqual(sig1, sig2)

    def test_runtime_update_db_sources_include_enabled_provider_with_game_db(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "app.db"
            app = Application(
                AppConfig(
                    bind_port=0,
                    db_path=str(db_path),
                    library_path=str(root / "library"),
                )
            )
            app._state.database = open_database(str(db_path))  # noqa: SLF001
            try:
                with app._state.database.connection:  # noqa: SLF001
                    app._state.database.connection.execute(  # noqa: SLF001
                        """
                        INSERT INTO extra_sync_items(
                            game_id, game_key, title_en, title_de, sync_enabled, is_game_provider, has_game_db, updated_at
                        ) VALUES ('provider_a', 'KEY', 'A', 'A', 1, 1, 1, datetime('now'))
                        """
                    )
                sources = app._resolve_runtime_update_db_sources()  # noqa: SLF001 private helper
            finally:
                if app._state.database is not None:  # noqa: SLF001
                    app._state.database.connection.close()  # noqa: SLF001
                app._server.server_close()  # noqa: SLF001
            source_ids = [item[0] for item in sources]
            self.assertIn("eti_launcher", source_ids)
            self.assertIn("provider_a", source_ids)


if __name__ == "__main__":
    unittest.main()
