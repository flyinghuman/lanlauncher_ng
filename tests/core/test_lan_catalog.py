"""LAN catalog reconciliation and ownership tests."""

import copy
import sqlite3
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from pathlib import Path

from src.core.catalog.lan_snapshot import InvalidLanSnapshot, publish_snapshot
from src.core.catalog.lan_settings import new_settings, read_settings
from src.core.catalog.repository import CatalogRepository
from src.core.config.loader import AppConfig
from src.core.db.migrations import apply_migrations
from src.core.service.app import Application
from src.core.service.launcher_site import build_snapshot_from_ini


def make_snapshot(source="server-one", games=None):
    return {
        "schema_version": 1,
        "source": {"id": source, "folder_id": "locallansync"},
        "games": games
        if games is not None
        else [
            {
                "game_id": "demo",
                "title": {"en": "Demo", "de": "Beispiel"},
                "llng": {"schema_version": 1, "distribution": {
                    "provider": "ouisync", "read_token": "token",
                    "info_hash": "ab" * 20, "editable_files": [],
                }},
                "version": "2",
                "media": {"image_url": "images/demo.jpg"},
            }
        ],
    }


class LanCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.conn = sqlite3.connect(":memory:")
        self.addCleanup(self.conn.close)
        apply_migrations(self.conn)
        self.repo = CatalogRepository(self.conn, self.root)
        self.path = self.root / "index.json"

    def apply(self, data):
        publish_snapshot(self.path, data)
        return self.repo.reconcile_lan_snapshot(self.path)

    def test_server_seeds_settings_snapshot_atomically(self):
        app = Application(AppConfig(bind_port=0))
        self.addCleanup(app._server.server_close)
        app._state.user_settings = SimpleNamespace(lan_mode="server")
        app._state.launcher_site_snapshot = build_snapshot_from_ini(
            """
            lan_title {
            Summer LAN
            }
            lan_url {
            https://lan.example/
            }
            stats_url {
            https://lan.example/stats.php
            }
            discord_url {
            https://discord.gg/example
            }
            ts3_server {
            ts3server://1.2.3.4?port=9987
            }
            link_1 {
            Food|https://lan.example/food
            }
            disable_games {
            demo
            }
            """,
            source_url="https://lan.example/launcher.ini",
            fetched_at=1,
        )
        with patch.object(app, "_effective_library_path", return_value=str(self.root)):
            app._ensure_lan_server_settings()
        snapshot = read_settings(self.root / "locallansync" / ".ouisync" / "settings.json")
        self.assertEqual(snapshot["schema_version"], 1)
        self.assertEqual(snapshot["disable_games"], ["demo"])
        self.assertEqual(snapshot["stats_url"], "https://lan.example/stats.php")
        self.assertEqual(snapshot["ts3_server"], "ts3server://1.2.3.4?port=9987")
        self.assertEqual(snapshot["links"][0]["key"], "link_1")

    def test_synced_settings_override_launcher_ini_but_missing_snapshot_uses_fallback(self):
        app = Application(AppConfig(bind_port=0))
        self.addCleanup(app._server.server_close)
        app._state.launcher_site_snapshot = build_snapshot_from_ini(
            "disable_games {\nlegacy-game\n}",
            source_url="http://launcher.lan/launcher.ini",
            fetched_at=1,
        )
        self.assertEqual(app._disabled_game_ids(), ["legacy-game"])
        app._state.lan_settings_snapshot = new_settings(
            lan_title="New title",
            lan_url="https://lan.example/",
            stats_url="https://lan.example/stats.php",
            disable_games=["new-game"],
            links=[{"key": "link_1", "label": "Food", "url": "https://lan.example/food"}],
        )
        payload = app._launcher_site_read()
        self.assertTrue(payload["managed_by_lan_server"])
        self.assertEqual(payload["disable_games"], ["new-game"])
        self.assertEqual(payload["lan_title"], "New title")
        self.assertEqual(payload["links"][0]["key"], "lan_url")
        self.assertEqual(app._disabled_game_ids(), [])
        self.assertEqual(app._lan_disabled_game_ids(), ["new-game"])

    def test_insert_update_and_remove_without_deleting_state_or_files(self):
        data = make_snapshot()
        self.assertEqual(self.apply(data)["updated"], 1)
        game = self.repo.get_game("demo", "de")
        self.assertEqual(game["title"], "Beispiel")
        self.assertEqual(game["key"], "ab" * 20)
        self.assertEqual(game["game_provider_type"], "ouisync")
        game_dir = self.root / "demo"
        game_dir.mkdir()
        (game_dir / "file.txt").write_text("data")
        self.repo.set_install_state("demo", "missing")
        data["games"][0]["title"]["de"] = "Aktualisiert"
        self.apply(data)
        self.assertEqual(self.repo.get_game("demo", "de")["title"], "Aktualisiert")
        self.assertEqual(self.apply(make_snapshot(games=[]))["removed"], 1)
        self.assertIsNone(self.repo.get_game("demo"))
        self.assertTrue((game_dir / "file.txt").exists())
        self.assertEqual(
            self.conn.execute(
                "SELECT state FROM install_state WHERE game_id='demo'"
            ).fetchone()[0],
            "missing",
        )
        self.assertEqual(self.apply(data)["updated"], 1)

    def test_ouisync_private_entry_stores_token_only_for_sync_access(self):
        token = "private-read-capability"
        data = make_snapshot(games=[{
            "game_id": "private-demo",
            "title": {"en": "Private Demo", "de": "Privates Spiel"},
            "llng": {
                "schema_version": 1,
                "distribution": {
                    "provider": "ouisync",
                    "read_token": token,
                    "info_hash": "ab" * 20,
                    "editable_files": [],
                },
            },
        }])
        self.assertEqual(self.apply(data)["updated"], 1)
        game = self.repo.get_game("private-demo", "en")
        self.assertEqual(game["game_provider_type"], "ouisync")
        self.assertEqual(game["key"], "ab" * 20)
        self.assertNotIn(token, repr(game))
        access = self.repo.lan_game_ouisync_access("private-demo")
        self.assertEqual(access.game_id, "private-demo")
        self.assertEqual(access.read_token, token)
        self.assertEqual(access.expected_info_hash, "ab" * 20)

    def test_invalid_ouisync_private_capability_rejects_whole_snapshot(self):
        data = make_snapshot(games=[{
            "game_id": "private-demo",
            "title": "Private Demo",
            "llng": {"schema_version": 1, "distribution": {
                "provider": "ouisync", "read_token": "bad token", "info_hash": "hash"
            }},
        }])
        with self.assertRaises(InvalidLanSnapshot):
            self.apply(data)

    def test_game_sync_uses_private_ouisync_access_instead_of_public_index(self):
        token = "private-read-capability"
        self.apply(make_snapshot(games=[{
            "game_id": "private-demo",
            "title": "Private Demo",
            "llng": {"schema_version": 1, "distribution": {
                "provider": "ouisync", "read_token": token, "info_hash": "ab" * 20
            }},
        }]))
        app = Application(AppConfig(library_path=str(self.root), bind_port=0))
        self.addCleanup(app._server.server_close)
        app._state.repository = self.repo
        app._state.user_settings = SimpleNamespace(
            lan_mode="client", sync_only_mode=False
        )
        sync = Mock()
        sync.provider_for_game = None
        sync.start_game_materialization.return_value = (True, "started")
        sync.folder_sync_status.return_value = {"active": False, "progress_percent": 0}
        sync.game_materialization_status.return_value = {
            "phase": "materializing", "progress_percent": 0, "error": ""
        }
        app._state.sync_provider = sync
        with patch.object(app, "_sync_provider_for_game", return_value=sync):
            result = app._game_sync_start("private-demo")
        self.assertTrue(result["ok"])
        access = sync.start_game_materialization.call_args.args[0]
        self.assertEqual(access.read_token, token)
        self.assertEqual(access.expected_info_hash, "ab" * 20)
    def test_removed_installed_game_retained_then_can_be_restored(self):
        self.apply(make_snapshot())
        self.repo.set_install_state("demo", "installed", "1")
        self.assertEqual(self.apply(make_snapshot(games=[]))["retained"], 1)
        self.assertEqual(self.repo.get_game("demo")["installed_version"], "1")
        self.assertEqual(self.apply(make_snapshot())["updated"], 1)
        row = self.conn.execute(
            "SELECT available, retained FROM lan_catalog_entries"
        ).fetchone()
        self.assertEqual(tuple(row), (1, 0))

    def test_removed_download_is_hidden_and_can_be_restored_without_losing_files(self):
        self.apply(make_snapshot())
        folder = self.root / "demo"
        folder.mkdir()
        (folder / "partial.bin").write_bytes(b"partial")
        self.repo.set_install_state("demo", "downloading")
        self.assertEqual(self.apply(make_snapshot(games=[]))["removed"], 1)
        self.assertIsNone(self.repo.get_game("demo"))
        self.assertEqual(self.repo.current_install_state("demo"), "missing")
        self.assertEqual(self.repo.unavailable_lan_games(), ["demo"])
        self.assertEqual((folder / "partial.bin").read_bytes(), b"partial")
        self.apply(make_snapshot())
        self.assertEqual(self.repo.unavailable_lan_games(), [])
        self.assertIsNotNone(self.repo.get_game("demo"))

    def test_removed_lan_game_is_unavailable_without_deleting_local_files(self):
        self.apply(make_snapshot())
        self.repo.set_install_state("demo", "installed", "1")
        self.apply(make_snapshot(games=[]))
        app = Application(AppConfig(library_path=str(self.root), bind_port=0))
        self.addCleanup(app._server.server_close)
        app._state.repository = self.repo
        app._ouisync_manage_lan_cycle()
        self.assertEqual(self.repo.get_game("demo")["install_state"], "installed")
        self.assertFalse(self.repo.lan_game_available("demo"))
        sync = Mock()
        app._state.sync_provider = sync
        result = app._game_sync_start("demo")
        self.assertEqual(result["message"], "lan_game_unavailable")
        sync.ensure_folder_synced.assert_not_called()
        self.apply(make_snapshot())
        self.assertTrue(self.repo.lan_game_available("demo"))

    def test_old_tombstone_does_not_pause_a_replacement_local_game(self):
        self.apply(make_snapshot())
        self.apply(make_snapshot(games=[]))
        with self.conn:
            self.conn.execute("INSERT INTO game_catalog(id,title_en,title_de,key,game_provider_type) VALUES ('demo','Local','Local','', 'local')")
        self.assertEqual(self.repo.unavailable_lan_games(), [])
        self.assertIsNone(self.repo.lan_game_available("demo"))

    def test_case_insensitive_collisions_never_overwrite_existing_game(self):
        with self.conn:
            self.conn.execute(
                "INSERT INTO game_catalog(id,title_en,title_de,key) VALUES ('DEMO','Official','Official','official')"
            )
        self.assertEqual(self.apply(make_snapshot())["conflicts"], 1)
        self.assertEqual(self.repo.get_game("DEMO")["title"], "Official")

    def test_other_source_and_missing_or_invalid_index_do_not_remove_games(self):
        self.apply(make_snapshot())
        other = make_snapshot("server-two")
        self.assertEqual(self.apply(other)["conflicts"], 1)
        self.path.write_text('{"schema_version":', encoding="utf-8")
        with self.assertRaises(InvalidLanSnapshot):
            self.repo.reconcile_lan_snapshot(self.path)
        self.path.unlink()
        with self.assertRaises(FileNotFoundError):
            self.repo.reconcile_lan_snapshot(self.path)
        self.assertIsNotNone(self.repo.get_game("demo"))

    def test_changed_id_case_updates_existing_record(self):
        data = make_snapshot()
        self.apply(data)
        changed = copy.deepcopy(data)
        changed["games"][0]["game_id"] = "DEMO"
        self.assertEqual(self.apply(changed)["updated"], 1)
        self.assertEqual(self.repo.list_game_ids(), ["demo"])

    def test_application_imports_and_serves_local_cover_without_network(self):
        app = Application(AppConfig(library_path=str(self.root), bind_port=0))
        self.addCleanup(app._server.server_close)
        app._state.repository = self.repo
        catalog = self.root / "locallansync"
        cover = catalog / "images" / "demo.jpg"
        cover.parent.mkdir(parents=True)
        cover.write_bytes(b"local image")
        publish_snapshot(catalog / "index.json", make_snapshot())
        self.assertTrue(app._try_import_lan_catalog())
        self.assertFalse(app._try_import_lan_catalog())
        self.assertEqual(self.repo.lan_cover_path("demo"), cover)
        self.assertIn(cover, app._candidate_media_paths("demo", "image", "jpg"))
        (catalog / "index.json").unlink()
        self.assertFalse(app._try_import_lan_catalog())
        self.assertIsNotNone(self.repo.get_game("demo"))

    def test_cover_symlink_cannot_escape_catalog(self):
        outside = self.root / "outside.jpg"
        outside.write_bytes(b"outside")
        (self.root / "images").mkdir()
        try:
            (self.root / "images" / "demo.jpg").symlink_to(outside)
        except OSError:
            self.skipTest("symlinks unavailable")
        self.apply(make_snapshot())
        # Index root is self.root here, so use a target outside that root.
        with tempfile.TemporaryDirectory() as other:
            external = Path(other) / "cover.jpg"
            external.write_bytes(b"outside")
            (self.root / "images" / "demo.jpg").unlink()
            (self.root / "images" / "demo.jpg").symlink_to(external)
            self.assertIsNone(self.repo.lan_cover_path("demo"))
