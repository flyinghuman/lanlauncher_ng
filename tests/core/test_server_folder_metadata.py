"""Metadata editing for server-managed game folders."""

import base64
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from src.core.catalog.lan_publish import publish_shared_games
from src.core.catalog.lan_snapshot import read_snapshot
from src.core.catalog.repository import CatalogRepository
from src.core.config.loader import AppConfig
from src.core.db.store import open_database
from src.core.service.app import Application
from src.core.service.settings_store import UserSettings


class ServerFolderMetadataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.folder = self.root / "demo"
        self.folder.mkdir()
        self.db = open_database(str(self.root / "app.db"))
        self.addCleanup(self.db.connection.close)
        self.app = Application(AppConfig(bind_port=0, library_path=str(self.root)))
        self.addCleanup(self.app._server.server_close)
        self.app._state.database = self.db
        self.app._state.repository = CatalogRepository(
            self.db.connection, self.root / "metadata"
        )
        self.app._state.user_settings = UserSettings(
            nickname="Tester",
            theme="dark",
            log_level="WARNING",
            auto_start_sync=True,
            library_path_initialized=True,
            windows_game_drive_letter="D",
            linux_install_path=str(self.root),
            lan_mode="server",
        )

    def publish(self, shares):
        return publish_shared_games(
            self.root, shares,
            ouisync_publisher=lambda _folder: {"read_token": "token", "info_hash": "ab" * 20},
        )

    def save(self, title="Demo", **extra):
        return self.app._lan_game_share_update(
            {
                "action": "save_metadata",
                "folder_path": str(self.folder),
                "item": {"title_en": title, "title_de": "Beispiel", **extra},
            }
        )

    def test_create_publish_import_and_edit_same_lan_game(self):
        self.assertTrue(self.save(readme_en="Description")["ok"])
        metadata = json.loads(
            (self.folder / "metadata.json").read_text(encoding="utf-8")
        )
        self.assertEqual(metadata["description"]["en"], "Description")
        shares = [{"path": str(self.folder), "id": "demo-folder"}]
        self.publish(shares)
        index = self.root / "locallansync" / ".ouisync" / "index.json"
        self.app._state.repository.reconcile_lan_snapshot(index)
        self.assertTrue(self.save("Updated")["ok"])
        self.publish(shares)
        self.app._state.repository.reconcile_lan_snapshot(index)
        self.assertEqual(
            self.app._state.repository.get_game("demo")["title"], "Updated"
        )
        result = self.app._lan_game_share_update(
            {"folder_path": str(self.folder), "shared": True}
        )
        self.assertTrue(result["ok"])

    def test_existing_metadata_and_local_cover_are_preserved(self):
        (self.folder / "metadata.json").write_text(
            json.dumps(
                {
                    "game_id": "demo",
                    "title": "Original",
                    "custom": {"future": True},
                    "media": {"video_url": "https://example.org/video"},
                }
            ),
            encoding="utf-8",
        )
        picture = "data:image/png;base64," + base64.b64encode(b"image bytes").decode()
        self.assertTrue(self.save(game_image_data_url=picture)["ok"])
        metadata = json.loads(
            (self.folder / "metadata.json").read_text(encoding="utf-8")
        )
        self.assertEqual(metadata["custom"], {"future": True})
        self.assertEqual(metadata["media"]["video_url"], "https://example.org/video")
        self.assertEqual(
            (self.folder / metadata["media"]["image_url"]).read_bytes(), b"image bytes"
        )
        self.publish([{"path": str(self.folder), "id": "demo"}])
        cover = read_snapshot(self.root / "locallansync" / ".ouisync" / "index.json")["games"][0][
            "media"
        ]["image_url"]
        self.assertEqual(
            (self.root / "locallansync" / ".ouisync" / cover).read_bytes(), b"image bytes"
        )

    def test_converted_download_is_saved_and_published_as_local_jpeg(self):
        (self.folder / "metadata.json").write_text(json.dumps({
            "game_id": "demo", "title": "Demo", "media": {"image_url": "https://example.org/cover.png"}
        }), encoding="utf-8")
        data = "data:image/jpeg;base64," + base64.b64encode(b"jpeg data").decode()
        self.assertTrue(self.save(game_image_data_url=data)["ok"])
        metadata = json.loads((self.folder / "metadata.json").read_text(encoding="utf-8"))
        self.assertTrue(metadata["media"]["image_url"].endswith(".jpg"))
        self.publish([{"path": str(self.folder), "id": "demo"}])
        image = read_snapshot(self.root / "locallansync" / ".ouisync" / "index.json")["games"][0]["media"]["image_url"]
        self.assertEqual((self.root / "locallansync" / ".ouisync" / image).read_bytes(), b"jpeg data")

    def test_ouisync_metadata_and_cover_are_read_from_repository_folder(self):
        source = self.folder / ".ouisync"
        source.mkdir()
        (source / "cover.webp").write_bytes(b"cover")
        (source / "metadata.json").write_text(
            json.dumps(
                {
                    "game_id": "demo",
                    "title": "Demo from Ouisync",
                    "media": {"image": "cover.webp"},
                }
            ),
            encoding="utf-8",
        )

        self.publish([{"path": str(self.folder), "id": "demo"}])

        snapshot = read_snapshot(self.root / "locallansync" / ".ouisync" / "index.json")
        self.assertEqual(snapshot["games"][0]["title"], "Demo from Ouisync")
        image = snapshot["games"][0]["media"]["image_url"]
        self.assertTrue((self.root / "locallansync" / ".ouisync" / image).is_file())

    def test_duplicate_official_id_does_not_create_metadata(self):
        with self.db.connection:
            self.db.connection.execute(
                "INSERT INTO game_catalog(id,title_en,title_de,key) VALUES ('DEMO','Official','Official','key')"
            )
        self.assertEqual(self.save()["message"], "duplicate_game_id")
        self.assertFalse((self.folder / "metadata.json").exists())

    def test_outside_folder_and_client_role_are_rejected(self):
        result = self.app._lan_game_share_update(
            {
                "action": "save_metadata",
                "folder_path": str(self.root.parent),
                "item": {"title_en": "Demo"},
            }
        )
        self.assertEqual(result["message"], "lan_game_folder_invalid")
        self.app._state.user_settings = replace(
            self.app._state.user_settings, lan_mode="client"
        )
        self.assertEqual(self.save()["message"], "server_mode_required")
