"""Tests for application-level default values."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from src.core.config.loader import AppConfig
from src.core.service.app import (
    Application,
    apply_linux_proton_autodiscovery,
    default_linux_install_path,
    discover_steam_proton_binaries,
    local_docs_file_path,
    local_docs_file_url,
    runtime_requirements_hint,
)
from src.core.service.settings_store import UserSettings
from src.core.sync.provider import SyncStatus


class ApplicationDefaultsTests(unittest.TestCase):
    def _sample_settings(
        self, proton_path: str = "", proton_ge_path: str = ""
    ) -> UserSettings:
        return UserSettings(
            nickname="",
            theme="dark",
            log_level="INFO",
            auto_start_sync=True,
            library_path_initialized=False,
            windows_game_drive_letter="C",
            linux_install_path="/media/library",
            linux_windows_runtime="wine",
            linux_proton_path=proton_path,
            linux_proton_ge_path=proton_ge_path,
        )

    def test_linux_default_install_path_uses_media_library(self) -> None:
        self.assertEqual(
            default_linux_install_path("linux", "data/library"),
            "/media/library",
        )

    def test_non_linux_default_install_path_uses_config_value(self) -> None:
        self.assertEqual(
            default_linux_install_path("windows", "data/library"),
            "data/library",
        )

    def test_linux_runtime_requirements_hint_mentions_expected_packages(self) -> None:
        hint = runtime_requirements_hint("linux")
        self.assertIn("python3", hint)
        self.assertIn("unrar", hint)
        self.assertIn("winetricks", hint)
        self.assertIn("gnome-terminal", hint)
        self.assertIn("xterm", hint)
        self.assertIn("konsole", hint)

    def test_discover_steam_proton_binaries_prefers_highest_version(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp)

            proton_80 = (
                home
                / ".local"
                / "share"
                / "Steam"
                / "steamapps"
                / "common"
                / "Proton 8.0"
                / "proton"
            )
            proton_90 = (
                home
                / ".local"
                / "share"
                / "Steam"
                / "steamapps"
                / "common"
                / "Proton 9.0"
                / "proton"
            )
            proton_experimental = (
                home
                / ".local"
                / "share"
                / "Steam"
                / "steamapps"
                / "common"
                / "Proton - Experimental"
                / "proton"
            )
            ge_95 = (
                home
                / ".steam"
                / "root"
                / "compatibilitytools.d"
                / "GE-Proton9-5"
                / "proton"
            )
            ge_1032 = (
                home
                / ".steam"
                / "root"
                / "compatibilitytools.d"
                / "GE-Proton10-32"
                / "proton"
            )

            for script in (
                proton_80,
                proton_90,
                proton_experimental,
                ge_95,
                ge_1032,
            ):
                script.parent.mkdir(parents=True, exist_ok=True)
                script.write_text("#!/bin/sh\n", encoding="utf-8")

            proton_path, proton_ge_path = discover_steam_proton_binaries(home)
            self.assertEqual(proton_path, str(proton_90))
            self.assertEqual(proton_ge_path, str(ge_1032))

    def test_apply_linux_proton_autodiscovery_fills_only_missing_values(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            proton_90 = (
                home
                / ".local"
                / "share"
                / "Steam"
                / "steamapps"
                / "common"
                / "Proton 9.0"
                / "proton"
            )
            ge_1032 = (
                home
                / ".steam"
                / "root"
                / "compatibilitytools.d"
                / "GE-Proton10-32"
                / "proton"
            )
            proton_90.parent.mkdir(parents=True, exist_ok=True)
            ge_1032.parent.mkdir(parents=True, exist_ok=True)
            proton_90.write_text("#!/bin/sh\n", encoding="utf-8")
            ge_1032.write_text("#!/bin/sh\n", encoding="utf-8")

            manual_proton = "/opt/manual/proton"
            settings = self._sample_settings(proton_path=manual_proton)
            merged, changed = apply_linux_proton_autodiscovery(settings, "linux", home)

            self.assertTrue(changed)
            self.assertEqual(merged.linux_proton_path, manual_proton)
            self.assertEqual(merged.linux_proton_ge_path, str(ge_1032))

    def test_apply_linux_proton_autodiscovery_skips_non_linux_platform(self) -> None:
        settings = self._sample_settings()
        merged, changed = apply_linux_proton_autodiscovery(settings, "windows")
        self.assertFalse(changed)
        self.assertEqual(merged, settings)

    def test_local_docs_file_url_returns_file_uri_when_site_exists(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            site_index = root / "site" / "index.html"
            site_index.parent.mkdir(parents=True, exist_ok=True)
            site_index.write_text("<html></html>", encoding="utf-8")

            url = local_docs_file_url(root)
            self.assertTrue(url.startswith("file:"))
            self.assertIn("site", url)
            self.assertIn("index.html", url)

    def test_local_docs_file_url_returns_empty_when_site_missing(self) -> None:
        with TemporaryDirectory() as tmp:
            self.assertEqual(local_docs_file_url(Path(tmp)), "")

    def test_local_docs_file_path_returns_path_when_site_exists(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            site_index = root / "site" / "index.html"
            site_index.parent.mkdir(parents=True, exist_ok=True)
            site_index.write_text("<html></html>", encoding="utf-8")
            self.assertEqual(
                Path(local_docs_file_path(root)).resolve(strict=False),
                site_index.resolve(strict=False),
            )

    def test_local_docs_file_path_returns_empty_when_site_missing(self) -> None:
        with TemporaryDirectory() as tmp:
            self.assertEqual(local_docs_file_path(Path(tmp)), "")

    def test_provider_interfaces_payload_includes_embed_urls(self) -> None:
        app = Application(AppConfig(bind_port=0))

        class _Provider:
            def __init__(self, title: str, url: str):
                self._title = title
                self._url = url

            def status(self) -> SyncStatus:
                return SyncStatus(
                    provider=self._title.lower(),
                    running=True,
                    state="running",
                )

            def web_ui_url(self) -> str:
                return self._url

        class _Router:
            def provider_for_type(self, provider_type: str):
                if provider_type == "ouisync":
                    return _Provider("Ouisync", "")
                return _Provider("Resilio", "http://127.0.0.1:13338/gui/")

        try:
            app._state.sync_provider = _Router()  # noqa: SLF001
            payload = app._provider_interfaces_payload()  # noqa: SLF001
            self.assertEqual(payload[0]["provider_type"], "ouisync")
            self.assertEqual(payload[0]["title"], "Ouisync")
            self.assertTrue(payload[0]["available"])
            self.assertEqual(payload[1]["provider_type"], "resilio")
            self.assertEqual(
                payload[1]["open_url"], "http://127.0.0.1:13338/gui/"
            )
            self.assertIsNone(payload[1]["pid"])
            self.assertEqual(payload[1]["last_error"], "")
        finally:
            if app._state.database is not None:  # noqa: SLF001
                app._state.database.connection.close()  # noqa: SLF001

    def test_log_timeline_infers_provider_sources_from_logger_names(self) -> None:
        app = Application(AppConfig(bind_port=0))

        class _Provider:
            def __init__(self, name: str):
                self._name = name

            def debug_logs(self, limit: int = 200) -> list[dict]:
                _ = limit
                return [
                    {
                        "ts": "2026-06-17T10:00:01+00:00",
                        "msg": f"{self._name} log line",
                    }
                ]

        class _Router:
            def provider_for_type(self, provider_type: str):
                return _Provider(str(provider_type or "ouisync"))

        try:
            app._state.sync_provider = _Router()  # noqa: SLF001
            with patch(
                "src.core.service.app.get_recent_logs",
                return_value=[
                    {
                        "ts": "2026-06-17T10:00:00+00:00",
                        "level": "INFO",
                        "logger": "root",
                        "msg": "launcher root line",
                    },
                    {
                        "ts": "2026-06-17T10:00:00+00:00",
                        "level": "INFO",
                        "logger": "src.core.main",
                        "msg": "launcher line",
                    },
                    {
                        "ts": "2026-06-17T10:00:00+00:00",
                        "level": "INFO",
                        "logger": "src.core.sync.resilio_provider",
                        "msg": "resilio launcher line",
                    },
                ],
            ):
                entries = app._collect_log_timeline(10)  # noqa: SLF001

            sources = [entry["source"] for entry in entries]
            self.assertIn("lanlauncherng", sources)
            self.assertIn("resilio", sources)
            self.assertIn("ouisync", sources)
        finally:
            if app._state.database is not None:  # noqa: SLF001
                app._state.database.connection.close()  # noqa: SLF001

    def test_ouisync_human_log_timestamps_join_the_sorted_timeline(self) -> None:
        app = Application(AppConfig(bind_port=0))

        class _Provider:
            def __init__(self, entries):
                self.entries = entries

            def debug_logs(self, limit: int = 200) -> list[dict]:
                return self.entries[-limit:]

        class _Router:
            def provider_for_type(self, provider_type: str):
                if provider_type == "ouisync":
                    return _Provider(
                        [
                            {
                                "provider": "ouisync",
                                "msg": "2026-06-17T10:00:01.000000Z INFO  Ouisync earlier",
                            },
                            {
                                "provider": "ouisync",
                                "msg": "2026-06-17T10:00:03.000000Z WARN  Ouisync later",
                            },
                        ]
                    )
                return _Provider(
                    [
                        {
                            "provider": "resilio",
                            "ts": "2026-06-17T10:00:02+00:00",
                            "level": "INFO",
                            "msg": "Resilio middle",
                        }
                    ]
                )

        try:
            app._state.sync_provider = _Router()  # noqa: SLF001
            with patch(
                "src.core.service.app.get_recent_logs",
                return_value=[
                    {
                        "ts": "2026-06-17T10:00:00+00:00",
                        "level": "INFO",
                        "logger": "src.core.main",
                        "msg": "LLNG first",
                    }
                ],
            ):
                entries = app._collect_log_timeline(10)  # noqa: SLF001

            self.assertEqual(
                [entry["msg"] for entry in entries],
                ["LLNG first", "Ouisync earlier", "Resilio middle", "Ouisync later"],
            )
            self.assertEqual(entries[1]["ts"], "2026-06-17T10:00:01.000000Z")
            self.assertEqual(entries[1]["level"], "INFO")
            self.assertEqual(entries[3]["level"], "WARN")
        finally:
            if app._state.database is not None:  # noqa: SLF001
                app._state.database.connection.close()  # noqa: SLF001

    def test_log_timeline_reads_persistent_app_log_file(self) -> None:
        with TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "log.txt"
            log_path.write_text(
                json.dumps(
                    {
                        "ts": "2026-06-17T10:00:00+00:00",
                        "level": "INFO",
                        "logger": "src.core.main",
                        "msg": "persistent launcher line",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            app = Application(AppConfig(bind_port=0, log_path=str(log_path)))

            class _Provider:
                def debug_logs(self, limit: int = 200) -> list[dict]:
                    _ = limit
                    return [
                        {
                            "ts": "2026-06-17 14:00:00",
                            "level": "INF",
                            "msg": "provider file line",
                        }
                    ]

            try:
                app._state.sync_provider = _Provider()  # noqa: SLF001
                with patch("src.core.service.app.get_recent_logs", return_value=[]):
                    entries = app._collect_log_timeline(10)  # noqa: SLF001

                self.assertEqual(entries[0]["source"], "lanlauncherng")
                self.assertEqual(entries[0]["msg"], "persistent launcher line")
                self.assertEqual(entries[1]["source"], "resilio")
                self.assertEqual(entries[1]["msg"], "provider file line")
            finally:
                if app._state.database is not None:  # noqa: SLF001
                    app._state.database.connection.close()  # noqa: SLF001

    def test_log_timeline_deduplicates_app_file_and_memory_entries(self) -> None:
        with TemporaryDirectory() as tmp:
            payload = {
                "ts": "2026-06-17T10:00:00+00:00",
                "level": "INFO",
                "logger": "src.core.main",
                "msg": "duplicate launcher line",
            }
            log_path = Path(tmp) / "log.txt"
            log_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
            app = Application(AppConfig(bind_port=0, log_path=str(log_path)))

            try:
                with patch("src.core.service.app.get_recent_logs", return_value=[payload]):
                    entries = app._collect_log_timeline(10)  # noqa: SLF001

                matches = [
                    entry for entry in entries if entry["msg"] == "duplicate launcher line"
                ]
                self.assertEqual(len(matches), 1)
                self.assertEqual(matches[0]["source"], "lanlauncherng")
            finally:
                if app._state.database is not None:  # noqa: SLF001
                    app._state.database.connection.close()  # noqa: SLF001

    def test_log_timeline_deduplicates_mirrored_resilio_process_output(self) -> None:
        app = Application(AppConfig(bind_port=0))

        class _Provider:
            def debug_logs(self, limit: int = 200) -> list[dict]:
                _ = limit
                return [
                    {
                        "ts": "2026-06-17T10:00:00.500000+00:00",
                        "level": "WARNING",
                        "msg": "[stderr] Can't lock pid file",
                    }
                ]

        try:
            app._state.sync_provider = _Provider()  # noqa: SLF001
            with patch(
                "src.core.service.app.get_recent_logs",
                return_value=[
                    {
                        "ts": "2026-06-17T10:00:00.500000+00:00",
                        "level": "WARNING",
                        "logger": "src.core.sync.resilio_provider",
                        "msg": "sync_process_stderr=Can't lock pid file",
                    }
                ],
            ):
                entries = app._collect_log_timeline(10)  # noqa: SLF001

            matches = [
                entry for entry in entries if "Can't lock pid file" in entry["msg"]
            ]
            self.assertEqual(len(matches), 1)
            self.assertEqual(matches[0]["source"], "resilio")
            self.assertEqual(matches[0]["msg"], "[stderr] Can't lock pid file")
        finally:
            if app._state.database is not None:  # noqa: SLF001
                app._state.database.connection.close()  # noqa: SLF001


if __name__ == "__main__":
    unittest.main()
