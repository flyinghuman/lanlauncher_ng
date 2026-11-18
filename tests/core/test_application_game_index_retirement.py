"""OSGI index removal respects the local installation lifecycle."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from src.core.catalog.game_index import GameIndexStore
from src.core.catalog.repository import CatalogRepository, ListQuery
from src.core.config.loader import AppConfig
from src.core.db.store import open_database
from src.core.service.app import Application
from tests.core.publisher_trust_fixtures import (
    ROOT_KEYS,
    publisher_registry,
    signed_index,
)


class GameIndexRetirementTests(unittest.TestCase):
    def test_verified_ouisync_index_game_appears_in_main_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database = open_database(str(root / "app.db"))
            library = root / "library"
            update_dir = library / "ng_provider" / "update"
            update_dir.mkdir(parents=True)
            (update_dir / "trusted-publishers.json").write_text(
                json.dumps(publisher_registry(1)), encoding="utf-8"
            )
            index_path = update_dir / "index.json"
            index_path.write_text(
                json.dumps(
                    signed_index(
                        {
                            "game_id": "0ad",
                            "title": {"en": "0 A.D.", "de": "0 A.D."},
                            "description": {
                                "en": "Historical strategy game.",
                                "de": "Historisches Strategiespiel.",
                            },
                            "version": "20261108",
                            "size_gb": 8.1,
                            "lan_supported": True,
                            "game_provider_type": "ouisync",
                            "distribution": {
                                "schema_version": 1,
                                "archive": {
                                    "file": "0ad.tar.gz",
                                    "format": "tar.gz",
                                    "sha256": "a" * 64,
                                    "version_file": "version.ini",
                                },
                            },
                            "llng": {
                                "schema_version": 1,
                                "distribution": {
                                    "provider": "ouisync",
                                    "read_token": "test-read-only-token",
                                    "info_hash": "ab" * 20,
                                },
                            },
                        }
                    ),
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            index_store = GameIndexStore(
                index_url="",
                cache_path=root / "cache" / "index.json",
                local_index_path=index_path,
                trust_root_public_keys=ROOT_KEYS,
            )
            repository = CatalogRepository(
                database.connection, metadata_lookup=index_store.get
            )
            app = Application(AppConfig(bind_port=0, library_path=str(library)))
            app._state.repository = repository  # noqa: SLF001
            app._state.game_index_store = index_store  # noqa: SLF001
            try:
                app._refresh_game_index_if_changed()  # noqa: SLF001

                result = repository.list_games(
                    ListQuery(locale="en", page_size=25)
                )

                self.assertEqual(result["total"], 1)
                self.assertEqual(result["items"][0]["id"], "0ad")
                self.assertEqual(result["items"][0]["title"], "0 A.D.")
                self.assertEqual(result["items"][0]["version"], "20261108")
                self.assertEqual(
                    result["items"][0]["game_provider_type"], "ouisync"
                )
                self.assertEqual(result["items"][0]["install_state"], "missing")
                self.assertNotIn("test-read-only-token", json.dumps(result))
            finally:
                app._server.server_close()  # noqa: SLF001
                database.connection.close()

    def test_removed_installed_game_is_deleted_after_uninstall(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database = open_database(str(root / "app.db"))
            with database.connection:
                database.connection.execute(
                    "INSERT INTO game_catalog(id, title_en, title_de, key, version) "
                    "VALUES ('demo', 'Demo', 'Demo', 'DEMO', '1.0')"
                )
                database.connection.execute(
                    "INSERT INTO games(id, title_en, title_de, version) "
                    "VALUES ('demo', 'Demo', 'Demo', '1.0')"
                )
                database.connection.execute(
                    "INSERT INTO game_catalog(id, title_en, title_de, key, version) "
                    "VALUES ('not-installed', 'Not installed', 'Not installiert', 'OTHER', '1.0')"
                )
                database.connection.execute(
                    "INSERT INTO games(id, title_en, title_de, version) "
                    "VALUES ('not-installed', 'Not installed', 'Not installiert', '1.0')"
                )
            repository = CatalogRepository(database.connection)
            repository.set_install_state("demo", "installed", "1.0")
            library = root / "library"
            installed_local = library / "demo" / "local"
            installed_local.mkdir(parents=True)

            index_path = root / "ng_provider" / "update" / "index.json"
            index_path.parent.mkdir(parents=True)
            index_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "games": [
                            {
                                "game_id": "demo",
                                "title": "Demo",
                                "game_provider_type": "ouisync",
                            },
                            {
                                "game_id": "not-installed",
                                "title": "Not installed",
                                "game_provider_type": "ouisync",
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            index_store = GameIndexStore(
                index_url="",
                cache_path=root / "cache" / "index.json",
                local_index_path=index_path,
            )
            self.assertTrue(index_store.refresh(force=True))

            app = Application(AppConfig(bind_port=0, library_path=str(library)))
            app._state.repository = repository  # noqa: SLF001
            app._state.game_index_store = index_store  # noqa: SLF001
            try:
                app._refresh_game_index_if_changed()  # noqa: SLF001
                old_stat = index_path.stat()
                index_path.write_text(
                    json.dumps({"schema_version": 1, "games": []}),
                    encoding="utf-8",
                )
                os.utime(
                    index_path,
                    ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns + 1_000_000_000),
                )

                app._refresh_game_index_if_changed()  # noqa: SLF001
                self.assertIsNotNone(repository.get_game("demo", locale="en"))
                self.assertIsNone(repository.get_game("not-installed", locale="en"))
                pending = database.connection.execute(
                    "SELECT pending_removal FROM game_index_catalog_entries "
                    "WHERE game_id = 'demo' COLLATE NOCASE"
                ).fetchone()
                self.assertEqual(pending[0], 1)

                shutil.rmtree(installed_local)
                repository.set_install_state("demo", "missing", "")
                app._refresh_game_index_if_changed()  # noqa: SLF001

                self.assertIsNone(repository.get_game("demo", locale="en"))
                remaining = database.connection.execute(
                    "SELECT 1 FROM game_index_catalog_entries "
                    "WHERE game_id = 'demo' COLLATE NOCASE"
                ).fetchone()
                self.assertIsNone(remaining)
            finally:
                app._server.server_close()  # noqa: SLF001
                database.connection.close()


if __name__ == "__main__":
    unittest.main()
