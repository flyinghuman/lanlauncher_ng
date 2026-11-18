"""Reject IDs already used by local and official catalogs."""

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.core.catalog.lan_snapshot import publish_snapshot
from src.core.catalog.repository import CatalogRepository
from src.core.config.loader import AppConfig
from src.core.db.store import open_database
from src.core.service.app import Application


class DuplicateGameIdTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.db = open_database(str(self.root / "app.db"))
        self.addCleanup(self.db.connection.close)
        self.app = Application(AppConfig(bind_port=0, library_path=str(self.root)))
        self.addCleanup(self.app._server.server_close)
        self.app._state.database = self.db
        self.app._state.repository = CatalogRepository(
            self.db.connection, self.root / "metadata"
        )

    def add(self, game_id, original=""):
        return self.app._local_game_settings_update(
            {
                "original_game_id": original,
                "item": {"game_id": game_id, "title_en": "Demo"},
            }
        )

    def test_rejects_case_insensitive_official_catalog_collision_before_writing(self):
        with self.db.connection:
            self.db.connection.execute(
                "INSERT INTO game_catalog(id,title_en,title_de,key) VALUES ('Demo','Official','Official','key')"
            )
        result = self.add("demo")
        self.assertEqual(result["message"], "duplicate_game_id")
        self.assertFalse((self.root / "demo").exists())

    def test_rejects_official_game_db_even_before_import(self):
        source = self.root / "eti_launcher" / "update" / "game.db"
        source.parent.mkdir(parents=True)
        with sqlite3.connect(source) as conn:
            conn.execute("CREATE TABLE games(game_id TEXT)")
            conn.execute("INSERT INTO games VALUES ('DEMO')")
        conn.close()
        self.assertEqual(self.add("demo")["message"], "duplicate_game_id")

    def test_rejects_index_id_even_if_it_has_not_been_imported(self):
        index = self.root / "locallansync" / "index.json"
        publish_snapshot(
            index,
            {
                "schema_version": 1,
                "source": {"id": "server", "folder_id": "locallansync"},
                "games": [
                    {"game_id": "DEMO", "title": "Demo", "llng": {"schema_version": 1, "distribution": {"provider": "ouisync", "read_token": "token", "info_hash": "ab" * 20}}}
                ],
            },
        )
        self.assertEqual(self.add("demo")["message"], "duplicate_game_id")

    def test_duplicate_local_creation_rejected_but_original_edit_allowed(self):
        self.assertTrue(self.add("demo")["ok"])
        self.assertEqual(self.add("DEMO")["message"], "duplicate_game_id")
        self.assertEqual(self.add("demo")["message"], "duplicate_game_id")
        self.assertTrue(self.add("demo", original="demo")["ok"])

    def test_editing_same_local_game_with_published_index_is_allowed(self):
        self.assertTrue(self.add("demo")["ok"])
        index = self.root / "locallansync" / "index.json"
        publish_snapshot(
            index,
            {
                "schema_version": 1,
                "source": {"id": "server", "folder_id": "locallansync"},
                "games": [
                    {"game_id": "demo", "title": "Demo", "llng": {"schema_version": 1, "distribution": {"provider": "ouisync", "read_token": "token", "info_hash": "ab" * 20}}}
                ],
            },
        )
        self.assertTrue(self.add("demo", original="demo")["ok"])

    def test_local_game_can_be_shared_when_not_yet_in_lan_index(self):
        self.assertTrue(self.add("demo")["ok"])
        result = self.app._lan_game_share_update(
            {"folder_path": str(self.root / "demo"), "shared": True}
        )
        self.assertTrue(result["ok"])

    def test_invalid_index_fails_closed(self):
        index = self.root / "locallansync" / "index.json"
        index.parent.mkdir()
        index.write_text("{", encoding="utf-8")
        self.assertEqual(self.add("demo")["message"], "game_id_check_unavailable")

    def test_database_check_failure_returns_a_stable_error(self):
        with patch.object(
            self.app._state.repository,
            "game_id_records",
            side_effect=sqlite3.OperationalError("busy"),
        ):
            self.assertEqual(self.add("demo")["message"], "game_id_check_unavailable")

    def test_share_rejects_official_collision_before_provider_mutation(self):
        with self.db.connection:
            self.db.connection.execute(
                "INSERT INTO game_catalog(id,title_en,title_de,key) VALUES ('Demo','Official','Official','key')"
            )
        (self.root / "demo").mkdir()
        result = self.app._lan_game_share_update(
            {"folder_path": str(self.root / "demo"), "shared": True}
        )
        self.assertEqual(result["message"], "duplicate_game_id")
