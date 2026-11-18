"""Tests for delete game action in Application."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from src.core.catalog.repository import CatalogRepository
from src.core.config.loader import AppConfig
from src.core.db.store import open_database
from src.core.service.app import Application
from src.core.service.settings_store import UserSettings


class _LinuxPlatform:
    def platform_name(self) -> str:
        return "linux"


class _SyncProvider:
    def __init__(self, ok: bool = True, detail: str = "ok") -> None:
        self.ok = ok
        self.detail = detail
        self.removed: list[str] = []
        self.paused: list[str] = []

    def remove_folder_sync(self, folder_path: str) -> tuple[bool, str]:
        self.removed.append(folder_path)
        return self.ok, self.detail

    def pause_folder_sync(self, folder_path: str) -> tuple[bool, str]:
        self.paused.append(folder_path)
        return self.ok, "ouisync_repository_paused"

    def start(self):  # pragma: no cover - unused
        raise NotImplementedError

    def stop(self):  # pragma: no cover - unused
        raise NotImplementedError

    def status(self):  # pragma: no cover - unused
        raise NotImplementedError

    def metrics(self):  # pragma: no cover - unused
        raise NotImplementedError

    def ensure_folder_synced(
        self, folder_path: str, secret: str
    ):  # pragma: no cover - unused
        _ = folder_path
        _ = secret
        raise NotImplementedError

    def folder_sync_status(self, folder_path: str):  # pragma: no cover - unused
        _ = folder_path
        raise NotImplementedError


class ApplicationGameDeleteTests(unittest.TestCase):
    def _create_runtime_update_db(
        self,
        path: Path,
        *,
        games: list[tuple[str, str, str]] | None = None,
        discarded: list[tuple[str, str]] | None = None,
    ) -> None:
        conn = sqlite3.connect(path)
        try:
            conn.execute(
                "CREATE TABLE genre (genre_id INTEGER PRIMARY KEY, genre_en TEXT, genre_de TEXT)"
            )
            conn.execute(
                """
                CREATE TABLE games (
                    game_id TEXT PRIMARY KEY,
                    game_title TEXT,
                    game_key TEXT,
                    game_release TEXT,
                    game_publisher TEXT,
                    game_size REAL,
                    game_readme_en TEXT,
                    game_readme_de TEXT,
                    game_maxplayers TEXT,
                    game_master_req INTEGER,
                    genre_id INTEGER,
                    game_version TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE tools (
                    tool_id TEXT PRIMARY KEY,
                    tool_name TEXT,
                    tool_key TEXT,
                    tool_maintainer TEXT,
                    tool_size REAL,
                    tool_readme_en TEXT,
                    tool_readme_de TEXT,
                    tool_disabled INTEGER
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE discarded (
                    game_id TEXT NOT NULL,
                    game_key TEXT NOT NULL
                )
                """
            )
            for game_id, game_title, game_key in games or []:
                conn.execute(
                    """
                    INSERT INTO games(
                        game_id, game_title, game_key, game_release, game_publisher, game_size,
                        game_readme_en, game_readme_de, game_maxplayers, game_master_req, genre_id, game_version
                    )
                    VALUES (?, ?, ?, '', '', 0, '', '', '', 0, NULL, '1.0')
                    """,
                    (game_id, game_title, game_key),
                )
            for game_id, game_key in discarded or []:
                conn.execute(
                    "INSERT INTO discarded(game_id, game_key) VALUES (?, ?)",
                    (game_id, game_key),
                )
            conn.commit()
        finally:
            conn.close()

    def test_delete_game_removes_sync_and_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = open_database(str(root / "app.db"))
            with db.connection:
                db.connection.execute(
                    """
                    INSERT INTO game_catalog(id, title_en, title_de, key, version)
                    VALUES ('demo', 'Demo', 'Demo', 'KEY', '1.0')
                    """
                )
            repo = CatalogRepository(db.connection)
            repo.set_install_state("demo", "installed", "1.0")
            folder = root / "LAN" / "demo"
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "demo.eti").write_bytes(b"data")

            app = Application(AppConfig(bind_port=0))
            app._state.repository = repo  # noqa: SLF001
            app._state.platform_adapter = _LinuxPlatform()  # noqa: SLF001
            app._state.user_settings = UserSettings(  # noqa: SLF001
                nickname="Tester",
                theme="dark",
                log_level="WARNING",
                auto_start_sync=True,
                library_path_initialized=True,
                windows_game_drive_letter="D",
                linux_install_path=str(root / "LAN"),
            )
            provider = _SyncProvider(ok=True, detail="ok")
            app._state.sync_provider = provider  # noqa: SLF001
            try:
                result = app._game_action("demo", "delete")  # noqa: SLF001
                self.assertTrue(result["ok"])
                self.assertEqual(result["message"], "deleted")
                self.assertFalse(folder.exists())
                self.assertTrue(
                    any(
                        path.replace("\\", "/").endswith("/demo")
                        for path in provider.removed
                    )
                )
                game = repo.get_game("demo", locale="en")
                self.assertIsNotNone(game)
                assert game is not None
                self.assertEqual(game["install_state"], "missing")
            finally:
                app._server.server_close()  # noqa: SLF001
                db.connection.close()

    def test_delete_game_fails_when_sync_remove_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = open_database(str(root / "app.db"))
            with db.connection:
                db.connection.execute(
                    """
                    INSERT INTO game_catalog(id, title_en, title_de, key, version)
                    VALUES ('demo', 'Demo', 'Demo', 'KEY', '1.0')
                    """
                )
            repo = CatalogRepository(db.connection)
            folder = root / "LAN" / "demo"
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "demo.eti").write_bytes(b"data")

            app = Application(AppConfig(bind_port=0))
            app._state.repository = repo  # noqa: SLF001
            app._state.platform_adapter = _LinuxPlatform()  # noqa: SLF001
            app._state.user_settings = UserSettings(  # noqa: SLF001
                nickname="Tester",
                theme="dark",
                log_level="WARNING",
                auto_start_sync=True,
                library_path_initialized=True,
                windows_game_drive_letter="D",
                linux_install_path=str(root / "LAN"),
            )
            provider = _SyncProvider(ok=False, detail="remove_failed")
            app._state.sync_provider = provider  # noqa: SLF001
            try:
                result = app._game_action("demo", "delete")  # noqa: SLF001
                self.assertFalse(result["ok"])
                self.assertEqual(result["message"], "sync_remove_failed")
                self.assertTrue(folder.exists())
            finally:
                app._server.server_close()  # noqa: SLF001
                db.connection.close()

    def test_delete_local_game_skips_sync_removal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = open_database(str(root / "app.db"))
            with db.connection:
                db.connection.execute(
                    """
                    INSERT INTO game_catalog(id, title_en, title_de, key, version, game_provider_type)
                    VALUES ('local-demo', 'Local Demo', 'Lokale Demo', 'KEY', '1.0', 'local')
                    """
                )
            repo = CatalogRepository(db.connection)
            repo.set_install_state("local-demo", "installed", "1.0")
            folder = root / "LAN" / "local-demo"
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "game_start.sh").write_text("#!/bin/sh\n", encoding="utf-8")

            app = Application(AppConfig(bind_port=0))
            app._state.repository = repo  # noqa: SLF001
            app._state.platform_adapter = _LinuxPlatform()  # noqa: SLF001
            app._state.user_settings = UserSettings(  # noqa: SLF001
                nickname="Tester",
                theme="dark",
                log_level="WARNING",
                auto_start_sync=True,
                library_path_initialized=True,
                windows_game_drive_letter="D",
                linux_install_path=str(root / "LAN"),
            )
            provider = _SyncProvider(ok=True, detail="ok")
            app._state.sync_provider = provider  # noqa: SLF001
            try:
                result = app._game_action("local-demo", "delete")  # noqa: SLF001
                self.assertTrue(result["ok"])
                self.assertEqual(provider.removed, [])
                self.assertTrue(folder.exists())
                self.assertIsNone(repo.get_game("local-demo", locale="en"))
            finally:
                app._server.server_close()  # noqa: SLF001
                db.connection.close()

    def test_delete_ouisync_game_removes_its_repository(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = open_database(str(root / "app.db"))
            with db.connection:
                db.connection.execute(
                    """
                    INSERT INTO game_catalog(id, title_en, title_de, key, version, game_provider_type)
                    VALUES ('demo', 'Demo', 'Demo', 'KEY', '1.0', 'ouisync')
                    """
                )
            repo = CatalogRepository(db.connection)
            folder = root / "LAN" / "demo"
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "demo.eti").write_bytes(b"data")

            app = Application(AppConfig(bind_port=0))
            app._state.repository = repo  # noqa: SLF001
            app._state.platform_adapter = _LinuxPlatform()  # noqa: SLF001
            app._state.user_settings = UserSettings(  # noqa: SLF001
                nickname="Tester",
                theme="dark",
                log_level="WARNING",
                auto_start_sync=True,
                library_path_initialized=True,
                windows_game_drive_letter="D",
                linux_install_path=str(root / "LAN"),
            )
            provider = _SyncProvider(ok=True, detail="ok")
            app._state.sync_provider = provider  # noqa: SLF001
            try:
                result = app._game_action("demo", "delete")  # noqa: SLF001
                self.assertTrue(result["ok"])
                self.assertEqual(result["message"], "deleted")
                self.assertFalse(folder.exists())
                self.assertEqual(provider.removed, [str(folder)])
                self.assertEqual(provider.paused, [])
            finally:
                app._server.server_close()  # noqa: SLF001
                db.connection.close()

    def test_runtime_db_discarded_removes_sync_folder_and_local_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = open_database(str(root / "app.db"))
            with db.connection:
                db.connection.execute(
                    """
                    INSERT INTO game_catalog(id, title_en, title_de, key, version)
                    VALUES ('demo', 'Demo', 'Demo', 'DEMO', '1.0')
                    """
                )
            repo = CatalogRepository(db.connection)
            repo.set_install_state("demo", "installed", "1.0")
            folder = root / "LAN" / "demo"
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "demo.eti").write_bytes(b"data")
            runtime_db = root / "runtime-update.db"
            self._create_runtime_update_db(
                runtime_db,
                games=[("demo", "Demo", "DEMO")],
                discarded=[("demo", "DEMO")],
            )

            app = Application(AppConfig(bind_port=0))
            app._state.database = db  # noqa: SLF001
            app._state.repository = repo  # noqa: SLF001
            app._state.platform_adapter = _LinuxPlatform()  # noqa: SLF001
            app._state.user_settings = UserSettings(  # noqa: SLF001
                nickname="Tester",
                theme="dark",
                log_level="WARNING",
                auto_start_sync=True,
                library_path_initialized=True,
                windows_game_drive_letter="D",
                linux_install_path=str(root / "LAN"),
            )
            provider = _SyncProvider(ok=True, detail="ok")
            app._state.sync_provider = provider  # noqa: SLF001
            app._resolve_runtime_update_db_sources = (  # type: ignore[method-assign]  # noqa: SLF001
                lambda: [("eti_launcher", runtime_db)]
            )
            try:
                self.assertTrue(app._try_import_runtime_update_dbs())  # noqa: SLF001
                self.assertFalse(folder.exists())
                self.assertTrue(
                    any(
                        path.replace("\\", "/").endswith("/demo")
                        for path in provider.removed
                    )
                )
                game = repo.get_game("demo", locale="en")
                self.assertIsNone(game)
                remaining_catalog = db.connection.execute(
                    "SELECT COUNT(*) FROM game_catalog WHERE id = 'demo'"
                ).fetchone()
                self.assertEqual(int(remaining_catalog[0]), 0)
                remaining_install = db.connection.execute(
                    "SELECT COUNT(*) FROM install_state WHERE game_id = 'demo'"
                ).fetchone()
                self.assertEqual(int(remaining_install[0]), 0)
            finally:
                app._server.server_close()  # noqa: SLF001
                db.connection.close()

    def test_runtime_db_discarded_skips_ids_not_in_local_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = open_database(str(root / "app.db"))
            with db.connection:
                db.connection.execute(
                    """
                    INSERT INTO game_catalog(id, title_en, title_de, key, version)
                    VALUES ('kept', 'Kept', 'Kept', 'KEEP', '1.0')
                    """
                )
            repo = CatalogRepository(db.connection)
            runtime_db = root / "runtime-update.db"
            self._create_runtime_update_db(runtime_db, discarded=[("demo", "DEMO")])

            app = Application(AppConfig(bind_port=0))
            app._state.database = db  # noqa: SLF001
            app._state.repository = repo  # noqa: SLF001
            app._state.platform_adapter = _LinuxPlatform()  # noqa: SLF001
            app._state.user_settings = UserSettings(  # noqa: SLF001
                nickname="Tester",
                theme="dark",
                log_level="WARNING",
                auto_start_sync=True,
                library_path_initialized=True,
                windows_game_drive_letter="D",
                linux_install_path=str(root / "LAN"),
            )
            provider = _SyncProvider(ok=True, detail="ok")
            app._state.sync_provider = provider  # noqa: SLF001
            app._resolve_runtime_update_db_sources = (  # type: ignore[method-assign]  # noqa: SLF001
                lambda: [("eti_launcher", runtime_db)]
            )
            try:
                self.assertTrue(app._try_import_runtime_update_dbs())  # noqa: SLF001
                self.assertEqual(provider.removed, [])
                kept = repo.get_game("kept", locale="en")
                self.assertIsNotNone(kept)
            finally:
                app._server.server_close()  # noqa: SLF001
                db.connection.close()

    def test_runtime_db_discarded_matches_game_id_case_insensitive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = open_database(str(root / "app.db"))
            with db.connection:
                db.connection.execute(
                    """
                    INSERT INTO game_catalog(id, title_en, title_de, key, version)
                    VALUES ('Demo', 'Demo', 'Demo', 'DEMO', '1.0')
                    """
                )
            repo = CatalogRepository(db.connection)
            folder = root / "LAN" / "Demo"
            folder.mkdir(parents=True, exist_ok=True)
            runtime_db = root / "runtime-update.db"
            self._create_runtime_update_db(runtime_db, discarded=[("demo", "DEMO")])

            app = Application(AppConfig(bind_port=0))
            app._state.database = db  # noqa: SLF001
            app._state.repository = repo  # noqa: SLF001
            app._state.platform_adapter = _LinuxPlatform()  # noqa: SLF001
            app._state.user_settings = UserSettings(  # noqa: SLF001
                nickname="Tester",
                theme="dark",
                log_level="WARNING",
                auto_start_sync=True,
                library_path_initialized=True,
                windows_game_drive_letter="D",
                linux_install_path=str(root / "LAN"),
            )
            provider = _SyncProvider(ok=True, detail="ok")
            app._state.sync_provider = provider  # noqa: SLF001
            app._resolve_runtime_update_db_sources = (  # type: ignore[method-assign]  # noqa: SLF001
                lambda: [("eti_launcher", runtime_db)]
            )
            try:
                self.assertTrue(app._try_import_runtime_update_dbs())  # noqa: SLF001
                self.assertFalse(folder.exists())
                game = repo.get_game("Demo", locale="en")
                self.assertIsNone(game)
            finally:
                app._server.server_close()  # noqa: SLF001
                db.connection.close()


if __name__ == "__main__":
    unittest.main()
