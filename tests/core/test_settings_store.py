"""Tests for persisted user settings handling."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.core.service.settings_store import SettingsStore, UserSettings


class SettingsStoreTests(unittest.TestCase):
    @staticmethod
    def _defaults(tmp: str) -> UserSettings:
        return UserSettings(
            nickname="",
            theme="dark",
            log_level="WARNING",
            auto_start_sync=True,
            library_path_initialized=False,
            windows_game_drive_letter="D",
            linux_install_path=str(Path(tmp) / "library"),
            sync_only_mode=False,
            lan_mode="client",
        )

    def test_load_defaults_when_file_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            defaults = self._defaults(tmp)
            store = SettingsStore(str(Path(tmp) / "settings.json"))
            loaded = store.load(defaults)
            self.assertEqual(loaded, defaults)

    def test_merge_and_validate_updates_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            current = self._defaults(tmp)
            store = SettingsStore(str(Path(tmp) / "settings.json"))
            merged = store.merge_and_validate(
                current,
                {
                    "nickname": "Alice",
                    "theme": "light",
                    "log_level": "INFO",
                    "auto_start_sync": False,
                    "sync_only_mode": True,
                    "library_path_initialized": True,
                    "windows_game_drive_letter": "e",
                    "linux_install_path": "/srv/LAN",
                    "linux_windows_runtime": "proton",
                    "linux_proton_path": "/opt/steam/proton",
                    "linux_proton_ge_path": "/opt/proton-ge/proton",
                    "ouisync_storage_path": "/srv/ouisync",
                    "syncthing_cluster_role": "server",
                },
            )
            self.assertEqual(merged.nickname, "Alice")
            self.assertEqual(merged.theme, "light")
            self.assertEqual(merged.log_level, "INFO")
            self.assertFalse(merged.auto_start_sync)
            self.assertTrue(merged.sync_only_mode)
            self.assertTrue(merged.library_path_initialized)
            self.assertEqual(merged.windows_game_drive_letter, "E")
            self.assertEqual(merged.linux_install_path, "/srv/LAN")
            self.assertEqual(merged.linux_windows_runtime, "proton")
            self.assertEqual(merged.linux_proton_path, "/opt/steam/proton")
            self.assertEqual(merged.linux_proton_ge_path, "/opt/proton-ge/proton")
            self.assertEqual(merged.ouisync_storage_path, "/srv/ouisync")
            self.assertEqual(merged.lan_mode, "server")

    def test_storage_fallback_paths_are_persisted_but_not_user_editable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            current = self._defaults(tmp)
            current = current.__class__(
                **{
                    **current.__dict__,
                    "ouisync_storage_fallback_paths": ["/srv/old-ouisync"],
                }
            )
            store = SettingsStore(str(Path(tmp) / "settings.json"))
            merged = store.merge_and_validate(
                current,
                {
                    "ouisync_storage_path": "/srv/new-ouisync",
                    "ouisync_storage_fallback_paths": ["/untrusted/path"],
                },
            )
            self.assertEqual(
                merged.ouisync_storage_fallback_paths, ["/srv/old-ouisync"]
            )
            store.save(merged)
            loaded = store.load(self._defaults(tmp))
            self.assertEqual(
                loaded.ouisync_storage_fallback_paths, ["/srv/old-ouisync"]
            )

    def test_critical_log_level_is_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            current = self._defaults(tmp)
            store = SettingsStore(str(Path(tmp) / "settings.json"))
            merged = store.merge_and_validate(current, {"log_level": "critical"})
            self.assertEqual(merged.log_level, "CRITICAL")

    def test_invalid_drive_letter_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            current = self._defaults(tmp)
            store = SettingsStore(str(Path(tmp) / "settings.json"))
            with self.assertRaises(ValueError):
                store.merge_and_validate(current, {"windows_game_drive_letter": "12"})

    def test_invalid_log_level_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            current = self._defaults(tmp)
            store = SettingsStore(str(Path(tmp) / "settings.json"))
            with self.assertRaises(ValueError):
                store.merge_and_validate(current, {"log_level": "TRACE"})

    def test_invalid_linux_runtime_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            current = self._defaults(tmp)
            store = SettingsStore(str(Path(tmp) / "settings.json"))
            with self.assertRaises(ValueError):
                store.merge_and_validate(current, {"linux_windows_runtime": "steam"})

    def test_invalid_syncthing_cluster_role_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            current = self._defaults(tmp)
            store = SettingsStore(str(Path(tmp) / "settings.json"))
            with self.assertRaises(ValueError):
                store.merge_and_validate(
                    current, {"syncthing_cluster_role": "master"}
                )


if __name__ == "__main__":
    unittest.main()
