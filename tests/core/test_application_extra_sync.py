"""Tests for manual extra sync item lifecycle in Application."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from src.core.config.loader import AppConfig
from src.core.db.store import open_database
from src.core.service.app import Application
from src.core.service.settings_store import UserSettings


class _FakeWindowsPlatform:
    def platform_name(self) -> str:
        return "linux"

    def normalize_path(self, raw_path: str) -> str:
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

    def list_storage_locations(self) -> list[dict[str, str]]:
        return []


class _FakeSyncProvider:
    def __init__(self) -> None:
        self.added: list[tuple[str, str]] = []
        self.removed: list[str] = []

    def ensure_folder_synced(self, folder_path: str, secret: str) -> tuple[bool, str]:
        self.added.append((folder_path, secret))
        return True, "ok"

    def remove_folder_sync(self, folder_path: str) -> tuple[bool, str]:
        self.removed.append(folder_path)
        return True, "ok"

    def start(self):  # pragma: no cover - unused
        raise NotImplementedError

    def stop(self):  # pragma: no cover - unused
        raise NotImplementedError

    def status(self):  # pragma: no cover - unused
        raise NotImplementedError

    def metrics(self):  # pragma: no cover - unused
        raise NotImplementedError


class ApplicationExtraSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.create_server_patch = patch(
            "src.core.service.app.create_server",
            return_value=Mock(server_close=Mock()),
        )
        self.create_server_patch.start()
        self.app = Application(
            AppConfig(bind_port=0, db_path=str(self.root / "app.db"))
        )
        self.app._state.database = open_database(str(self.root / "app.db"))  # noqa: SLF001
        self.app._state.platform_adapter = _FakeWindowsPlatform()  # noqa: SLF001
        self.app._state.sync_provider = _FakeSyncProvider()  # noqa: SLF001
        self.app._state.user_settings = UserSettings(  # noqa: SLF001
            nickname="Tester",
            theme="dark",
            log_level="WARNING",
            auto_start_sync=True,
            library_path_initialized=True,
            windows_game_drive_letter="D",
            linux_install_path=str(self.root / "library"),
        )

    def tearDown(self) -> None:
        if self.app._state.database is not None:  # noqa: SLF001
            self.app._state.database.connection.close()  # noqa: SLF001
        self.app._server.server_close()  # noqa: SLF001
        self.create_server_patch.stop()
        self.tmp.cleanup()

    def test_default_extra_sync_item_is_seeded(self) -> None:
        with self.assertLogs("src.core.service.app", level="INFO") as captured:
            self.app._ensure_default_extra_sync_item()  # noqa: SLF001
        payload = self.app._extra_sync_items_read()  # noqa: SLF001
        ids = {item["game_id"] for item in payload["items"]}
        self.assertIn("ng_provider", ids)
        self.assertNotIn("eti_launcher", ids)
        ng = next(item for item in payload["items"] if item["game_id"] == "ng_provider")
        self.assertTrue(ng["is_game_provider"])
        self.assertFalse(ng["has_game_db"])
        self.assertEqual(ng["game_provider_type"], "ouisync")
        self.assertTrue(ng["is_seeded_default"])
        self.assertFalse(
            any("game_id=eti_launcher" in line for line in captured.output)
        )
        self.assertTrue(
            any("default_extra_sync_item_added game_id=ng_provider" in line for line in captured.output)
        )

    def test_default_extra_sync_item_overwrites_existing_row(self) -> None:
        with self.app._state.database.connection:  # noqa: SLF001
            self.app._state.database.connection.execute(  # noqa: SLF001
                """
                INSERT INTO extra_sync_items(
                    game_id, game_key, title_en, title_de, release_year, publisher, size_gb,
                    readme_en, readme_de, max_players, master_required, version,
                    visible_in_gamelist, sync_enabled, is_game_provider, has_game_db,
                    packed_image_path, packed_image_password, is_seeded_default
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(game_id) DO UPDATE SET
                    game_key = excluded.game_key,
                    title_en = excluded.title_en,
                    title_de = excluded.title_de,
                    release_year = excluded.release_year,
                    publisher = excluded.publisher,
                    size_gb = excluded.size_gb,
                    readme_en = excluded.readme_en,
                    readme_de = excluded.readme_de,
                    max_players = excluded.max_players,
                    master_required = excluded.master_required,
                    version = excluded.version,
                    visible_in_gamelist = excluded.visible_in_gamelist,
                    sync_enabled = excluded.sync_enabled,
                    is_game_provider = excluded.is_game_provider,
                    has_game_db = excluded.has_game_db,
                    packed_image_path = excluded.packed_image_path,
                    packed_image_password = excluded.packed_image_password,
                    is_seeded_default = excluded.is_seeded_default,
                    updated_at = datetime('now')
                """,
                (
                    "ng_provider",
                    "OUTDATED",
                    "Old Title",
                    "Old Title",
                    "1999",
                    "Old Publisher",
                    9.9,
                    "Old EN",
                    "Old DE",
                    "99",
                    0,
                    "0.1",
                    0,
                    0,
                    0,
                    0,
                    "old/path.rar",
                    "oldsecret",
                    0,
                ),
            )

        with self.assertLogs("src.core.service.app", level="INFO") as captured:
            self.app._ensure_default_extra_sync_item()  # noqa: SLF001
        payload = self.app._extra_sync_items_read()  # noqa: SLF001
        ng = next(item for item in payload["items"] if item["game_id"] == "ng_provider")
        self.assertTrue(ng["game_key"])
        self.assertEqual(ng["title_en"], "NG-Provider")
        self.assertEqual(ng["publisher"], "NG")
        self.assertTrue(ng["is_game_provider"])
        self.assertFalse(ng["has_game_db"])
        self.assertNotIn("eti_launcher", {item["game_id"] for item in payload["items"]})
        self.assertEqual(ng["game_provider_type"], "ouisync")
        self.assertTrue(ng["sync_enabled"])
        self.assertTrue(ng["is_seeded_default"])
        self.assertTrue(
            any("default_extra_sync_item_updated game_id=ng_provider" in line for line in captured.output)
        )

    def test_upsert_requires_unique_game_id(self) -> None:
        first = self.app._extra_sync_item_upsert(  # noqa: SLF001
            {
                "item": {
                    "game_id": "manual_one",
                    "game_key": "AAAA",
                    "title_en": "Manual One",
                    "title_de": "Manual One",
                }
            }
        )
        self.assertTrue(first["ok"])
        second = self.app._extra_sync_item_upsert(  # noqa: SLF001
            {
                "item": {
                    "game_id": "manual_one",
                    "game_key": "BBBB",
                    "title_en": "Manual Two",
                    "title_de": "Manual Two",
                }
            }
        )
        self.assertFalse(second["ok"])
        self.assertEqual(second["message"], "extra_sync_game_id_not_unique")

    def test_toggle_sync_removes_folder_when_disabled(self) -> None:
        self.app._extra_sync_item_upsert(  # noqa: SLF001
            {
                "item": {
                    "game_id": "manual_toggle",
                    "game_key": "AAAA",
                    "title_en": "Manual Toggle",
                    "title_de": "Manual Toggle",
                    "sync_enabled": True,
                    "is_game_provider": True,
                    "has_game_db": True,
                }
            }
        )
        result = self.app._extra_sync_item_toggle(  # noqa: SLF001
            {"game_id": "manual_toggle", "sync_enabled": False}
        )
        self.assertTrue(result["ok"])
        provider = self.app._state.sync_provider  # noqa: SLF001
        assert isinstance(provider, _FakeSyncProvider)
        self.assertTrue(any("manual_toggle" in path for path in provider.removed))

    def test_upsert_persists_provider_flags(self) -> None:
        result = self.app._extra_sync_item_upsert(  # noqa: SLF001
            {
                "item": {
                    "game_id": "provider_alpha",
                    "game_key": "AAAA",
                    "title_en": "Provider Alpha",
                    "title_de": "Provider Alpha",
                    "is_game_provider": True,
                    "has_game_db": True,
                }
            }
        )
        self.assertTrue(result["ok"])
        entry = next(
            item for item in result["items"] if item["game_id"] == "provider_alpha"
        )
        self.assertTrue(entry["is_game_provider"])
        self.assertTrue(entry["has_game_db"])
        self.assertEqual(entry["game_provider_type"], "resilio")

    def test_bootstrap_import_adds_provider_entries_and_skips_regular_items(self) -> None:
        result = self.app._extra_sync_items_import_bootstrap(  # noqa: SLF001
            {
                "items": [
                    {
                        "game_id": "provider_imported",
                        "game_key": "OUISYNC-READ-KEY",
                        "title_en": "Imported Provider",
                        "title_de": "Importierter Provider",
                        "game_provider_type": "ouisync",
                        "is_game_provider": True,
                        "sync_enabled": False,
                    },
                    {
                        "game_id": "regular_entry",
                        "game_key": "IGNORED",
                        "title_en": "Regular entry",
                        "is_game_provider": False,
                    },
                ]
            }
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["imported"], 1)
        imported = next(
            item for item in result["items"] if item["game_id"] == "provider_imported"
        )
        self.assertTrue(imported["is_game_provider"])
        self.assertEqual(imported["game_provider_type"], "ouisync")
        self.assertFalse(imported["sync_enabled"])
        self.assertNotIn("regular_entry", {item["game_id"] for item in result["items"]})

    def test_bootstrap_import_rejects_duplicate_provider_ids(self) -> None:
        entry = {
            "game_id": "provider_duplicate",
            "game_key": "KEY",
            "title_en": "Provider",
            "is_game_provider": True,
        }
        result = self.app._extra_sync_items_import_bootstrap(  # noqa: SLF001
            {"items": [entry, dict(entry)]}
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["message"], "extra_sync_bootstrap_duplicate")
        self.assertFalse(
            any(item["game_id"] == "provider_duplicate" for item in result["items"])
        )

    def test_bootstrap_import_rolls_back_rows_when_apply_fails(self) -> None:
        provider = self.app._state.sync_provider  # noqa: SLF001
        entry = {
            "game_id": "provider_retry",
            "game_key": "KEY",
            "title_en": "Provider",
            "game_provider_type": "resilio",
            "is_game_provider": True,
            "sync_enabled": True,
        }
        with patch.object(
            provider, "ensure_folder_synced", return_value=(False, "sync_api_unreachable")
        ):
            failed = self.app._extra_sync_items_import_bootstrap(  # noqa: SLF001
                {"items": [entry]}
            )
        self.assertFalse(failed["ok"])
        self.assertEqual(failed["message"], "sync_api_unreachable")
        self.assertEqual(failed["imported"], 0)
        self.assertNotIn("provider_retry", {item["game_id"] for item in failed["items"]})
        self.assertTrue(any(path.endswith("provider_retry") for path in provider.removed))

        retried = self.app._extra_sync_items_import_bootstrap(  # noqa: SLF001
            {"items": [entry]}
        )
        self.assertTrue(retried["ok"])
        self.assertEqual(retried["imported"], 1)

    def test_bootstrap_import_rejects_dot_only_game_ids(self) -> None:
        for game_id in (".", "..", "..."):
            with self.subTest(game_id=game_id):
                result = self.app._extra_sync_items_import_bootstrap(  # noqa: SLF001
                    {
                        "items": [
                            {
                                "game_id": game_id,
                                "game_key": "KEY",
                                "title_en": "Escape",
                                "is_game_provider": True,
                                "sync_enabled": True,
                            }
                        ]
                    }
                )
                self.assertFalse(result["ok"])
                self.assertEqual(result["message"], "extra_sync_bootstrap_invalid_item")
        self.assertEqual(self.app._state.sync_provider.added, [])  # noqa: SLF001

    def test_extra_sync_ids_by_info_hash_resolves_each_token_once(self) -> None:
        for game_id, token in (("first", "TOKEN-A"), ("second", "TOKEN-B")):
            self.app._extra_sync_item_upsert(  # noqa: SLF001
                {
                    "item": {
                        "game_id": game_id,
                        "game_key": token,
                        "title_en": game_id,
                        "is_game_provider": True,
                        "game_provider_type": "ouisync",
                        "sync_enabled": False,
                    }
                }
            )
        provider = Mock()
        provider.share_token_info_hashes.return_value = {
            "TOKEN-A": "AAA111",
            "TOKEN-B": "bbb222",
        }
        mapping = self.app._extra_sync_ids_by_info_hash(provider)  # noqa: SLF001
        self.assertEqual(mapping.get("aaa111"), "first")
        self.assertEqual(mapping.get("bbb222"), "second")
        provider.share_token_info_hashes.assert_called_once()
        provider.repository_token_status.assert_not_called()

    def test_ouisync_lookup_never_falls_back_to_resilio(self) -> None:
        from src.core.sync.resilio_provider import ResilioSyncProvider

        resilio = Mock(spec=ResilioSyncProvider)
        self.app._state.sync_provider = resilio  # noqa: SLF001
        self.assertIsNone(self.app._sync_provider_for_type("ouisync"))  # noqa: SLF001
        self.assertIs(self.app._sync_provider_for_type("resilio"), resilio)  # noqa: SLF001

        router = Mock()
        router.provider_for_type.return_value = resilio
        self.app._state.sync_provider = router  # noqa: SLF001
        self.assertIsNone(self.app._sync_provider_for_type("ouisync"))  # noqa: SLF001

        result = self.app._ouisync_debug_action("reset-ng-provider")  # noqa: SLF001
        self.assertFalse(result["ok"])
        self.assertEqual(result["message"], "sync_provider_unavailable")
        resilio.remove_folder_sync.assert_not_called()
        resilio.ensure_folder_synced.assert_not_called()

    def test_ouisync_debug_reset_reasons_are_locale_keys(self) -> None:
        self.app._ensure_default_extra_sync_item()  # noqa: SLF001
        provider = Mock()
        provider.status.return_value = Mock(running=False, state="stopped")
        provider.repository_token_status.return_value = {"available": False}
        provider.provider_for_type.return_value = provider
        self.app._state.sync_provider = provider  # noqa: SLF001
        result = self.app._ouisync_debug_action("reset-ng-provider")  # noqa: SLF001
        skipped = [line for line in result["lines"] if line["key"] == "ui.ouisync_debug_reset_skipped"]
        self.assertEqual(skipped[0]["value"], "ui.ouisync_debug_reason_not_running")

    def test_upsert_persists_game_provider_type(self) -> None:
        result = self.app._extra_sync_item_upsert(  # noqa: SLF001
            {
                "item": {
                    "game_id": "provider_ouisync",
                    "game_key": "AAAA",
                    "title_en": "Provider Ouisync",
                    "title_de": "Provider Ouisync",
                    "is_game_provider": True,
                    "has_game_db": True,
                    "game_provider_type": "ouisync",
                }
            }
        )
        self.assertTrue(result["ok"])
        entry = next(
            item for item in result["items"] if item["game_id"] == "provider_ouisync"
        )
        self.assertEqual(entry["game_provider_type"], "ouisync")

    def test_upsert_persists_packed_image_fields(self) -> None:
        result = self.app._extra_sync_item_upsert(  # noqa: SLF001
            {
                "item": {
                    "game_id": "provider_images",
                    "game_key": "AAAA",
                    "title_en": "Provider Images",
                    "title_de": "Provider Images",
                    "is_game_provider": True,
                    "has_game_db": True,
                    "packed_image_path": "image/images.rar",
                    "packed_image_password": "secret",
                }
            }
        )
        self.assertTrue(result["ok"])
        entry = next(
            item for item in result["items"] if item["game_id"] == "provider_images"
        )
        self.assertEqual(entry["packed_image_path"], "image/images.rar")
        self.assertEqual(entry["packed_image_password"], "secret")

    def test_game_image_path_does_not_extract_packed_provider_archive(self) -> None:
        provider_root = self.root / "library" / "ng_provider"
        archive = provider_root / "assets" / "assets.rar"
        archive.parent.mkdir(parents=True, exist_ok=True)
        archive.write_bytes(b"rar")
        self.app._extra_sync_item_upsert(  # noqa: SLF001
            {
                "item": {
                    "game_id": "ng_provider",
                    "game_key": "AAAA",
                    "title_en": "NG Provider",
                    "title_de": "NG Provider",
                    "is_game_provider": True,
                    "has_game_db": True,
                    "packed_image_path": "assets/assets.rar",
                    "packed_image_password": "secret",
                }
            }
        )

        with unittest.mock.patch(
            "src.core.service.app.subprocess.run"
        ) as mocked_run:
            path = self.app._game_image_path("demo")  # noqa: SLF001

        self.assertEqual(
            Path(path), self.root / "library" / "eti_launcher" / "image" / "demo.jpg"
        )
        mocked_run.assert_not_called()

    def test_refresh_provider_images_extracts_packed_provider_archive(self) -> None:
        provider_root = self.root / "library" / "ng_provider"
        archive = provider_root / "assets" / "assets.rar"
        archive.parent.mkdir(parents=True, exist_ok=True)
        archive.write_bytes(b"rar")
        target_dir = provider_root / "image"
        self.app._extra_sync_item_upsert(  # noqa: SLF001
            {
                "item": {
                    "game_id": "ng_provider",
                    "game_key": "AAAA",
                    "title_en": "NG Provider",
                    "title_de": "NG Provider",
                    "is_game_provider": True,
                    "has_game_db": True,
                    "packed_image_path": "assets/assets.rar",
                    "packed_image_password": "secret",
                }
            }
        )

        def _fake_run(cmd, **_kwargs):
            self.assertIn("-psecret", cmd)
            target_dir.mkdir(parents=True, exist_ok=True)
            (target_dir / "demo.jpg").write_bytes(b"new")

            class _Result:
                returncode = 0
                stdout = "ok"

            return _Result()

        with (
            self.assertLogs("src.core.service.app", level="INFO") as captured,
            unittest.mock.patch("src.core.service.app.shutil.which", return_value="/usr/bin/unrar"),
            unittest.mock.patch(
                "src.core.service.app.subprocess.run", side_effect=_fake_run
            ),
        ):
            result = self.app._refresh_provider_image_archives("ng_provider")  # noqa: SLF001

        self.assertTrue(result["ok"])
        self.assertEqual(result["refreshed"], 1)
        self.assertTrue((target_dir / "demo.jpg").read_bytes() == b"new")
        self.assertTrue(
            any(
                "provider_image_target_dir_created provider_game_id=ng_provider"
                in line
                for line in captured.output
            )
        )
        self.assertTrue(
            any(
                "provider_image_archive_extracting provider_game_id=ng_provider"
                in line
                for line in captured.output
            )
        )
        self.assertTrue((target_dir / ".llng-image-archive.json").exists())

    def test_defaults_loaded_from_config_file(self) -> None:
        defaults_path = self.root / "defaults.json"
        defaults_path.write_text(
            json.dumps(
                {
                    "items": [
                        {
                            "game_id": "custom_provider",
                            "game_key": "ROKEY",
                            "title_en": "Custom Provider",
                            "title_de": "Custom Provider",
                            "is_game_provider": True,
                            "has_game_db": True,
                            "sync_enabled": True,
                            "visible_in_gamelist": False,
                            "game_provider_type": "ouisync",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        app = Application(
            AppConfig(
                bind_port=0,
                db_path=str(self.root / "custom.db"),
                default_extra_sync_items_path=str(defaults_path),
            )
        )
        app._state.database = open_database(str(self.root / "custom.db"))  # noqa: SLF001
        try:
            app._ensure_default_extra_sync_item()  # noqa: SLF001
            payload = app._extra_sync_items_read()  # noqa: SLF001
        finally:
            if app._state.database is not None:  # noqa: SLF001
                app._state.database.connection.close()  # noqa: SLF001
            app._server.server_close()  # noqa: SLF001
        ids = {item["game_id"] for item in payload["items"]}
        self.assertIn("custom_provider", ids)
        self.assertNotIn("ng_provider", ids)
        custom = next(item for item in payload["items"] if item["game_id"] == "custom_provider")
        self.assertEqual(custom["game_provider_type"], "ouisync")

    def test_default_extra_sync_items_resolve_against_runtime_root(self) -> None:
        runtime_root = self.root / "runtime"
        config_dir = runtime_root / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        defaults_path = config_dir / "bootstrap.json"
        defaults_path.write_text(
            json.dumps(
                {
                    "items": [
                        {
                            "game_id": "runtime_provider",
                            "game_key": "ROKEY",
                            "title_en": "Runtime Provider",
                            "title_de": "Runtime Provider",
                            "sync_enabled": True,
                            "game_provider_type": "resilio",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        app = Application(
            AppConfig(
                bind_port=0,
                db_path=str(self.root / "runtime.db"),
                repo_root=str(runtime_root),
                default_extra_sync_items_path="config/bootstrap.json",
            )
        )
        app._state.database = open_database(str(self.root / "runtime.db"))  # noqa: SLF001
        try:
            with self.assertLogs("src.core.service.app", level="INFO") as captured:
                app._ensure_default_extra_sync_item()  # noqa: SLF001
            payload = app._extra_sync_items_read()  # noqa: SLF001
        finally:
            if app._state.database is not None:  # noqa: SLF001
                app._state.database.connection.close()  # noqa: SLF001
            app._server.server_close()  # noqa: SLF001
        ids = {item["game_id"] for item in payload["items"]}
        self.assertIn("runtime_provider", ids)
        self.assertTrue(
            any("default_extra_sync_item_added game_id=runtime_provider" in line for line in captured.output)
        )

    def test_optional_bootstrap_seeds_and_removes_optional_items(self) -> None:
        runtime_root = self.root / "optional-runtime"
        config_dir = runtime_root / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        defaults_path = config_dir / "bootstrap.json"
        optional_path = config_dir / "optional-bootstrap.json"
        defaults_path.write_text(
            json.dumps({"items": [{
                "game_id": "required_provider",
                "game_key": "REQUIRED",
                "title_en": "Required Provider",
                "title_de": "Required Provider",
            }]}),
            encoding="utf-8",
        )
        optional_path.write_text(
            json.dumps({"items": [
                {
                    "game_id": "eti_launcher",
                    "game_key": "OPTIONAL",
                    "title_en": "ETI LAN Launcher",
                    "title_de": "ETI LAN Launcher",
                    "game_provider_type": "resilio",
                    "has_game_db": True,
                },
                {
                    "game_id": "required_provider",
                    "game_key": "OVERRIDE",
                    "title_en": "Must Not Override",
                    "title_de": "Must Not Override",
                },
            ]}),
            encoding="utf-8",
        )
        app = Application(
            AppConfig(
                bind_port=0,
                db_path=str(self.root / "optional-runtime.db"),
                repo_root=str(runtime_root),
                default_extra_sync_items_path="config/bootstrap.json",
                optional_extra_sync_items_path="config/optional-bootstrap.json",
            )
        )
        app._state.database = open_database(str(self.root / "optional-runtime.db"))  # noqa: SLF001
        try:
            app._ensure_default_extra_sync_item()  # noqa: SLF001
            ids = {item["game_id"] for item in app._extra_sync_items_read()["items"]}  # noqa: SLF001
            self.assertEqual(ids, {"required_provider", "eti_launcher"})
            required = next(
                item
                for item in app._extra_sync_items_read()["items"]  # noqa: SLF001
                if item["game_id"] == "required_provider"
            )
            self.assertEqual(required["title_en"], "Required Provider")

            optional_path.unlink()
            app._ensure_default_extra_sync_item()  # noqa: SLF001
            ids = {item["game_id"] for item in app._extra_sync_items_read()["items"]}  # noqa: SLF001
            self.assertEqual(ids, {"required_provider"})
        finally:
            app._state.database.connection.close()  # noqa: SLF001
            app._server.server_close()  # noqa: SLF001

    def test_seeded_default_item_cannot_be_deleted(self) -> None:
        self.app._ensure_default_extra_sync_item()  # noqa: SLF001
        result = self.app._extra_sync_item_delete({"game_id": "ng_provider"})  # noqa: SLF001
        self.assertFalse(result["ok"])
        self.assertEqual(result["message"], "extra_sync_item_locked")

    def test_seeded_default_item_cannot_be_edited(self) -> None:
        self.app._ensure_default_extra_sync_item()  # noqa: SLF001
        result = self.app._extra_sync_item_upsert(  # noqa: SLF001
            {
                "original_game_id": "ng_provider",
                "item": {
                    "game_id": "ng_provider",
                    "game_key": "CHANGED",
                    "title_en": "NG-Provider",
                    "title_de": "NG-Provider",
                },
            }
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["message"], "extra_sync_item_locked")


if __name__ == "__main__":
    unittest.main()
