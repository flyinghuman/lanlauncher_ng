"""Tests for configuration loading behavior."""

from __future__ import annotations

import json
import os
import platform
import tempfile
import unittest
from pathlib import Path

from src.core.config.loader import AppConfig, load_config


class ConfigLoaderTests(unittest.TestCase):
    def setUp(self) -> None:
        self._env_backup = dict(os.environ)

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self._env_backup)

    def test_defaults_without_file(self) -> None:
        cfg = load_config(path="nonexistent.json")
        expected_sync_binary_path = (
            "vendor/bin/windows-amd64/btsync.exe"
            if platform.system().lower().startswith("win")
            else "vendor/bin/linux-x64/rslsync"
        )
        expected_ouisync_binary_path = (
            "vendor/bin/windows-amd64/ouisync.exe"
            if platform.system().lower().startswith("win")
            else "vendor/bin/linux-x64/ouisync"
        )
        self.assertEqual(cfg.sync_provider, AppConfig.sync_provider)
        self.assertEqual(cfg.sync_binary_path, expected_sync_binary_path)
        self.assertEqual(cfg.ouisync_binary_path, expected_ouisync_binary_path)
        self.assertEqual(cfg.sync_startup_retry_seconds, AppConfig.sync_startup_retry_seconds)

    def test_loads_file_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "core.json"
            file_path.write_text(
                json.dumps(
                    {
                        "bind_host": "0.0.0.0",
                        "bind_port": 19090,
                        "db_path": "tmp/test.db",
                        "legacy_db_path": "old/game.db",
                        "library_path": "tmp/library",
                        "log_level": "debug",
                        "default_locale": "de",
                        "settings_path": "tmp/settings.json",
                        "default_extra_sync_items_path": "tmp/bootstrap.json",
                        "optional_extra_sync_items_path": "tmp/optional-bootstrap.json",
                        "feature_flags_path": "tmp/feature-flags.json",
                        "update_manifest_path": "tmp/ng_provider/update-manifest.json",
                        "windows_updater_script_path": "scripts/wrappers/windows/custom-updater.ps1",
                        "linux_updater_script_path": "scripts/wrappers/linux/custom-updater.sh",
                    }
                ),
                encoding="utf-8",
            )

            cfg = load_config(str(file_path))
            self.assertEqual(cfg.bind_host, "0.0.0.0")
            self.assertEqual(cfg.bind_port, 19090)
            self.assertEqual(cfg.db_path, "tmp/test.db")
            self.assertEqual(cfg.legacy_db_path, "old/game.db")
            self.assertEqual(cfg.library_path, "tmp/library")
            self.assertEqual(cfg.log_level, "DEBUG")
            self.assertEqual(cfg.default_locale, "de")
            self.assertEqual(cfg.settings_path, "tmp/settings.json")
            self.assertEqual(cfg.default_extra_sync_items_path, "tmp/bootstrap.json")
            self.assertEqual(
                cfg.optional_extra_sync_items_path, "tmp/optional-bootstrap.json"
            )
            self.assertEqual(cfg.feature_flags_path, "tmp/feature-flags.json")
            self.assertEqual(
                cfg.update_manifest_path, "tmp/ng_provider/update-manifest.json"
            )
            self.assertEqual(
                cfg.windows_updater_script_path,
                "scripts/wrappers/windows/custom-updater.ps1",
            )
            self.assertEqual(
                cfg.linux_updater_script_path,
                "scripts/wrappers/linux/custom-updater.sh",
            )

    def test_critical_log_level_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "core.json"
            file_path.write_text(json.dumps({"log_level": "critical"}), encoding="utf-8")

            cfg = load_config(str(file_path))
            self.assertEqual(cfg.log_level, "CRITICAL")

    def test_env_overrides_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "core.json"
            file_path.write_text(json.dumps({"bind_port": 18080}), encoding="utf-8")

            os.environ["LLNG_BIND_PORT"] = "20001"
            os.environ["LLNG_UPDATE_MANIFEST_PATH"] = "sync/update-manifest.json"
            os.environ["LLNG_FEATURE_FLAGS_PATH"] = "config/flags-override.json"
            cfg = load_config(str(file_path))
            self.assertEqual(cfg.bind_port, 20001)
            self.assertEqual(cfg.update_manifest_path, "sync/update-manifest.json")
            self.assertEqual(cfg.feature_flags_path, "config/flags-override.json")

    def test_legacy_syncthing_provider_setting_migrates_to_ouisync(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "core.json"
            file_path.write_text(
                json.dumps({"sync_provider": "syncthing"}), encoding="utf-8"
            )

            cfg = load_config(str(file_path))
            expected_sync_binary_path = (
                "vendor/bin/windows-amd64/btsync.exe"
                if platform.system().lower().startswith("win")
                else "vendor/bin/linux-x64/rslsync"
            )
            self.assertEqual(cfg.sync_provider, "ouisync")
            self.assertEqual(cfg.sync_binary_path, expected_sync_binary_path)
            self.assertEqual(cfg.ouisync_binary_path, (
                "vendor/bin/windows-amd64/ouisync.exe"
                if platform.system().lower().startswith("win")
                else "vendor/bin/linux-x64/ouisync"
            ))


if __name__ == "__main__":
    unittest.main()
