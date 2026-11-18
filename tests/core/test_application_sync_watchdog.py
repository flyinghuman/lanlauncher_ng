"""Tests for manual sync control and watchdog pause behavior."""

from __future__ import annotations

import os
import logging
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import Mock, patch

from src.core.config.loader import AppConfig
from src.core.platform.base import ActionResult
from src.core.service.app import Application
from src.core.service.settings_store import UserSettings
from src.core.sync.provider import SyncStatus


class _FakeSyncProvider:
    def __init__(self) -> None:
        self.started = 0
        self.stopped = 0
        self.running = False
        self.peer_device_ids: list[str] = []
        self.synced_folders: list[tuple[str, str]] = []

    def start(self) -> SyncStatus:
        self.started += 1
        self.running = True
        return SyncStatus(provider="resilio", running=True, state="running", pid=123)

    def stop(self) -> SyncStatus:
        self.stopped += 1
        self.running = False
        return SyncStatus(provider="resilio", running=False, state="stopped", pid=None)

    def status(self) -> SyncStatus:
        return SyncStatus(
            provider="resilio",
            running=self.running,
            state="running" if self.running else "stopped",
            pid=123 if self.running else None,
        )

    def metrics(self):  # pragma: no cover - unused in this test
        raise NotImplementedError

    def set_peer_device_ids(self, device_ids: list[str]) -> None:
        self.peer_device_ids = list(device_ids)

    def ensure_folder_synced(self, folder_path: str, secret: str) -> tuple[bool, str]:
        self.synced_folders.append((folder_path, secret))
        return True, "started"

    def folder_sync_status(self, _folder_path: str) -> dict[str, int | bool]:
        return {
            "active": True,
            "progress_percent": 100,
            "syncing": False,
            "queued_files": 0,
            "downloaded_gb": 0,
            "total_gb": 0,
        }


class _StartingSyncProvider(_FakeSyncProvider):
    def status(self) -> SyncStatus:
        return SyncStatus(
            provider="resilio",
            running=False,
            state="starting",
            pid=None,
        )


class _FailingOuisyncProvider(_FakeSyncProvider):
    def start(self) -> SyncStatus:
        raise OSError("sync_launch_failed")


class _PartialErrorSyncProvider(_FakeSyncProvider):
    def start(self) -> SyncStatus:
        self.started += 1
        self.running = True
        return SyncStatus(
            provider="dual",
            running=True,
            state="running",
            pid=321,
            last_error="<urlopen error [Errno 111] Connection refused>",
        )


class _FakeDualRouter:
    def __init__(self) -> None:
        self.resilio = _FakeSyncProvider()
        self.ouisync = _FakeSyncProvider()
        self.ouisync.running = True

    def provider_for_type(self, provider_type: str):
        if provider_type == "ouisync":
            return self.ouisync
        return self.resilio

    def status_for_type(self, provider_type: str) -> SyncStatus:
        return self.provider_for_type(provider_type).status()

    def status(self) -> SyncStatus:
        return SyncStatus(provider="dual", running=True, state="running", pid=222)


class _UnhealthyResilioProvider(_FakeSyncProvider):
    def __init__(self) -> None:
        super().__init__()
        self.recovered = 0

    def status(self) -> SyncStatus:
        return SyncStatus(
            provider="resilio",
            running=False,
            state="failed",
            pid=1152,
            last_error="sync_api_unreachable",
        )

    def recover_if_unhealthy(self) -> SyncStatus:
        self.recovered += 1
        return SyncStatus(provider="resilio", running=True, state="running", pid=1152)


class _FakeFolderStatusProvider:
    def __init__(self, status_payload: dict[str, int | bool]) -> None:
        self._status_payload = status_payload

    def folder_sync_status(self, _folder_path: str) -> dict[str, int | bool]:
        return self._status_payload


class _ManagedOuisyncProvider(_FakeSyncProvider):
    def __init__(self) -> None:
        super().__init__()
        self.approved: list[str] = []
        self.paused: list[str] = []
        self.folder_calls: list[tuple[str, str]] = []
        self.lan_publish_calls: list[str] = []
        self.lan_repository_paths: list[str] = []
        self.lan_reconcile_calls: list[list[str]] = []

    def approve_pending_devices(self) -> list[str]:
        self.approved.append("NEW-DEVICE")
        return ["NEW-DEVICE"]

    def list_shared_game_folders(self) -> list[dict[str, str]]:
        return [{"path": "library/shared", "id": "shared-id"}]

    def ensure_folder_synced(self, folder_path: str, secret: str) -> tuple[bool, str]:
        self.folder_calls.append((folder_path, secret))
        return True, "ouisync_folder_configured"

    def publish_lan_game(
        self, folder_path: str, repository_path: str | None = None
    ) -> dict[str, str]:
        self.lan_publish_calls.append(folder_path)
        if repository_path:
            self.lan_repository_paths.append(repository_path)
        return {"read_token": "token", "info_hash": "ab" * 20}

    def reconcile_lan_shared_games(self, folder_paths: list[str]) -> None:
        self.lan_reconcile_calls.append(folder_paths)

    def pause_folder_sync(self, folder_path: str) -> tuple[bool, str]:
        self.paused.append(folder_path)
        return True, "ouisync_folder_paused"


class _FakePlatformAdapter:
    def __init__(self) -> None:
        self.requests: list[tuple[str, str, str]] = []
        self.wine_dep_requests: list[list[str]] = []

    def platform_name(self) -> str:
        return "windows"

    def normalize_path(self, raw_path: str) -> str:  # pragma: no cover - unused
        return raw_path

    def validate_storage_path(self, raw_path: str):  # pragma: no cover - unused
        _ = raw_path
        raise NotImplementedError

    def open_folder(self, raw_path: str):  # pragma: no cover - unused
        _ = raw_path
        raise NotImplementedError

    def launch_executable(
        self, executable_path: str, args: list[str] | None = None
    ):  # pragma: no cover - unused
        _ = executable_path
        _ = args
        raise NotImplementedError

    def list_storage_locations(self):  # pragma: no cover - unused
        return []

    def configure_sync_network_mode(
        self, script_path: str, sync_binary_path: str, mode: str
    ) -> ActionResult:
        self.requests.append((script_path, sync_binary_path, mode))
        return ActionResult(ok=True, message="network_mode_applied")

    def set_local_network_private(self, script_path: str) -> ActionResult:
        self.requests.append((script_path, "", "private"))
        return ActionResult(ok=True, message="network_profile_applied")

    def install_common_wine_dependencies(
        self,
        packages: list[str],
        *,
        winetricks_path: str = "",
        cache_path: str = "",
    ) -> ActionResult:
        self.wine_dep_requests.append(
            [*packages, f"winetricks={winetricks_path}", f"cache={cache_path}"]
        )
        return ActionResult(ok=True, message="wine_dependencies_install_started")

    def install_common_wine_dependencies_for_prefix(
        self,
        prefix_path: str,
        packages: list[str],
        *,
        winetricks_path: str = "",
        cache_path: str = "",
    ) -> ActionResult:
        self.wine_dep_requests.append(
            [
                prefix_path,
                *packages,
                f"winetricks={winetricks_path}",
                f"cache={cache_path}",
            ]
        )
        return ActionResult(
            ok=True,
            message="wine_dependencies_install_started",
            detail=prefix_path,
        )

    def open_wine_prefix_uninstaller(self, prefix_path: str) -> ActionResult:
        self.wine_dep_requests.append([f"uninstaller={prefix_path}"])
        return ActionResult(
            ok=True,
            message="wine_prefix_uninstaller_started",
            detail=prefix_path,
        )


class ApplicationSyncWatchdogTests(unittest.TestCase):
    def test_ouisync_autostarts_before_library_is_initialized_without_starting_resilio(self) -> None:
        app = Application(AppConfig(bind_port=0))
        provider = _FakeDualRouter()
        provider.ouisync.running = False
        app._state.sync_provider = provider  # noqa: SLF001
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
            result = app._run_sync_watchdog_provider_cycle(  # noqa: SLF001
                provider,
                logging.getLogger("test"),
                allow_resilio=False,
                run_game_tasks=False,
            )
            self.assertTrue(result)
            self.assertEqual(provider.ouisync.started, 1)
            self.assertEqual(provider.resilio.started, 0)
        finally:
            app._server.server_close()  # noqa: SLF001 explicit cleanup for bound test server

    def test_sync_stop_pauses_watchdog_and_start_unpauses(self) -> None:
        app = Application(AppConfig(bind_port=0))
        provider = _FakeSyncProvider()
        app._state.sync_provider = provider  # noqa: SLF001
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
            app._sync_stop()  # noqa: SLF001
            self.assertTrue(app._state.sync_watchdog_paused)  # noqa: SLF001
            self.assertFalse(app._state.desired_sync_running)  # noqa: SLF001
            self.assertEqual(provider.stopped, 1)

            app._sync_start()  # noqa: SLF001
            self.assertFalse(app._state.sync_watchdog_paused)  # noqa: SLF001
            self.assertTrue(app._state.desired_sync_running)  # noqa: SLF001
            self.assertEqual(provider.started, 1)
        finally:
            app._server.server_close()  # noqa: SLF001 explicit cleanup for bound test server

    def test_sync_start_logs_provider_exception(self) -> None:
        app = Application(AppConfig(bind_port=0))
        provider = _FailingOuisyncProvider()
        app._state.sync_provider = provider  # noqa: SLF001
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
            with self.assertLogs("src.core.service.app", level="WARNING") as logs:
                status = app._sync_start()  # noqa: SLF001
            self.assertEqual(status["provider"], "ouisync")
            self.assertFalse(status["running"])
            self.assertEqual(status["state"], "failed")
            self.assertEqual(status["last_error"], "sync_launch_failed")
            self.assertTrue(
                any(
                    "sync_start_failed provider=_FailingOuisyncProvider" in line
                    for line in logs.output
                )
            )
            self.assertTrue(
                any(
                    "sync_start_failed provider=ouisync state=failed" in line
                    for line in logs.output
                )
            )
        finally:
            app._server.server_close()  # noqa: SLF001 explicit cleanup for bound test server

    def test_sync_start_logs_partial_provider_error_even_when_running(self) -> None:
        app = Application(AppConfig(bind_port=0))
        provider = _PartialErrorSyncProvider()
        app._state.sync_provider = provider  # noqa: SLF001
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
            with self.assertLogs("src.core.service.app", level="WARNING") as logs:
                status = app._sync_start()  # noqa: SLF001
            self.assertEqual(status["provider"], "dual")
            self.assertTrue(status["running"])
            self.assertEqual(status["state"], "running")
            self.assertEqual(
                status["last_error"], "<urlopen error [Errno 111] Connection refused>"
            )
            self.assertTrue(
                any(
                    "sync_start_failed provider=dual state=running" in line
                    for line in logs.output
                )
            )
        finally:
            app._server.server_close()  # noqa: SLF001 explicit cleanup for bound test server

    def test_sync_watchdog_skips_restart_while_provider_is_starting(self) -> None:
        app = Application(AppConfig(bind_port=0))
        provider = _StartingSyncProvider()
        app._state.sync_provider = provider  # noqa: SLF001
        app._state.user_settings = UserSettings(  # noqa: SLF001
            nickname="Tester",
            theme="dark",
            log_level="WARNING",
            auto_start_sync=True,
            library_path_initialized=True,
            windows_game_drive_letter="D",
            linux_install_path="library",
        )
        app._state.desired_sync_running = True  # noqa: SLF001
        app._state.sync_watchdog_paused = False  # noqa: SLF001
        app._state.sync_watchdog_stop = Event()  # noqa: SLF001

        sleep_calls = {"count": 0}

        def _sleep(_seconds: float) -> None:
            sleep_calls["count"] += 1
            if sleep_calls["count"] >= 1:
                app._state.sync_watchdog_stop.set()  # noqa: SLF001

        try:
            with patch("src.core.service.app.time.sleep", side_effect=_sleep):
                app._run_sync_watchdog()  # noqa: SLF001
            self.assertEqual(provider.started, 0)
            self.assertGreaterEqual(sleep_calls["count"], 1)
        finally:
            app._server.server_close()  # noqa: SLF001 explicit cleanup for bound test server

    def test_sync_watchdog_starts_stopped_resilio_when_ouisync_is_running(self) -> None:
        app = Application(AppConfig(bind_port=0))
        provider = _FakeDualRouter()
        app._state.sync_provider = provider  # noqa: SLF001
        app._state.user_settings = UserSettings(  # noqa: SLF001
            nickname="Tester",
            theme="dark",
            log_level="WARNING",
            auto_start_sync=True,
            library_path_initialized=True,
            windows_game_drive_letter="D",
            linux_install_path="library",
        )
        app._state.desired_sync_running = True  # noqa: SLF001
        app._state.sync_watchdog_paused = False  # noqa: SLF001
        app._state.sync_watchdog_stop = Event()  # noqa: SLF001

        sleep_calls = {"count": 0}

        def _sleep(_seconds: float) -> None:
            sleep_calls["count"] += 1
            app._state.sync_watchdog_stop.set()  # noqa: SLF001

        try:
            with patch("src.core.service.app.time.sleep", side_effect=_sleep):
                app._run_sync_watchdog()  # noqa: SLF001
            self.assertEqual(provider.resilio.started, 1)
            self.assertEqual(provider.ouisync.started, 0)
        finally:
            app._server.server_close()  # noqa: SLF001 explicit cleanup for bound test server

    def test_sync_watchdog_recovers_failed_resilio_with_live_pid(self) -> None:
        app = Application(AppConfig(bind_port=0))
        provider = _FakeDualRouter()
        resilio = _UnhealthyResilioProvider()
        provider.resilio = resilio
        app._state.sync_provider = provider  # noqa: SLF001
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
            result = app._run_sync_watchdog_provider_cycle(  # noqa: SLF001
                provider, logging.getLogger("test")
            )
            self.assertTrue(result)
            self.assertEqual(resilio.recovered, 1)
            self.assertEqual(resilio.started, 0)
        finally:
            app._server.server_close()  # noqa: SLF001 explicit cleanup for bound test server

    def test_set_resilio_network_mode_uses_platform_adapter(self) -> None:
        app = Application(AppConfig(bind_port=0))
        adapter = _FakePlatformAdapter()
        app._state.platform_adapter = adapter  # noqa: SLF001
        try:
            result = app._set_resilio_network_mode({"mode": "lan"})  # noqa: SLF001
            self.assertTrue(result["ok"])
            self.assertEqual(result["message"], "network_mode_applied")
            self.assertEqual(result["mode"], "lan")
            self.assertEqual(len(adapter.requests), 1)
            self.assertEqual(adapter.requests[0][2], "lan")
        finally:
            app._server.server_close()  # noqa: SLF001 explicit cleanup for bound test server

    def test_set_local_network_private_uses_platform_adapter(self) -> None:
        app = Application(AppConfig(bind_port=0))
        adapter = _FakePlatformAdapter()
        app._state.platform_adapter = adapter  # noqa: SLF001
        try:
            result = app._set_local_network_private({})  # noqa: SLF001
            self.assertTrue(result["ok"])
            self.assertEqual(result["message"], "network_profile_applied")
            self.assertEqual(len(adapter.requests), 1)
            self.assertEqual(adapter.requests[0][2], "private")
        finally:
            app._server.server_close()  # noqa: SLF001 explicit cleanup for bound test server

    @unittest.skipIf(os.name == "nt", "asserts Linux filesystem path semantics")
    def test_install_wine_common_dependencies_uses_platform_adapter(self) -> None:
        app = Application(AppConfig(bind_port=0))
        adapter = _FakePlatformAdapter()
        adapter.platform_name = lambda: "linux"  # type: ignore[method-assign]
        app._state.platform_adapter = adapter  # noqa: SLF001
        app._state.user_settings = UserSettings(  # noqa: SLF001
            nickname="Tester",
            theme="dark",
            log_level="WARNING",
            auto_start_sync=True,
            library_path_initialized=True,
            windows_game_drive_letter="D",
            linux_install_path="/srv/LAN",
            linux_windows_runtime="wine",
        )
        try:
            result = app._install_wine_common_dependencies()  # noqa: SLF001
            self.assertTrue(result["ok"])
            self.assertEqual(result["message"], "wine_dependencies_install_started")
            self.assertEqual(len(adapter.wine_dep_requests), 1)
            self.assertIn("d3dx9", adapter.wine_dep_requests[0])
            self.assertIn("vcrun2008", adapter.wine_dep_requests[0])
            self.assertIn(
                "winetricks=/srv/LAN/ng_provider/tools/winetricks/winetricks",
                adapter.wine_dep_requests[0],
            )
            self.assertIn(
                "cache=/srv/LAN/ng_provider/tools/winetricks/cache",
                adapter.wine_dep_requests[0],
            )
        finally:
            app._server.server_close()  # noqa: SLF001 explicit cleanup for bound test server

    @unittest.skipIf(
        os.name == "nt",
        "linux path semantics are not reliable when simulated with pathlib on Windows",
    )
    def test_install_game_proton_common_dependencies_uses_game_prefix(self) -> None:
        app = Application(AppConfig(bind_port=0))
        adapter = _FakePlatformAdapter()
        adapter.platform_name = lambda: "linux"  # type: ignore[method-assign]
        app._state.platform_adapter = adapter  # noqa: SLF001
        app._state.user_settings = UserSettings(  # noqa: SLF001
            nickname="Tester",
            theme="dark",
            log_level="WARNING",
            auto_start_sync=True,
            library_path_initialized=True,
            windows_game_drive_letter="D",
            linux_install_path="/srv/LAN",
            linux_windows_runtime="proton",
        )
        try:
            result = app._install_game_proton_common_dependencies("demo")  # noqa: SLF001
            self.assertTrue(result["ok"])
            self.assertEqual(result["runtime"], "proton")
            self.assertEqual(result["prefix"], "/srv/LAN/demo/.compatdata/proton")
            self.assertEqual(len(adapter.wine_dep_requests), 1)
            self.assertEqual(
                adapter.wine_dep_requests[0][0],
                "/srv/LAN/demo/.compatdata/proton",
            )
            self.assertIn("d3dx9", adapter.wine_dep_requests[0])
            self.assertIn(
                "winetricks=/srv/LAN/ng_provider/tools/winetricks/winetricks",
                adapter.wine_dep_requests[0],
            )
            self.assertIn(
                "cache=/srv/LAN/ng_provider/tools/winetricks/cache",
                adapter.wine_dep_requests[0],
            )
        finally:
            app._server.server_close()  # noqa: SLF001 explicit cleanup for bound test server

    @unittest.skipIf(os.name == "nt", "asserts Linux filesystem path semantics")
    def test_manage_game_prefix_wine_dependencies_supports_wine_runtime(self) -> None:
        app = Application(AppConfig(bind_port=0))
        adapter = _FakePlatformAdapter()
        adapter.platform_name = lambda: "linux"  # type: ignore[method-assign]
        app._state.platform_adapter = adapter  # noqa: SLF001
        app._state.user_settings = UserSettings(  # noqa: SLF001
            nickname="Tester",
            theme="dark",
            log_level="WARNING",
            auto_start_sync=True,
            library_path_initialized=True,
            windows_game_drive_letter="D",
            linux_install_path="/srv/LAN",
            linux_windows_runtime="wine",
        )
        try:
            result = app._manage_game_prefix_wine_dependencies(  # noqa: SLF001
                "demo",
                {"action": "install", "packages": ["d3dx9", "vcrun2019"]},
            )
            self.assertTrue(result["ok"])
            self.assertEqual(result["runtime"], "wine")
            self.assertEqual(result["prefix"], "/srv/LAN/demo/.compatdata/wine")
            self.assertIn("vcrun2019", adapter.wine_dep_requests[0])
        finally:
            app._server.server_close()  # noqa: SLF001 explicit cleanup for bound test server

    @unittest.skipIf(os.name == "nt", "asserts Linux filesystem path semantics")
    def test_manage_game_prefix_wine_dependencies_remove_opens_uninstaller(
        self,
    ) -> None:
        app = Application(AppConfig(bind_port=0))
        adapter = _FakePlatformAdapter()
        adapter.platform_name = lambda: "linux"  # type: ignore[method-assign]
        app._state.platform_adapter = adapter  # noqa: SLF001
        app._state.user_settings = UserSettings(  # noqa: SLF001
            nickname="Tester",
            theme="dark",
            log_level="WARNING",
            auto_start_sync=True,
            library_path_initialized=True,
            windows_game_drive_letter="D",
            linux_install_path="/srv/LAN",
            linux_windows_runtime="proton",
        )
        try:
            result = app._manage_game_prefix_wine_dependencies(  # noqa: SLF001
                "demo",
                {"action": "remove", "packages": ["d3dx9"]},
            )
            self.assertTrue(result["ok"])
            self.assertEqual(result["message"], "wine_prefix_uninstaller_started")
            self.assertEqual(
                adapter.wine_dep_requests[0][0],
                "uninstaller=/srv/LAN/demo/.compatdata/proton",
            )
        finally:
            app._server.server_close()  # noqa: SLF001 explicit cleanup for bound test server

    def test_folder_sync_status_estimates_eta_from_provider_bytes(self) -> None:
        app = Application(AppConfig(bind_port=0))
        app._state.sync_provider = _FakeFolderStatusProvider(  # noqa: SLF001
            {
                "active": True,
                "progress_percent": 20,
                "down_eta": 0,
                "down_speed": 10485760,
                "down_status": 1,
                "downloaded_bytes": 104857600,
                "total_bytes": 524288000,
            }
        )
        try:
            status = app._folder_sync_status(Path("demo"), expected_size_gb=0)  # noqa: SLF001
            self.assertEqual(status["down_eta"], 40)
        finally:
            app._server.server_close()  # noqa: SLF001 explicit cleanup for bound test server

    def test_folder_sync_status_estimates_eta_from_expected_size(self) -> None:
        app = Application(AppConfig(bind_port=0))
        app._state.sync_provider = _FakeFolderStatusProvider(  # noqa: SLF001
            {
                "active": True,
                "progress_percent": 50,
                "down_eta": 0,
                "down_speed": 16777216,
                "down_status": 1,
            }
        )
        try:
            status = app._folder_sync_status(Path("demo"), expected_size_gb=0.5)  # noqa: SLF001
            self.assertEqual(status["down_eta"], 16)
        finally:
            app._server.server_close()  # noqa: SLF001 explicit cleanup for bound test server

    def test_ouisync_lan_management_publishes_selected_games_and_client_catalog(
        self,
    ) -> None:
        import tempfile

        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        library = root / "library"
        (library / "shared").mkdir(parents=True)
        (library / "shared" / "metadata.json").write_text(
            '{"game_id":"shared","title":"Shared"}\n', encoding="utf-8"
        )
        app = Application(
            AppConfig(
                bind_port=0, db_path=str(root / "state.db"), library_path=str(library)
            )
        )
        provider = _ManagedOuisyncProvider()
        app._state.sync_provider = provider  # noqa: SLF001
        app._lan_shares.write(["shared"])  # noqa: SLF001
        app._state.repository = Mock()
        app._state.repository.list_sync_targets.return_value = [
            {"id": "demo", "key": "SECRET", "title": "Demo"}
        ]
        app._state.repository.get_game.return_value = {
            "install_state": "missing",
        }
        app._state.user_settings = UserSettings(  # noqa: SLF001
            nickname="Tester",
            theme="dark",
            log_level="WARNING",
            auto_start_sync=True,
            library_path_initialized=True,
            windows_game_drive_letter="D",
            linux_install_path=str(library),
            lan_mode="server",
        )
        try:
            with (
                patch("src.core.service.app.publish_shared_games") as publish,
                patch.object(app, "_try_import_lan_catalog"),
                patch.object(app, "_ensure_lan_server_settings"),
            ):
                app._ouisync_manage_lan_cycle()  # noqa: SLF001
            self.assertEqual(provider.approved, [])
            self.assertEqual(provider.folder_calls, [])
            self.assertEqual(
                provider.lan_publish_calls, [str(library / "locallansync")]
            )
            self.assertEqual(publish.call_args.args[0], library)
            self.assertEqual(
                publish.call_args.args[1],
                [{"id": "shared", "path": str(library / "shared")}],
            )
            publish.call_args.kwargs["ouisync_publisher"](str(library / "shared"))
            self.assertEqual(
                provider.lan_repository_paths,
                [
                    str(library / "locallansync" / ".ouisync" / "lan-repository"),
                    str(library / "shared" / ".ouisync" / "lan-repository"),
                ],
            )
            self.assertEqual(
                provider.lan_reconcile_calls,
                [
                    [
                        str(library / "locallansync" / ".ouisync" / "lan-repository"),
                        str(library / "shared" / ".ouisync" / "lan-repository"),
                    ]
                ],
            )
        finally:
            app._server.server_close()  # noqa: SLF001 explicit cleanup for bound test server

        app._state.user_settings = UserSettings(  # noqa: SLF001
            nickname="Tester",
            theme="dark",
            log_level="WARNING",
            auto_start_sync=True,
            library_path_initialized=True,
            windows_game_drive_letter="D",
            linux_install_path=str(library),
            lan_mode="client",
        )
        try:
            with patch.object(app, "_ouisync_lan_catalog_cycle") as catalog_cycle:
                app._ouisync_manage_lan_cycle()  # noqa: SLF001
                catalog_cycle.assert_called_once()
            self.assertEqual(provider.paused, [])
        finally:
            app._server.server_close()  # noqa: SLF001 explicit cleanup for bound test server

    def test_app_stop_disables_watchdog_restart_before_sync_stop(self) -> None:
        app = Application(AppConfig(bind_port=0))
        provider = _FakeSyncProvider()
        app._state.sync_provider = provider  # noqa: SLF001
        app._state.desired_sync_running = True  # noqa: SLF001
        app._state.sync_watchdog_paused = False  # noqa: SLF001
        try:
            with (
                patch.object(app._server, "shutdown", return_value=None),  # noqa: SLF001
                patch.object(app._server, "server_close", return_value=None),  # noqa: SLF001
                patch(
                    "src.core.platform.browser.close_browser_app_mode",
                    return_value=True,
                ),
            ):
                app.stop()
            self.assertFalse(app._state.desired_sync_running)  # noqa: SLF001
            self.assertTrue(app._state.sync_watchdog_paused)  # noqa: SLF001
            self.assertEqual(provider.stopped, 1)
        finally:
            app._server.server_close()  # noqa: SLF001 explicit cleanup for bound test server


if __name__ == "__main__":
    unittest.main()
