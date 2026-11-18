"""Tests for provider-specific sync controls in Application."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from src.core.config.loader import AppConfig
from src.core.service.app import Application
from src.core.service.settings_store import UserSettings
from src.core.sync.provider import SyncStatus


class _ActionProvider:
    def __init__(self, name: str) -> None:
        self.name = name
        self.started = 0
        self.stopped = 0
        self.running = False

    def start(self) -> SyncStatus:
        self.started += 1
        self.running = True
        return SyncStatus(provider=self.name, running=True, state="running", pid=1234)

    def stop(self) -> SyncStatus:
        self.stopped += 1
        self.running = False
        return SyncStatus(provider=self.name, running=False, state="stopped", pid=None)

    def status(self) -> SyncStatus:
        return SyncStatus(
            provider=self.name,
            running=self.running,
            state="running" if self.running else "stopped",
            pid=1234 if self.running else None,
        )

    def metrics(self):  # pragma: no cover - not used by this test
        raise NotImplementedError


class _ActionRouter:
    def __init__(self) -> None:
        self.providers = {
            "resilio": _ActionProvider("resilio"),
            "ouisync": _ActionProvider("ouisync"),
        }

    def provider_for_type(self, provider_type: str | None):
        return self.providers["ouisync" if str(provider_type or "").strip().lower() == "ouisync" else "resilio"]


class ApplicationSyncProviderActionTests(unittest.TestCase):
    def test_provider_actions_target_selected_provider_only(self) -> None:
        app = Application(AppConfig(bind_port=0))
        router = _ActionRouter()
        app._state.sync_provider = router  # noqa: SLF001
        app._state.user_settings = UserSettings(  # noqa: SLF001
            nickname="Tester",
            theme="dark",
            log_level="WARNING",
            auto_start_sync=True,
            library_path_initialized=True,
            windows_game_drive_letter="D",
            linux_install_path="library",
        )

        try:
            with (
                patch.object(app, "_apply_all_extra_sync_items") as mocked_apply,
                patch.object(
                    app, "_persist_resilio_library_path", return_value=True
                ) as mocked_persist,
            ):
                start_result = app._sync_provider_action("ouisync", "start")  # noqa: SLF001
                stop_result = app._sync_provider_action("ouisync", "stop")  # noqa: SLF001
                restart_result = app._sync_provider_action("resilio", "restart")  # noqa: SLF001

            self.assertTrue(start_result["running"])
            self.assertEqual(router.providers["ouisync"].started, 1)
            self.assertEqual(router.providers["resilio"].started, 1)
            self.assertEqual(router.providers["ouisync"].stopped, 1)
            self.assertEqual(router.providers["resilio"].stopped, 1)
            self.assertFalse(stop_result["running"])
            self.assertTrue(restart_result["running"])
            mocked_apply.assert_called()
            mocked_persist.assert_called()
        finally:
            app._server.server_close()  # noqa: SLF001 explicit cleanup for bound test server

    def test_provider_action_blocks_when_library_path_not_initialized(self) -> None:
        app = Application(AppConfig(bind_port=0))
        router = _ActionRouter()
        app._state.sync_provider = router  # noqa: SLF001
        app._state.user_settings = UserSettings(  # noqa: SLF001
            nickname="Tester",
            theme="dark",
            log_level="WARNING",
            auto_start_sync=True,
            library_path_initialized=False,
            windows_game_drive_letter="D",
            linux_install_path="library",
        )

        try:
            result = app._sync_provider_action("ouisync", "start")  # noqa: SLF001
            self.assertEqual(result["state"], "blocked")
            self.assertEqual(result["last_error"], "library_path_not_initialized")
            self.assertEqual(router.providers["ouisync"].started, 0)
        finally:
            app._server.server_close()  # noqa: SLF001 explicit cleanup for bound test server


if __name__ == "__main__":
    unittest.main()
