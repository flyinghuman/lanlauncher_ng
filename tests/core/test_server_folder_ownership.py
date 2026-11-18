"""Server settings hide folders belonging to other game providers."""

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from src.core.catalog.repository import CatalogRepository
from src.core.config.loader import AppConfig
from src.core.db.store import open_database
from src.core.service.app import Application
from src.core.service.settings_store import UserSettings


class ServerFolderOwnershipTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        db = open_database(str(self.root / "app.db"))
        self.addCleanup(db.connection.close)
        self.repo = CatalogRepository(db.connection, self.root / "metadata")
        with db.connection:
            for game_id, provider in (
                ("localgame", "local"),
                ("oldgame", "resilio"),
                ("synced", "ouisync"),
                ("future-provider-game", "custom-provider"),
                ("local-without-folder", "local"),
            ):
                db.connection.execute("INSERT INTO game_catalog(id,title_en,title_de,key,game_provider_type) VALUES(?,?,?,?,?)",
                                      (game_id, game_id, game_id, "key", provider))
            db.connection.execute("INSERT INTO extra_sync_items(game_id, game_key, game_provider_type) VALUES (?, ?, ?)", ("extra", "key", "resilio"))
            db.connection.execute(
                "INSERT INTO game_index_catalog_entries(game_id, present, pending_removal) VALUES (?, 1, 0)",
                ("global-index-game",),
            )
            db.connection.execute(
                "INSERT INTO game_index_catalog_entries(game_id, present, pending_removal) VALUES (?, 0, 1)",
                ("retiring-global-game",),
            )
        self.app = Application(AppConfig(bind_port=0, library_path=str(self.root)))
        self.addCleanup(self.app._server.server_close)
        self.app._state.repository = self.repo
        self.app._state.user_settings = UserSettings(nickname="Test", theme="dark", log_level="WARNING", auto_start_sync=True,
            library_path_initialized=True, windows_game_drive_letter="D", linux_install_path=str(self.root), lan_mode="server")
        names = (
            "LocalGame",
            "OLDGAME",
            "synced",
            "manual",
            "extra",
            "fresh",
            "future-provider-game",
            "GLOBAL-INDEX-GAME",
            "retiring-global-game",
        )
        for name in names:
            (self.root / name).mkdir()

    def read(self):
        return self.app._lan_game_inventory_read()

    def read_server_preview(self):
        return self.app._lan_server_game_inventory_read()

    def test_hides_provider_folders_but_keeps_existing_local_catalog_game(self):
        result = self.read()
        self.assertEqual(
            [f["name"] for f in result["folders"]],
            ["fresh", "LocalGame", "manual"],
        )
        self.assertNotIn(
            "local-without-folder", [f["name"] for f in result["folders"]]
        )
        self.app._state.user_settings = replace(self.app._state.user_settings, lan_mode="client")
        self.assertEqual(len(self.read()["folders"]), 9)

    def test_server_role_preview_filters_folders_before_role_is_saved(self):
        self.app._state.user_settings = replace(
            self.app._state.user_settings, lan_mode="client"
        )
        result = self.read_server_preview()
        self.assertEqual(
            [folder["name"] for folder in result["folders"]],
            ["fresh", "LocalGame", "manual"],
        )

    def test_database_unavailable_does_not_expose_unknown_folders(self):
        self.app._state.repository = None
        result = self.read()
        self.assertEqual(result["folders"], [])
        self.assertEqual(result["message"], "lan_game_inventory_unavailable")
