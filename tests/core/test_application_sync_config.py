"""Tests for sync config persistence in Application."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from src.core.config.loader import AppConfig
from src.core.catalog.repository import CatalogRepository
from src.core.db.store import open_database
from src.core.service.app import Application
from src.core.service.settings_store import SettingsStore, UserSettings


class ApplicationSyncConfigTests(unittest.TestCase):
    class _PlatformAdapter:
        def platform_name(self) -> str:
            return "linux"

        def validate_storage_path(self, raw_path: str):
            _ = raw_path
            return SimpleNamespace(ok=True, message="ok")

    class _OuisyncProviderStub:
        def __init__(self) -> None:
            self.library_paths: list[str] = []
            self.cluster_roles: list[str] = []
            self.folder_inventories: list[dict] = []
            self.folder_updates: list[tuple[str, bool]] = []

        def set_library_path(self, library_path: str) -> None:
            self.library_paths.append(library_path)

        def set_cluster_role(self, role: str) -> None:
            self.cluster_roles.append(role)

        def list_managed_folders(self) -> dict:
            inventory = {
                "root_path": "/srv/LAN",
                "folders": [
                    {
                        "name": "alpha",
                        "path": "/srv/LAN/alpha",
                        "folder_id": "alpha",
                        "configured": True,
                        "shared": True,
                        "paused": False,
                        "type": "receiveonly",
                    }
                ],
            }
            self.folder_inventories.append(inventory)
            return inventory

        def set_folder_shared(self, folder_path: str, shared: bool) -> tuple[bool, str]:
            self.folder_updates.append((folder_path, shared))
            return True, "ouisync_folder_configured"

    def test_persist_sync_config_normalizes_paths_and_creates_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "config" / "resilio" / "config.json"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(
                json.dumps(
                    {
                        "storage_path": "data/sync",
                        "pid_file": "data/sync/rslsync.pid",
                        "lanlauncher_library_path": "D:/LAN",
                    }
                ),
                encoding="utf-8",
            )

            app = Application(
                AppConfig(
                    bind_port=0,
                    sync_provider="resilio",
                    sync_config_path=str(config_path),
                )
            )
            previous_cwd = Path.cwd()
            try:
                os.chdir(root)
                ok = app._persist_resilio_library_path("D:/LAN")  # noqa: SLF001 private helper
            finally:
                os.chdir(previous_cwd)
                app._server.server_close()  # noqa: SLF001 explicit cleanup for bound test server

            self.assertTrue(ok)
            persisted = json.loads(config_path.read_text(encoding="utf-8"))
            expected_storage = str((root / "data" / "sync").resolve())
            expected_pid = str((root / "data" / "sync" / "rslsync.pid").resolve())
            self.assertEqual(persisted["storage_path"], expected_storage)
            self.assertEqual(persisted["pid_file"], expected_pid)
            self.assertNotIn("lanlauncher_library_path", persisted)
            self.assertTrue(Path(expected_storage).exists())
            self.assertTrue(Path(expected_pid).parent.exists())

    def test_persist_sync_config_rewrites_windows_absolute_paths_on_linux(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "config" / "resilio" / "config.json"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(
                json.dumps(
                    {
                        "storage_path": r"P:\workspace\LANLauncherNG\data\sync",
                        "pid_file": r"P:\workspace\LANLauncherNG\data\sync\rslsync.pid",
                    }
                ),
                encoding="utf-8",
            )

            app = Application(
                AppConfig(
                    bind_port=0,
                    sync_provider="resilio",
                    sync_config_path=str(config_path),
                    platform_override="Linux",
                )
            )
            previous_cwd = Path.cwd()
            try:
                os.chdir(root)
                ok = app._persist_resilio_library_path("/mnt/lan")  # noqa: SLF001 private helper
            finally:
                os.chdir(previous_cwd)
                app._server.server_close()  # noqa: SLF001 explicit cleanup for bound test server

            self.assertTrue(ok)
            persisted = json.loads(config_path.read_text(encoding="utf-8"))
            expected_storage = str((root / "data" / "sync").resolve())
            expected_pid = str((root / "data" / "sync" / "rslsync.pid").resolve())
            self.assertEqual(persisted["storage_path"], expected_storage)
            self.assertEqual(persisted["pid_file"], expected_pid)

    def test_persist_sync_config_rewrites_stale_absolute_dev_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "config" / "resilio" / "config.json"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(
                json.dumps(
                    {
                        "storage_path": "/srv/stale-dev-checkout/LANLauncherNG/data/sync",
                        "pid_file": "/srv/stale-dev-checkout/LANLauncherNG/data/sync/rslsync.pid",
                    }
                ),
                encoding="utf-8",
            )

            app = Application(
                AppConfig(
                    bind_port=0,
                    sync_provider="resilio",
                    sync_config_path=str(config_path),
                )
            )
            try:
                ok = app._persist_resilio_library_path("/mnt/lan")  # noqa: SLF001 private helper
            finally:
                app._server.server_close()  # noqa: SLF001 explicit cleanup for bound test server

            self.assertTrue(ok)
            persisted = json.loads(config_path.read_text(encoding="utf-8"))
            expected_storage = str((root / "data" / "sync").resolve())
            expected_pid = str((root / "data" / "sync" / "rslsync.pid").resolve())
            self.assertEqual(persisted["storage_path"], expected_storage)
            self.assertEqual(persisted["pid_file"], expected_pid)

    def test_persist_sync_config_is_noop_for_ouisync_provider(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "config" / "resilio" / "config.json"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(json.dumps({"storage_path": "unchanged"}), encoding="utf-8")

            app = Application(
                AppConfig(
                    bind_port=0,
                    sync_provider="ouisync",
                    sync_config_path=str(config_path),
                )
            )
            try:
                ok = app._persist_resilio_library_path("/mnt/lan")  # noqa: SLF001 private helper
            finally:
                app._server.server_close()  # noqa: SLF001 explicit cleanup for bound test server

            self.assertTrue(ok)
            self.assertEqual(
                json.loads(config_path.read_text(encoding="utf-8"))["storage_path"],
                "unchanged",
            )

    def test_settings_update_saves_lan_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings_path = root / "settings.json"
            app = Application(AppConfig(bind_port=0))
            provider = self._OuisyncProviderStub()
            app._state.sync_provider = provider  # noqa: SLF001
            app._state.platform_adapter = self._PlatformAdapter()  # noqa: SLF001
            app._state.settings_store = SettingsStore(str(settings_path))  # noqa: SLF001
            app._state.user_settings = UserSettings(  # noqa: SLF001
                nickname="Tester",
                theme="dark",
                log_level="WARNING",
                auto_start_sync=True,
                library_path_initialized=True,
                windows_game_drive_letter="D",
                linux_install_path=str(root / "LAN"),
                lan_mode="client",
            )
            try:
                result = app._settings_update(  # noqa: SLF001
                    {
                        "nickname": "Tester",
                        "theme": "dark",
                        "log_level": "WARNING",
                        "auto_start_sync": True,
                        "sync_only_mode": False,
                        "library_path_initialized": True,
                        "windows_game_drive_letter": "D",
                        "linux_install_path": str(root / "LAN"),
                        "lan_mode": "server",
                    }
                )
            finally:
                app._server.server_close()  # noqa: SLF001 explicit cleanup for bound test server

            self.assertTrue(result["ok"])
            self.assertEqual(provider.library_paths, [])
            self.assertEqual(provider.cluster_roles, [])

    def test_ouisync_paths_reuse_repositories_from_previous_storage_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            library = root / "library"
            previous = root / "previous-store"
            current = root / "current-store"
            game_repo = previous / "demo" / ".ouisync" / "demo.ouisyncdb"
            lan_repo = previous / "shared" / ".ouisync" / "lan-repository.ouisyncdb"
            game_repo.parent.mkdir(parents=True)
            lan_repo.parent.mkdir(parents=True)
            game_repo.write_bytes(b"db")
            lan_repo.write_bytes(b"db")

            app = Application(
                AppConfig(bind_port=0, library_path=str(library), db_path=str(root / "app.db"))
            )
            self.addCleanup(app._server.server_close)
            app._state.platform_adapter = self._PlatformAdapter()  # noqa: SLF001
            app._state.user_settings = UserSettings(  # noqa: SLF001
                nickname="Tester",
                theme="dark",
                log_level="WARNING",
                auto_start_sync=True,
                library_path_initialized=True,
                windows_game_drive_letter="D",
                linux_install_path=str(library),
                ouisync_storage_path=str(current),
                ouisync_storage_fallback_paths=[str(previous)],
            )

            self.assertEqual(
                app._ouisync_game_repository_path("demo"),  # noqa: SLF001
                previous / "demo" / ".ouisync" / "demo",
            )
            self.assertEqual(
                app._ouisync_lan_repository_path(str(library / "shared")),  # noqa: SLF001
                previous / "shared" / ".ouisync" / "lan-repository",
            )

    def test_settings_update_retains_previous_ouisync_storage_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old_root = root / "old-store"
            new_root = root / "new-store"
            settings_path = root / "settings.json"
            app = Application(AppConfig(bind_port=0, library_path=str(root / "library")))
            self.addCleanup(app._server.server_close)
            app._state.settings_store = SettingsStore(str(settings_path))  # noqa: SLF001
            app._state.platform_adapter = self._PlatformAdapter()  # noqa: SLF001
            app._state.user_settings = UserSettings(  # noqa: SLF001
                nickname="Tester",
                theme="dark",
                log_level="WARNING",
                auto_start_sync=True,
                library_path_initialized=True,
                windows_game_drive_letter="D",
                linux_install_path=str(root / "library"),
                ouisync_storage_path=str(old_root),
            )

            result = app._settings_update(  # noqa: SLF001
                {"ouisync_storage_path": str(new_root)}
            )

            self.assertTrue(result["ok"])
            self.assertEqual(
                app._state.user_settings.ouisync_storage_fallback_paths,  # noqa: SLF001
                [str(old_root.resolve())],
            )
            persisted = SettingsStore(str(settings_path)).load(app._state.user_settings)
            self.assertEqual(
                persisted.ouisync_storage_fallback_paths, [str(old_root.resolve())]
            )

    def test_lan_folder_inventory_and_share_selection_flow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            library = root / "LAN"
            folder = library / "alpha"
            folder.mkdir(parents=True)
            db = open_database(str(root / "app.db"))
            self.addCleanup(db.connection.close)
            app = Application(AppConfig(bind_port=0, library_path=str(library), db_path=str(root / "app.db")))
            app._state.repository = CatalogRepository(db.connection, root / "metadata")  # noqa: SLF001
            app._state.platform_adapter = self._PlatformAdapter()  # noqa: SLF001
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
                inventory = app._lan_game_inventory_read()  # noqa: SLF001
                update = app._lan_game_share_update(  # noqa: SLF001
                    {"folder_path": str(folder), "shared": True}
                )
            finally:
                app._server.server_close()  # noqa: SLF001 explicit cleanup for bound test server
                db.connection.close()

            self.assertEqual(inventory["root_path"], str(library))
            self.assertEqual(len(inventory["folders"]), 1)
            self.assertTrue(update["ok"])
            self.assertEqual(update["lan"]["root_path"], str(library))
            self.assertTrue(update["lan"]["folders"][0]["shared"])


if __name__ == "__main__":
    unittest.main()
