"""Tests for per-game metadata save behavior in Application."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from src.core.catalog.metadata import MetadataStore
from src.core.catalog.repository import CatalogRepository
from src.core.config.loader import AppConfig
from src.core.db.store import open_database
from src.core.service.app import Application
from src.core.service.settings_store import UserSettings


class ApplicationGameMetadataTests(unittest.TestCase):
    def test_ouisync_metadata_media_resolves_inside_repository_without_copying(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            library_root = root / "LAN"
            source_root = library_root / "demo" / ".ouisync"
            source_root.mkdir(parents=True)
            image = source_root / "cover.webp"
            image.write_bytes(b"cover")
            (source_root / "metadata.json").write_text(
                json.dumps({"media": {"image": "cover.webp"}}), encoding="utf-8"
            )
            db = open_database(str(root / "app.db"))
            app = Application(AppConfig(bind_port=0, library_path=str(library_root)))
            app._state.database = db  # noqa: SLF001
            app._state.repository = CatalogRepository(db.connection)  # noqa: SLF001
            app._state.user_settings = UserSettings(  # noqa: SLF001
                nickname="Tester",
                theme="dark",
                log_level="WARNING",
                auto_start_sync=True,
                library_path_initialized=True,
                windows_game_drive_letter="D",
                linux_install_path=str(library_root),
            )
            adapter = Mock()
            adapter.platform_name.return_value = "linux"
            app._state.platform_adapter = adapter  # noqa: SLF001
            try:
                candidates = app._candidate_media_paths("demo", "image", "jpg")  # noqa: SLF001
                self.assertIn(image, candidates)
                self.assertEqual(app._game_metadata("demo").image, "cover.webp")  # noqa: SLF001
                self.assertTrue(image.is_file())
                self.assertFalse((library_root / "demo" / "cover.webp").exists())
            finally:
                app._server.server_close()  # noqa: SLF001
                db.connection.close()

    def test_save_game_metadata_file_writes_catalog_fields_and_winetricks_tasks(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            metadata_root = root / "metadata"
            metadata_root.mkdir(parents=True, exist_ok=True)
            db = open_database(str(root / "app.db"))
            with db.connection:
                db.connection.execute(
                    "INSERT INTO genres(id, name_en, name_de) VALUES (7, 'Racing', 'Rennspiel')"
                )
                db.connection.execute(
                    """
                    INSERT INTO game_catalog(
                        id, title_en, title_de, key, release_year, publisher, size_gb,
                        readme_en, readme_de, max_players, master_required, genre_id, version
                    )
                    VALUES (
                        'demo', 'Demo EN', 'Demo DE', 'DEMO_KEY', '2000', 'ETI', 1.5,
                        'Readme EN', 'Readme DE', '8', 1, 7, '1.0'
                    )
                    """
                )

            library_root = root / "LAN"
            app = Application(AppConfig(bind_port=0, library_path=str(library_root)))
            app._state.database = db  # noqa: SLF001
            app._state.repository = CatalogRepository(  # noqa: SLF001
                db.connection,
                metadata_root=metadata_root,
            )
            app._state.metadata_root = metadata_root  # noqa: SLF001
            app._state.metadata_store = MetadataStore(metadata_root)  # noqa: SLF001
            app._state.user_settings = UserSettings(  # noqa: SLF001
                nickname="Tester",
                theme="dark",
                log_level="WARNING",
                auto_start_sync=True,
                library_path_initialized=True,
                windows_game_drive_letter="D",
                linux_install_path=str(root / "LAN"),
                linux_windows_runtime="proton-ge",
            )
            try:
                result = app._save_game_metadata_file(  # noqa: SLF001
                    "demo",
                    {"packages": ["d3dx9", "vcrun2019", "d3dx9"]},
                )
                self.assertTrue(result["ok"])
                self.assertEqual(result["message"], "ok")
                self.assertEqual(result["packages"], ["d3dx9", "vcrun2019"])

                metadata_payload = json.loads(
                    (library_root / "demo" / "metadata.json").read_text(encoding="utf-8")
                )
                self.assertFalse((library_root / "demo" / "metadata").exists())
                self.assertEqual(metadata_payload["title"]["en"], "Demo EN")
                self.assertEqual(metadata_payload["title"]["de"], "Demo DE")
                self.assertEqual(metadata_payload["description"]["en"], "Readme EN")
                self.assertEqual(metadata_payload["description"]["de"], "Readme DE")
                self.assertEqual(metadata_payload["key"], "DEMO_KEY")
                self.assertEqual(metadata_payload["release_year"], "2000")
                self.assertEqual(metadata_payload["publisher"], "ETI")
                self.assertEqual(metadata_payload["size_gb"], 1.5)
                self.assertEqual(metadata_payload["max_players"], "8")
                self.assertTrue(metadata_payload["master_required"])
                self.assertEqual(metadata_payload["version"], "1.0")
                self.assertEqual(metadata_payload["genre"]["en"], "Racing")
                self.assertEqual(metadata_payload["genre"]["de"], "Rennspiel")
                self.assertEqual(metadata_payload["genre_id"], 7)
                self.assertEqual(metadata_payload["runner"], "proton-ge")
                self.assertEqual(
                    metadata_payload["installer_tasks"],
                    [
                        {"name": "winetricks", "app": "d3dx9"},
                        {"name": "winetricks", "app": "vcrun2019"},
                    ],
                )
            finally:
                app._server.server_close()  # noqa: SLF001
                db.connection.close()

    def test_save_game_metadata_file_preserves_non_winetricks_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            metadata_root = root / "metadata"
            metadata_root.mkdir(parents=True, exist_ok=True)
            (metadata_root / "demo.jpg").write_bytes(b"jpg")
            (metadata_root / "demo.json").write_text(
                json.dumps(
                    {
                        "title": {"en": "Old EN", "de": "Old DE"},
                        "image": "demo.jpg",
                        "installer_tasks": [
                            {"name": "copy", "src": "a", "dst": "b"},
                            {"name": "winetricks", "app": "oldverb"},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            db = open_database(str(root / "app.db"))
            with db.connection:
                db.connection.execute(
                    "INSERT INTO genres(id, name_en, name_de) VALUES (2, 'Action', 'Action')"
                )
                db.connection.execute(
                    """
                    INSERT INTO game_catalog(
                        id, title_en, title_de, key, release_year, publisher, size_gb,
                        readme_en, readme_de, max_players, master_required, genre_id, version
                    )
                    VALUES (
                        'demo', 'Demo EN', 'Demo DE', 'DEMO_KEY', '2001', 'ETI', 2.0,
                        'Readme EN', 'Readme DE', '4', 0, 2, '2.0'
                    )
                    """
                )

            library_root = root / "LAN"
            app = Application(AppConfig(bind_port=0, library_path=str(library_root)))
            app._state.database = db  # noqa: SLF001
            app._state.repository = CatalogRepository(  # noqa: SLF001
                db.connection,
                metadata_root=metadata_root,
            )
            app._state.metadata_root = metadata_root  # noqa: SLF001
            app._state.metadata_store = MetadataStore(metadata_root)  # noqa: SLF001
            app._state.user_settings = UserSettings(  # noqa: SLF001
                nickname="Tester",
                theme="dark",
                log_level="WARNING",
                auto_start_sync=True,
                library_path_initialized=True,
                windows_game_drive_letter="D",
                linux_install_path=str(root / "LAN"),
                linux_windows_runtime="wine",
            )
            try:
                result = app._save_game_metadata_file(  # noqa: SLF001
                    "demo",
                    {"packages": ["xact"]},
                )
                self.assertTrue(result["ok"])
                self.assertEqual(result["packages"], ["xact"])

                metadata_payload = json.loads(
                    (library_root / "demo" / "metadata.json").read_text(encoding="utf-8")
                )
                self.assertEqual(metadata_payload["image"], "demo.jpg")
                self.assertEqual(
                    metadata_payload["installer_tasks"],
                    [
                        {"name": "copy", "src": "a", "dst": "b"},
                        {"name": "winetricks", "app": "xact"},
                    ],
                )
            finally:
                app._server.server_close()  # noqa: SLF001
                db.connection.close()

    def test_save_game_metadata_file_rejects_invalid_package_selection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            metadata_root = root / "metadata"
            metadata_root.mkdir(parents=True, exist_ok=True)
            db = open_database(str(root / "app.db"))
            with db.connection:
                db.connection.execute(
                    "INSERT INTO genres(id, name_en, name_de) VALUES (1, 'Action', 'Action')"
                )
                db.connection.execute(
                    """
                    INSERT INTO game_catalog(id, title_en, title_de, key, genre_id, version)
                    VALUES ('demo', 'Demo EN', 'Demo DE', 'DEMO_KEY', 1, '1.0')
                    """
                )

            app = Application(AppConfig(bind_port=0, library_path=str(root / "LAN")))
            app._state.database = db  # noqa: SLF001
            app._state.repository = CatalogRepository(  # noqa: SLF001
                db.connection,
                metadata_root=metadata_root,
            )
            app._state.metadata_root = metadata_root  # noqa: SLF001
            app._state.metadata_store = MetadataStore(metadata_root)  # noqa: SLF001
            try:
                result = app._save_game_metadata_file(  # noqa: SLF001
                    "demo",
                    {"packages": ["not-a-winetricks-verb"]},
                )
                self.assertFalse(result["ok"])
                self.assertEqual(result["message"], "invalid_winetricks_package_set")
            finally:
                app._server.server_close()  # noqa: SLF001
                db.connection.close()

    def test_save_game_metadata_file_falls_back_to_library_metadata_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            blocked_metadata_path = root / "metadata"
            blocked_metadata_path.write_text("not-a-directory", encoding="utf-8")
            library_root = root / "LAN"
            db = open_database(str(root / "app.db"))
            with db.connection:
                db.connection.execute(
                    "INSERT INTO genres(id, name_en, name_de) VALUES (3, 'Action', 'Action')"
                )
                db.connection.execute(
                    """
                    INSERT INTO game_catalog(
                        id, title_en, title_de, key, release_year, publisher, size_gb,
                        readme_en, readme_de, max_players, master_required, genre_id, version
                    )
                    VALUES (
                        'demo', 'Demo EN', 'Demo DE', 'DEMO_KEY', '2002', 'ETI', 2.5,
                        'Readme EN', 'Readme DE', '6', 0, 3, '3.0'
                    )
                    """
                )

            app = Application(AppConfig(bind_port=0, library_path=str(library_root)))
            app._state.database = db  # noqa: SLF001
            app._state.repository = CatalogRepository(  # noqa: SLF001
                db.connection,
                metadata_root=blocked_metadata_path,
            )
            app._state.metadata_root = blocked_metadata_path  # noqa: SLF001
            app._state.metadata_store = MetadataStore(blocked_metadata_path)  # noqa: SLF001
            try:
                result = app._save_game_metadata_file(  # noqa: SLF001
                    "demo",
                    {"packages": ["xact"]},
                )
                self.assertTrue(result["ok"])
                fallback_file = library_root / "demo" / "metadata.json"
                self.assertTrue(fallback_file.exists())
                metadata_payload = json.loads(fallback_file.read_text(encoding="utf-8"))
                self.assertEqual(metadata_payload["title"]["en"], "Demo EN")
                self.assertEqual(
                    metadata_payload["installer_tasks"],
                    [{"name": "winetricks", "app": "xact"}],
                )
            finally:
                app._server.server_close()  # noqa: SLF001
                db.connection.close()

    def test_save_local_game_settings_writes_catalog_and_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = open_database(str(root / "app.db"))
            with db.connection:
                db.connection.execute(
                    "INSERT INTO genres(id, name_en, name_de) VALUES (5, 'Adventure', 'Abenteuer')"
                )

            library_root = root / "LAN"
            app = Application(AppConfig(bind_port=0, library_path=str(library_root)))
            app._state.database = db  # noqa: SLF001
            app._state.repository = CatalogRepository(  # noqa: SLF001
                db.connection,
                metadata_root=root / "metadata",
            )
            app._state.user_settings = UserSettings(  # noqa: SLF001
                nickname="Tester",
                theme="dark",
                log_level="WARNING",
                auto_start_sync=True,
                library_path_initialized=True,
                windows_game_drive_letter="D",
                linux_install_path=str(library_root),
            )
            try:
                result = app._local_game_settings_update(  # noqa: SLF001
                    {
                        "item": {
                            "game_id": "local-demo",
                            "title_en": "Local Demo",
                            "title_de": "Lokale Demo",
                            "genre_id": 5,
                            "release_year": "1999",
                            "publisher": "LAN",
                            "size_gb": 12.5,
                            "max_players": "4",
                            "version": "1.0",
                            "game_start_file": "game_start.sh",
                            "game_start_args": "--fullscreen\n--debug",
                            "readme_en": "Local description EN",
                            "readme_de": "Lokale Beschreibung DE",
                        }
                    }
                )
                self.assertTrue(result["ok"])
                self.assertEqual(result["game_id"], "local-demo")
                game = app._state.repository.get_game("local-demo", locale="en")  # noqa: SLF001
                self.assertIsNotNone(game)
                assert game is not None
                self.assertEqual(game["game_provider_type"], "local")
                self.assertEqual(game["title"], "Local Demo")
                metadata_file = library_root / "local-demo" / "metadata.json"
                self.assertTrue(metadata_file.exists())
                metadata_payload = json.loads(metadata_file.read_text(encoding="utf-8"))
                self.assertEqual(metadata_payload["title"]["en"], "Local Demo")
                self.assertEqual(metadata_payload["game_start"]["file"], "game_start.sh")
                self.assertEqual(metadata_payload["game_start"]["args"], ["--fullscreen", "--debug"])
            finally:
                app._server.server_close()  # noqa: SLF001
                db.connection.close()


if __name__ == "__main__":
    unittest.main()
