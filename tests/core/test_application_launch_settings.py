"""Tests for per-game launch runtime settings in Application."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.core.config.loader import AppConfig
from src.core.db.store import open_database
from src.core.launcher.game_manager import GameActionResult
from src.core.service.app import Application
from src.core.service.settings_store import UserSettings


class _GameManagerStub:
    def __init__(self) -> None:
        self.last_runtime_override = ""
        self.last_leave_terminal_open = False

    def start_game(
        self,
        game_id: str,
        *,
        server: bool = False,
        game_lang: str = "en",
        player: str = "",
        linux_runtime_override: str = "",
        linux_leave_terminal_open: bool = False,
    ) -> GameActionResult:
        _ = game_id
        _ = server
        _ = game_lang
        _ = player
        self.last_runtime_override = linux_runtime_override
        self.last_leave_terminal_open = linux_leave_terminal_open
        return GameActionResult(True, "start", "demo", "launched", {})

    def check_status(
        self, game_id: str
    ) -> GameActionResult:  # pragma: no cover - unused
        _ = game_id
        raise NotImplementedError

    def install(self, game_id: str) -> GameActionResult:  # pragma: no cover - unused
        _ = game_id
        raise NotImplementedError

    def update(self, game_id: str) -> GameActionResult:  # pragma: no cover - unused
        _ = game_id
        raise NotImplementedError

    def uninstall(self, game_id: str) -> GameActionResult:  # pragma: no cover - unused
        _ = game_id
        raise NotImplementedError


class ApplicationLaunchSettingsTests(unittest.TestCase):
    def test_metadata_runtime_is_default_until_user_sets_a_game_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = open_database(str(root / "app.db"))
            app = Application(AppConfig(bind_port=0))
            app._state.database = db  # noqa: SLF001
            app._state.user_settings = UserSettings(  # noqa: SLF001
                nickname="Tester",
                theme="dark",
                log_level="WARNING",
                auto_start_sync=True,
                library_path_initialized=True,
                windows_game_drive_letter="D",
                linux_install_path=str(root / "LAN"),
                linux_windows_runtime="wine",
            )
            try:
                with patch.object(
                    app, "_game_metadata", return_value=SimpleNamespace(runner="proton")
                ):
                    self.assertEqual(app._effective_linux_runtime_for_game("demo"), "proton")
                    app._game_launch_settings_update(  # noqa: SLF001
                        "demo", {"linux_runtime_override": "wine"}
                    )
                    self.assertEqual(app._effective_linux_runtime_for_game("demo"), "wine")
            finally:
                app._server.server_close()  # noqa: SLF001
                db.connection.close()

    def test_launch_settings_read_update_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = open_database(str(root / "app.db"))
            app = Application(AppConfig(bind_port=0))
            app._state.database = db  # noqa: SLF001
            app._state.user_settings = UserSettings(  # noqa: SLF001
                nickname="Tester",
                theme="dark",
                log_level="WARNING",
                auto_start_sync=True,
                library_path_initialized=True,
                windows_game_drive_letter="D",
                linux_install_path=str(root / "LAN"),
                linux_windows_runtime="wine",
            )
            try:
                initial = app._game_launch_settings_read("demo")  # noqa: SLF001
                self.assertTrue(initial["ok"])
                self.assertEqual(initial["linux_runtime_override"], "")
                self.assertFalse(initial["linux_leave_terminal_open"])
                self.assertEqual(initial["effective_linux_runtime"], "wine")

                saved = app._game_launch_settings_update(  # noqa: SLF001
                    "demo",
                    {
                        "linux_runtime_override": "proton",
                        "linux_leave_terminal_open": True,
                    },
                )
                self.assertTrue(saved["ok"])
                self.assertEqual(saved["linux_runtime_override"], "proton")
                self.assertTrue(saved["linux_leave_terminal_open"])
                self.assertEqual(saved["effective_linux_runtime"], "proton")

                reread = app._game_launch_settings_read("demo")  # noqa: SLF001
                self.assertTrue(reread["ok"])
                self.assertEqual(reread["linux_runtime_override"], "proton")
                self.assertTrue(reread["linux_leave_terminal_open"])
                self.assertEqual(reread["effective_linux_runtime"], "proton")

                cleared = app._game_launch_settings_update(  # noqa: SLF001
                    "demo",
                    {
                        "linux_runtime_override": "",
                        "linux_leave_terminal_open": False,
                    },
                )
                self.assertTrue(cleared["ok"])
                self.assertEqual(cleared["linux_runtime_override"], "")
                self.assertFalse(cleared["linux_leave_terminal_open"])
                self.assertEqual(cleared["effective_linux_runtime"], "wine")
            finally:
                app._server.server_close()  # noqa: SLF001
                db.connection.close()

    def test_game_start_uses_per_game_runtime_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = open_database(str(root / "app.db"))
            app = Application(AppConfig(bind_port=0))
            app._state.database = db  # noqa: SLF001
            app._state.user_settings = UserSettings(  # noqa: SLF001
                nickname="Tester",
                theme="dark",
                log_level="WARNING",
                auto_start_sync=True,
                library_path_initialized=True,
                windows_game_drive_letter="D",
                linux_install_path=str(root / "LAN"),
                linux_windows_runtime="wine",
            )
            manager = _GameManagerStub()
            app._state.game_manager = manager  # noqa: SLF001
            try:
                app._game_launch_settings_update(  # noqa: SLF001
                    "demo",
                    {
                        "linux_runtime_override": "proton-ge",
                        "linux_leave_terminal_open": True,
                    },
                )
                result = app._game_action("demo", "start")  # noqa: SLF001
                self.assertTrue(result["ok"])
                self.assertEqual(manager.last_runtime_override, "proton-ge")
                self.assertTrue(manager.last_leave_terminal_open)
            finally:
                app._server.server_close()  # noqa: SLF001
                db.connection.close()


if __name__ == "__main__":
    unittest.main()
