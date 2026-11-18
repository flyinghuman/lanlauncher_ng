"""Tests for automatic install/update watchdog behavior."""

from __future__ import annotations

import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.core.catalog.repository import CatalogRepository
from src.core.config.loader import AppConfig
from src.core.db.store import open_database
from src.core.launcher.game_manager import GameActionResult
from src.core.service.app import Application
from src.core.service.launcher_site import default_snapshot
from src.core.service.settings_store import UserSettings


class _LinuxAdapter:
    def platform_name(self) -> str:
        return "linux"


class _FakeSyncProvider:
    def __init__(self, progress_percent: int = 100, down_status: int = 1) -> None:
        self.progress_percent = progress_percent
        self.down_status = down_status

    def status(self):  # pragma: no cover - not used directly in this unit
        return None

    def folder_sync_status(self, _folder_path: str) -> dict[str, int | bool]:
        return {
            "active": True,
            "progress_percent": self.progress_percent,
            "down_eta": 10,
            "down_speed": 2048,
            "down_status": self.down_status,
        }


class _FakeGameManager:
    def __init__(self) -> None:
        self.installs: list[str] = []
        self.updates: list[str] = []
        self.installed_versions: dict[str, str] = {}

    def install(self, game_id: str, output_callback=None) -> GameActionResult:
        self.installs.append(game_id)
        if output_callback is not None:
            output_callback("extracting data")
        return GameActionResult(True, "install", game_id, "installed", {})

    def update(self, game_id: str, output_callback=None) -> GameActionResult:
        self.updates.append(game_id)
        if output_callback is not None:
            output_callback("updating data")
        return GameActionResult(True, "update", game_id, "updated", {})

    def check_status(self, game_id: str) -> GameActionResult:
        return GameActionResult(
            True,
            "status",
            game_id,
            "ok",
            {"installed_version": self.installed_versions.get(game_id, "")},
        )


class _StreamingInstallGameManager(_FakeGameManager):
    def install(self, game_id: str, output_callback=None) -> GameActionResult:
        self.installs.append(game_id)
        if output_callback is not None:
            output_callback("archive extraction started")
            output_callback("Extracting 42%")
        self.installed_versions[game_id] = "20250101"
        return GameActionResult(True, "install", game_id, "installed", {})


class _FailingGameManager(_FakeGameManager):
    def install(self, game_id: str, output_callback=None) -> GameActionResult:
        self.installs.append(game_id)
        return GameActionResult(False, "install", game_id, "install_failed", {})

    def update(self, game_id: str, output_callback=None) -> GameActionResult:
        self.updates.append(game_id)
        return GameActionResult(False, "update", game_id, "update_failed", {})


class _GameSetupFailingManager(_FakeGameManager):
    def install(self, game_id: str, output_callback=None) -> GameActionResult:
        self.installs.append(game_id)
        return GameActionResult(
            False,
            "install",
            game_id,
            "game_setup_failed",
            {"script": "/tmp/LAN/demo/game_setup.cmd", "code": 1},
        )


class ApplicationAutoInstallWatchdogTests(unittest.TestCase):
    def test_auto_install_runs_after_sync_download_reaches_100_percent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = open_database(str(root / "watchdog.db"))
            with db.connection:
                db.connection.execute(
                    """
                    INSERT INTO game_catalog(id, title_en, title_de, key, size_gb, version)
                    VALUES ('demo', 'Demo', 'Demo', 'KEY', 1.0, '20250101')
                    """
                )

            repo = CatalogRepository(db.connection)
            game_folder = root / "LAN" / "demo"
            game_folder.mkdir(parents=True, exist_ok=True)
            (game_folder / "demo.eti").write_bytes(b"data")

            manager = _FakeGameManager()
            manager.installed_versions["demo"] = "20250101"

            app = Application(AppConfig(bind_port=0))
            app._state.repository = repo  # noqa: SLF001
            app._state.game_manager = manager  # noqa: SLF001
            app._state.sync_provider = _FakeSyncProvider(progress_percent=100)  # noqa: SLF001
            app._state.platform_adapter = _LinuxAdapter()  # noqa: SLF001
            app._state.user_settings = UserSettings(  # noqa: SLF001
                nickname="Tester",
                theme="dark",
                log_level="WARNING",
                auto_start_sync=True,
                library_path_initialized=True,
                windows_game_drive_letter="D",
                linux_install_path=str(root / "LAN"),
            )
            try:
                app._run_auto_install_watchdog_cycle()  # noqa: SLF001
                self.assertEqual(manager.installs, ["demo"])
                game = repo.get_game("demo", locale="en")
                self.assertIsNotNone(game)
                assert game is not None
                self.assertEqual(game["install_state"], "installed")
                self.assertEqual(game["installed_version"], "20250101")
                self.assertFalse(game["needs_update"])
            finally:
                app._server.server_close()  # noqa: SLF001
                db.connection.close()

    def test_auto_install_uses_update_path_for_installed_games_with_update_flag(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = open_database(str(root / "watchdog.db"))
            with db.connection:
                db.connection.execute(
                    """
                    INSERT INTO game_catalog(id, title_en, title_de, key, size_gb, version)
                    VALUES ('demo', 'Demo', 'Demo', 'KEY', 1.0, '20250101')
                    """
                )

            repo = CatalogRepository(db.connection)
            repo.set_install_state("demo", "installed", "20240101")

            game_folder = root / "LAN" / "demo"
            game_folder.mkdir(parents=True, exist_ok=True)
            (game_folder / "demo.eti").write_bytes(b"data")

            manager = _FakeGameManager()
            manager.installed_versions["demo"] = "20250101"

            app = Application(AppConfig(bind_port=0))
            app._state.repository = repo  # noqa: SLF001
            app._state.game_manager = manager  # noqa: SLF001
            app._state.sync_provider = _FakeSyncProvider(progress_percent=100)  # noqa: SLF001
            app._state.platform_adapter = _LinuxAdapter()  # noqa: SLF001
            app._state.user_settings = UserSettings(  # noqa: SLF001
                nickname="Tester",
                theme="dark",
                log_level="WARNING",
                auto_start_sync=True,
                library_path_initialized=True,
                windows_game_drive_letter="D",
                linux_install_path=str(root / "LAN"),
            )
            try:
                app._run_auto_install_watchdog_cycle()  # noqa: SLF001
                self.assertEqual(manager.updates, ["demo"])
                game = repo.get_game("demo", locale="en")
                self.assertIsNotNone(game)
                assert game is not None
                self.assertEqual(game["install_state"], "installed")
                self.assertEqual(game["installed_version"], "20250101")
                self.assertFalse(game["needs_update"])
            finally:
                app._server.server_close()  # noqa: SLF001
                db.connection.close()

    def test_auto_install_failure_rolls_back_install_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = open_database(str(root / "watchdog.db"))
            with db.connection:
                db.connection.execute(
                    """
                    INSERT INTO game_catalog(id, title_en, title_de, key, size_gb, version)
                    VALUES ('demo', 'Demo', 'Demo', 'KEY', 1.0, '20250101')
                    """
                )

            repo = CatalogRepository(db.connection)
            game_folder = root / "LAN" / "demo"
            game_folder.mkdir(parents=True, exist_ok=True)
            (game_folder / "demo.eti").write_bytes(b"data")

            manager = _FailingGameManager()
            app = Application(AppConfig(bind_port=0))
            app._state.repository = repo  # noqa: SLF001
            app._state.game_manager = manager  # noqa: SLF001
            app._state.sync_provider = _FakeSyncProvider(progress_percent=100)  # noqa: SLF001
            app._state.platform_adapter = _LinuxAdapter()  # noqa: SLF001
            app._state.user_settings = UserSettings(  # noqa: SLF001
                nickname="Tester",
                theme="dark",
                log_level="WARNING",
                auto_start_sync=True,
                library_path_initialized=True,
                windows_game_drive_letter="D",
                linux_install_path=str(root / "LAN"),
            )
            try:
                app._run_auto_install_watchdog_cycle()  # noqa: SLF001
                game = repo.get_game("demo", locale="en")
                self.assertIsNotNone(game)
                assert game is not None
                self.assertEqual(game["install_state"], "missing")
            finally:
                app._server.server_close()  # noqa: SLF001
                db.connection.close()

    def test_auto_install_failure_does_not_retry_same_archive_after_time_passes(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = open_database(str(root / "watchdog.db"))
            with db.connection:
                db.connection.execute(
                    """
                    INSERT INTO game_catalog(id, title_en, title_de, key, size_gb, version)
                    VALUES ('demo', 'Demo', 'Demo', 'KEY', 1.0, '20250101')
                    """
                )

            repo = CatalogRepository(db.connection)
            game_folder = root / "LAN" / "demo"
            game_folder.mkdir(parents=True, exist_ok=True)
            (game_folder / "demo.eti").write_bytes(b"data")

            manager = _FailingGameManager()
            app = Application(AppConfig(bind_port=0))
            app._state.repository = repo  # noqa: SLF001
            app._state.game_manager = manager  # noqa: SLF001
            app._state.sync_provider = _FakeSyncProvider(progress_percent=100)  # noqa: SLF001
            app._state.platform_adapter = _LinuxAdapter()  # noqa: SLF001
            app._state.user_settings = UserSettings(  # noqa: SLF001
                nickname="Tester",
                theme="dark",
                log_level="WARNING",
                auto_start_sync=True,
                library_path_initialized=True,
                windows_game_drive_letter="D",
                linux_install_path=str(root / "LAN"),
            )
            try:
                with patch(
                    "src.core.service.app.time.time",
                    side_effect=[1000.0, 1035.0, 1035.0, 1035.0],
                ):
                    app._run_auto_install_watchdog_cycle()  # noqa: SLF001
                    app._run_auto_install_watchdog_cycle()  # noqa: SLF001
                self.assertEqual(manager.installs, ["demo"])
            finally:
                app._server.server_close()  # noqa: SLF001
                db.connection.close()

    def test_auto_install_retries_when_archive_payload_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = open_database(str(root / "watchdog.db"))
            with db.connection:
                db.connection.execute(
                    """
                    INSERT INTO game_catalog(id, title_en, title_de, key, size_gb, version)
                    VALUES ('demo', 'Demo', 'Demo', 'KEY', 1.0, '20250101')
                    """
                )

            repo = CatalogRepository(db.connection)
            game_folder = root / "LAN" / "demo"
            game_folder.mkdir(parents=True, exist_ok=True)
            archive = game_folder / "demo.eti"
            archive.write_bytes(b"v1")

            manager = _FailingGameManager()
            app = Application(AppConfig(bind_port=0))
            app._state.repository = repo  # noqa: SLF001
            app._state.game_manager = manager  # noqa: SLF001
            app._state.sync_provider = _FakeSyncProvider(progress_percent=100)  # noqa: SLF001
            app._state.platform_adapter = _LinuxAdapter()  # noqa: SLF001
            app._state.user_settings = UserSettings(  # noqa: SLF001
                nickname="Tester",
                theme="dark",
                log_level="WARNING",
                auto_start_sync=True,
                library_path_initialized=True,
                windows_game_drive_letter="D",
                linux_install_path=str(root / "LAN"),
            )
            try:
                app._run_auto_install_watchdog_cycle()  # noqa: SLF001
                archive.write_bytes(b"v2")
                app._run_auto_install_watchdog_cycle()  # noqa: SLF001
                self.assertEqual(manager.installs, ["demo", "demo"])
            finally:
                app._server.server_close()  # noqa: SLF001
                db.connection.close()

    def test_auto_install_sets_downloading_state_until_sync_reaches_100(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = open_database(str(root / "watchdog.db"))
            with db.connection:
                db.connection.execute(
                    """
                    INSERT INTO game_catalog(id, title_en, title_de, key, size_gb, version)
                    VALUES ('demo', 'Demo', 'Demo', 'KEY', 1.0, '20250101')
                    """
                )

            repo = CatalogRepository(db.connection)
            game_folder = root / "LAN" / "demo"
            game_folder.mkdir(parents=True, exist_ok=True)
            (game_folder / "demo.eti").write_bytes(b"data")

            manager = _FakeGameManager()
            app = Application(AppConfig(bind_port=0))
            app._state.repository = repo  # noqa: SLF001
            app._state.game_manager = manager  # noqa: SLF001
            app._state.sync_provider = _FakeSyncProvider(progress_percent=42)  # noqa: SLF001
            app._state.platform_adapter = _LinuxAdapter()  # noqa: SLF001
            app._state.user_settings = UserSettings(  # noqa: SLF001
                nickname="Tester",
                theme="dark",
                log_level="WARNING",
                auto_start_sync=True,
                library_path_initialized=True,
                windows_game_drive_letter="D",
                linux_install_path=str(root / "LAN"),
            )
            try:
                app._run_auto_install_watchdog_cycle()  # noqa: SLF001
                self.assertEqual(manager.installs, [])
                game = repo.get_game("demo", locale="en")
                self.assertIsNotNone(game)
                assert game is not None
                self.assertEqual(game["install_state"], "downloading")
            finally:
                app._server.server_close()  # noqa: SLF001
                db.connection.close()

    def test_auto_install_retries_unpack_when_local_folder_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = open_database(str(root / "watchdog.db"))
            with db.connection:
                db.connection.execute(
                    """
                    INSERT INTO game_catalog(id, title_en, title_de, key, size_gb, version)
                    VALUES ('demo', 'Demo', 'Demo', 'KEY', 1.0, '20250101')
                    """
                )

            repo = CatalogRepository(db.connection)
            repo.set_install_state("demo", "installed", "20250101")
            game_folder = root / "LAN" / "demo"
            game_folder.mkdir(parents=True, exist_ok=True)
            (game_folder / "demo.eti").write_bytes(b"data")
            # Intentionally keep <game>/local missing. Watchdog must trigger unpack/install again.

            manager = _FakeGameManager()
            manager.installed_versions["demo"] = "20250101"

            app = Application(AppConfig(bind_port=0))
            app._state.repository = repo  # noqa: SLF001
            app._state.game_manager = manager  # noqa: SLF001
            app._state.sync_provider = _FakeSyncProvider(progress_percent=100)  # noqa: SLF001
            app._state.platform_adapter = _LinuxAdapter()  # noqa: SLF001
            app._state.user_settings = UserSettings(  # noqa: SLF001
                nickname="Tester",
                theme="dark",
                log_level="WARNING",
                auto_start_sync=True,
                library_path_initialized=True,
                windows_game_drive_letter="D",
                linux_install_path=str(root / "LAN"),
            )
            try:
                app._run_auto_install_watchdog_cycle()  # noqa: SLF001
                self.assertEqual(manager.installs, ["demo"])
                self.assertEqual(manager.updates, [])
            finally:
                app._server.server_close()  # noqa: SLF001
                db.connection.close()

    def test_sync_only_mode_skips_auto_extract_and_marks_game_ready_to_install(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = open_database(str(root / "watchdog.db"))
            with db.connection:
                db.connection.execute(
                    """
                    INSERT INTO game_catalog(id, title_en, title_de, key, size_gb, version)
                    VALUES ('demo', 'Demo', 'Demo', 'KEY', 1.0, '20250101')
                    """
                )

            repo = CatalogRepository(db.connection)
            repo.set_install_state("demo", "downloading", "")
            game_folder = root / "LAN" / "demo"
            game_folder.mkdir(parents=True, exist_ok=True)
            (game_folder / "demo.eti").write_bytes(b"data")

            manager = _FakeGameManager()

            app = Application(AppConfig(bind_port=0))
            app._state.repository = repo  # noqa: SLF001
            app._state.game_manager = manager  # noqa: SLF001
            app._state.sync_provider = _FakeSyncProvider(progress_percent=100)  # noqa: SLF001
            app._state.platform_adapter = _LinuxAdapter()  # noqa: SLF001
            app._state.user_settings = UserSettings(  # noqa: SLF001
                nickname="Tester",
                theme="dark",
                log_level="WARNING",
                auto_start_sync=True,
                library_path_initialized=True,
                windows_game_drive_letter="D",
                linux_install_path=str(root / "LAN"),
                sync_only_mode=True,
            )
            try:
                app._run_auto_install_watchdog_cycle()  # noqa: SLF001
                self.assertEqual(manager.installs, [])
                game = repo.get_game("demo", locale="en")
                assert game is not None
                self.assertEqual(game["install_state"], "missing")
                payload = app._game_sync_status_payload("demo")  # noqa: SLF001
                self.assertEqual(payload["sync_state"], "ready_to_install")
                self.assertTrue(
                    any(
                        "sync-only mode enabled" in line
                        for line in payload["install_console_lines"]
                    )
                )
            finally:
                app._server.server_close()  # noqa: SLF001
                db.connection.close()

    def test_missing_local_warning_not_emitted_while_still_downloading(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = open_database(str(root / "watchdog.db"))
            with db.connection:
                db.connection.execute(
                    """
                    INSERT INTO game_catalog(id, title_en, title_de, key, size_gb, version)
                    VALUES ('demo', 'Demo', 'Demo', 'KEY', 1.0, '20250101')
                    """
                )

            repo = CatalogRepository(db.connection)
            repo.set_install_state("demo", "installed", "20250101")
            game_folder = root / "LAN" / "demo"
            game_folder.mkdir(parents=True, exist_ok=True)
            (game_folder / "demo.eti").write_bytes(b"data")
            # local folder is missing, but download progress is below 100%.

            manager = _FakeGameManager()
            app = Application(AppConfig(bind_port=0))
            app._state.repository = repo  # noqa: SLF001
            app._state.game_manager = manager  # noqa: SLF001
            app._state.sync_provider = _FakeSyncProvider(progress_percent=42)  # noqa: SLF001
            app._state.platform_adapter = _LinuxAdapter()  # noqa: SLF001
            app._state.user_settings = UserSettings(  # noqa: SLF001
                nickname="Tester",
                theme="dark",
                log_level="WARNING",
                auto_start_sync=True,
                library_path_initialized=True,
                windows_game_drive_letter="D",
                linux_install_path=str(root / "LAN"),
            )

            logger = logging.getLogger("src.core.service.app")
            messages: list[str] = []

            class _Capture(logging.Handler):
                def emit(self, record: logging.LogRecord) -> None:
                    messages.append(record.getMessage())

            handler = _Capture(level=logging.WARNING)
            logger.addHandler(handler)
            try:
                app._run_auto_install_watchdog_cycle()  # noqa: SLF001
                self.assertEqual(manager.installs, [])
                self.assertFalse(
                    any("auto_install_local_missing_retry" in msg for msg in messages)
                )
            finally:
                logger.removeHandler(handler)
                app._server.server_close()  # noqa: SLF001
                db.connection.close()

    def test_auto_install_failure_log_contains_reason_details(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = open_database(str(root / "watchdog.db"))
            with db.connection:
                db.connection.execute(
                    """
                    INSERT INTO game_catalog(id, title_en, title_de, key, size_gb, version)
                    VALUES ('demo', 'Demo', 'Demo', 'KEY', 1.0, '20250101')
                    """
                )

            repo = CatalogRepository(db.connection)
            game_folder = root / "LAN" / "demo"
            game_folder.mkdir(parents=True, exist_ok=True)
            (game_folder / "demo.eti").write_bytes(b"data")

            manager = _GameSetupFailingManager()
            app = Application(AppConfig(bind_port=0))
            app._state.repository = repo  # noqa: SLF001
            app._state.game_manager = manager  # noqa: SLF001
            app._state.sync_provider = _FakeSyncProvider(progress_percent=100)  # noqa: SLF001
            app._state.platform_adapter = _LinuxAdapter()  # noqa: SLF001
            app._state.user_settings = UserSettings(  # noqa: SLF001
                nickname="Tester",
                theme="dark",
                log_level="WARNING",
                auto_start_sync=True,
                library_path_initialized=True,
                windows_game_drive_letter="D",
                linux_install_path=str(root / "LAN"),
            )

            logger = logging.getLogger("src.core.service.app")
            messages: list[str] = []

            class _Capture(logging.Handler):
                def emit(self, record: logging.LogRecord) -> None:
                    messages.append(record.getMessage())

            handler = _Capture(level=logging.WARNING)
            logger.addHandler(handler)
            try:
                app._run_auto_install_watchdog_cycle()  # noqa: SLF001
                self.assertTrue(
                    any(
                        "auto_install_watchdog_failed" in msg
                        and "message=game_setup_failed" in msg
                        and "reason=code=1 script=/tmp/LAN/demo/game_setup.cmd" in msg
                        for msg in messages
                    )
                )
            finally:
                logger.removeHandler(handler)
                app._server.server_close()  # noqa: SLF001
                db.connection.close()

    def test_game_sync_status_includes_install_console_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = open_database(str(root / "watchdog.db"))
            with db.connection:
                db.connection.execute(
                    """
                    INSERT INTO game_catalog(id, title_en, title_de, key, size_gb, version)
                    VALUES ('demo', 'Demo', 'Demo', 'KEY', 1.0, '20250101')
                    """
                )

            repo = CatalogRepository(db.connection)
            game_folder = root / "LAN" / "demo"
            game_folder.mkdir(parents=True, exist_ok=True)
            (game_folder / "demo.eti").write_bytes(b"data")

            manager = _FakeGameManager()
            manager.installed_versions["demo"] = "20250101"

            app = Application(AppConfig(bind_port=0))
            app._state.repository = repo  # noqa: SLF001
            app._state.game_manager = manager  # noqa: SLF001
            app._state.sync_provider = _FakeSyncProvider(progress_percent=100)  # noqa: SLF001
            app._state.platform_adapter = _LinuxAdapter()  # noqa: SLF001
            app._state.user_settings = UserSettings(  # noqa: SLF001
                nickname="Tester",
                theme="dark",
                log_level="WARNING",
                auto_start_sync=True,
                library_path_initialized=True,
                windows_game_drive_letter="D",
                linux_install_path=str(root / "LAN"),
            )
            try:
                app._run_auto_install_watchdog_cycle()  # noqa: SLF001
                payload = app._game_sync_status_payload("demo")  # noqa: SLF001
                self.assertIn("install_console_lines", payload)
                lines = payload["install_console_lines"]
                self.assertTrue(any("extracting data" in line for line in lines))
            finally:
                app._server.server_close()  # noqa: SLF001
                db.connection.close()

    def test_manual_install_action_populates_install_console_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = open_database(str(root / "watchdog.db"))
            with db.connection:
                db.connection.execute(
                    """
                    INSERT INTO game_catalog(id, title_en, title_de, key, size_gb, version)
                    VALUES ('demo', 'Demo', 'Demo', 'KEY', 1.0, '20250101')
                    """
                )

            repo = CatalogRepository(db.connection)
            manager = _StreamingInstallGameManager()

            app = Application(AppConfig(bind_port=0))
            app._state.repository = repo  # noqa: SLF001
            app._state.game_manager = manager  # noqa: SLF001
            app._state.platform_adapter = _LinuxAdapter()  # noqa: SLF001
            try:
                result = app._game_action("demo", "install")  # noqa: SLF001
                self.assertTrue(result["ok"])
                payload = app._game_sync_status_payload("demo")  # noqa: SLF001
                self.assertIn("install_console_lines", payload)
                lines = payload["install_console_lines"]
                self.assertTrue(
                    any("archive extraction started" in line for line in lines)
                )
                self.assertTrue(any("Extracting 42%" in line for line in lines))
                game = repo.get_game("demo", locale="en")
                assert game is not None
                self.assertEqual(game["install_state"], "installed")
            finally:
                app._server.server_close()  # noqa: SLF001
                db.connection.close()

    def test_game_sync_status_keeps_installed_state_and_marks_syncing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = open_database(str(root / "watchdog.db"))
            with db.connection:
                db.connection.execute(
                    """
                    INSERT INTO game_catalog(id, title_en, title_de, key, size_gb, version)
                    VALUES ('demo', 'Demo', 'Demo', 'KEY', 1.0, '20250101')
                    """
                )

            repo = CatalogRepository(db.connection)
            repo.set_install_state("demo", "installed", "20240101")
            game_folder = root / "LAN" / "demo"
            game_folder.mkdir(parents=True, exist_ok=True)
            (game_folder / "local").mkdir(parents=True, exist_ok=True)
            (game_folder / "game_start.sh").write_text(
                "#!/usr/bin/env bash\n",
                encoding="utf-8",
            )
            # Existing installs stay startable even while Resilio is still indexing/updating.

            app = Application(AppConfig(bind_port=0))
            app._state.repository = repo  # noqa: SLF001
            app._state.sync_provider = _FakeSyncProvider(
                progress_percent=12, down_status=1
            )  # noqa: SLF001
            app._state.platform_adapter = _LinuxAdapter()  # noqa: SLF001
            app._state.user_settings = UserSettings(  # noqa: SLF001
                nickname="Tester",
                theme="dark",
                log_level="WARNING",
                auto_start_sync=True,
                library_path_initialized=True,
                windows_game_drive_letter="D",
                linux_install_path=str(root / "LAN"),
            )
            try:
                payload = app._game_sync_status_payload("demo")  # noqa: SLF001
                self.assertEqual(payload["install_state"], "installed")
                self.assertEqual(payload["sync_state"], "syncing")
                self.assertTrue(payload["installed"])
            finally:
                app._server.server_close()  # noqa: SLF001
                db.connection.close()

    def test_game_sync_status_downgrades_stale_installed_state_without_runtime_files(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = open_database(str(root / "watchdog.db"))
            with db.connection:
                db.connection.execute(
                    """
                    INSERT INTO game_catalog(id, title_en, title_de, key, size_gb, version)
                    VALUES ('demo', 'Demo', 'Demo', 'KEY', 1.0, '20250101')
                    """
                )

            repo = CatalogRepository(db.connection)
            repo.set_install_state("demo", "installed", "20240101")
            game_folder = root / "LAN" / "demo"
            game_folder.mkdir(parents=True, exist_ok=True)

            app = Application(AppConfig(bind_port=0))
            app._state.repository = repo  # noqa: SLF001
            app._state.sync_provider = _FakeSyncProvider(
                progress_percent=12, down_status=1
            )  # noqa: SLF001
            app._state.platform_adapter = _LinuxAdapter()  # noqa: SLF001
            app._state.user_settings = UserSettings(  # noqa: SLF001
                nickname="Tester",
                theme="dark",
                log_level="WARNING",
                auto_start_sync=True,
                library_path_initialized=True,
                windows_game_drive_letter="D",
                linux_install_path=str(root / "LAN"),
            )
            try:
                payload = app._game_sync_status_payload("demo")  # noqa: SLF001
                self.assertEqual(payload["install_state"], "missing")
                self.assertEqual(payload["sync_state"], "downloading")
                self.assertFalse(payload["installed"])
            finally:
                app._server.server_close()  # noqa: SLF001
                db.connection.close()

    def test_game_sync_status_marks_missing_game_as_downloading_when_active(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = open_database(str(root / "watchdog.db"))
            with db.connection:
                db.connection.execute(
                    """
                    INSERT INTO game_catalog(id, title_en, title_de, key, size_gb, version)
                    VALUES ('demo', 'Demo', 'Demo', 'KEY', 1.0, '20250101')
                    """
                )

            repo = CatalogRepository(db.connection)
            game_folder = root / "LAN" / "demo"
            game_folder.mkdir(parents=True, exist_ok=True)

            app = Application(AppConfig(bind_port=0))
            app._state.repository = repo  # noqa: SLF001
            app._state.sync_provider = _FakeSyncProvider(
                progress_percent=12, down_status=1
            )  # noqa: SLF001
            app._state.platform_adapter = _LinuxAdapter()  # noqa: SLF001
            app._state.user_settings = UserSettings(  # noqa: SLF001
                nickname="Tester",
                theme="dark",
                log_level="WARNING",
                auto_start_sync=True,
                library_path_initialized=True,
                windows_game_drive_letter="D",
                linux_install_path=str(root / "LAN"),
            )
            try:
                payload = app._game_sync_status_payload("demo")  # noqa: SLF001
                self.assertEqual(payload["install_state"], "missing")
                self.assertEqual(payload["sync_state"], "downloading")
                self.assertFalse(payload["installed"])
            finally:
                app._server.server_close()  # noqa: SLF001
                db.connection.close()

    def test_auto_install_skips_games_disabled_by_launcher_ini(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = open_database(str(root / "watchdog.db"))
            with db.connection:
                db.connection.execute(
                    """
                    INSERT INTO game_catalog(id, title_en, title_de, key, size_gb, version)
                    VALUES ('demo', 'Demo', 'Demo', 'KEY', 1.0, '20250101')
                    """
                )

            repo = CatalogRepository(db.connection)
            game_folder = root / "LAN" / "demo"
            game_folder.mkdir(parents=True, exist_ok=True)
            (game_folder / "demo.eti").write_bytes(b"data")

            manager = _FakeGameManager()
            app = Application(AppConfig(bind_port=0))
            app._state.repository = repo  # noqa: SLF001
            app._state.game_manager = manager  # noqa: SLF001
            app._state.sync_provider = _FakeSyncProvider(progress_percent=100)  # noqa: SLF001
            app._state.platform_adapter = _LinuxAdapter()  # noqa: SLF001
            app._state.user_settings = UserSettings(  # noqa: SLF001
                nickname="Tester",
                theme="dark",
                log_level="WARNING",
                auto_start_sync=True,
                library_path_initialized=True,
                windows_game_drive_letter="D",
                linux_install_path=str(root / "LAN"),
            )
            app._state.launcher_site_snapshot = default_snapshot()  # noqa: SLF001
            app._state.launcher_site_snapshot = (
                app._state.launcher_site_snapshot.__class__(  # noqa: SLF001
                    **{
                        **app._state.launcher_site_snapshot.to_dict(),  # noqa: SLF001
                        "disable_games": ["demo"],
                    }
                )
            )
            try:
                app._run_auto_install_watchdog_cycle()  # noqa: SLF001
                self.assertEqual(manager.installs, [])
            finally:
                app._server.server_close()  # noqa: SLF001
                db.connection.close()


if __name__ == "__main__":
    unittest.main()
