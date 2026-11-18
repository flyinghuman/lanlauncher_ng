"""Tests for catalog import and querying."""

from __future__ import annotations

import sqlite3
import tempfile
from dataclasses import replace
import unittest
from pathlib import Path

from src.core.catalog.importer import import_legacy_catalog
from src.core.catalog.metadata import GameMetadata
from src.core.catalog.repository import CatalogRepository, ListQuery
from src.core.db.store import open_database


class CatalogImportTests(unittest.TestCase):
    def test_list_game_provider_types_returns_catalog_and_extra_item_providers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = open_database(str(Path(tmp) / "target.db"))
            with db.connection:
                db.connection.execute(
                    "INSERT INTO game_catalog(id, title_en, title_de, key, game_provider_type) "
                    "VALUES ('global', 'Global', 'Global', 'OUISYNC_TOKEN', 'Ouisync')"
                )
                db.connection.execute(
                    "INSERT INTO extra_sync_items(game_id, game_key, title_en, game_provider_type) "
                    "VALUES ('legacy', 'KEY', 'Legacy', 'Resilio')"
                )
                db.connection.execute(
                    "INSERT INTO game_catalog(id, title_en, title_de, key, game_provider_type) "
                    "VALUES ('local', 'Local', 'Local', '', 'local')"
                )

            repo = CatalogRepository(db.connection)
            self.assertEqual(repo.list_game_provider_types(), {"ouisync", "resilio"})
            db.connection.close()

    def _create_legacy_db(self, path: Path, version: str) -> None:
        conn = sqlite3.connect(path)
        try:
            conn.execute(
                "CREATE TABLE genre (genre_id INTEGER PRIMARY KEY, genre_en TEXT, genre_de TEXT)"
            )
            conn.execute(
                """
                CREATE TABLE games (
                    game_id TEXT PRIMARY KEY,
                    game_title TEXT,
                    game_key TEXT,
                    game_release TEXT,
                    game_publisher TEXT,
                    game_size REAL,
                    game_readme_en TEXT,
                    game_readme_de TEXT,
                    game_maxplayers TEXT,
                    game_master_req INTEGER,
                    genre_id INTEGER,
                    game_version TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE tools (
                    tool_id TEXT PRIMARY KEY,
                    tool_name TEXT,
                    tool_key TEXT,
                    tool_maintainer TEXT,
                    tool_size REAL,
                    tool_readme_en TEXT,
                    tool_readme_de TEXT,
                    tool_disabled INTEGER
                )
                """
            )
            conn.execute(
                "INSERT INTO genre(genre_id, genre_en, genre_de) VALUES (1, 'Action', 'Action')"
            )
            conn.execute(
                """
                INSERT INTO games(
                    game_id, game_title, game_key, game_release, game_publisher, game_size,
                    game_readme_en, game_readme_de, game_maxplayers, game_master_req, genre_id, game_version
                )
                VALUES ('demo', 'Demo Game', 'DEMO', '2020', 'ETI', 1.0, 'Readme EN', 'Readme DE', '8', 0, 1, ?)
                """,
                (version,),
            )
            conn.execute(
                """
                INSERT INTO tools(tool_id, tool_name, tool_key, tool_maintainer, tool_size, tool_readme_en, tool_readme_de, tool_disabled)
                VALUES ('sync', 'Sync', 'SYNC', 'ETI', 1.0, 'Sync EN', 'Sync DE', 0)
                """
            )
            conn.commit()
        finally:
            conn.close()

    def test_import_legacy_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = open_database(str(Path(tmp) / "target.db"))
            legacy_db = Path(tmp) / "old-game.db"
            self._create_legacy_db(legacy_db, version="20161234")
            summary = import_legacy_catalog(db.connection, str(legacy_db))

            self.assertGreater(summary["games"], 0)
            self.assertGreater(summary["genres"], 0)

            repo = CatalogRepository(db.connection)
            result = repo.list_games(ListQuery(page_size=10))
            self.assertGreater(result["total"], 0)
            db.connection.close()

    def test_list_and_get_localized_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = open_database(str(Path(tmp) / "target.db"))
            with db.connection:
                db.connection.execute(
                    "INSERT INTO genres(id, name_en, name_de) VALUES (1, 'Shooter', 'Shooter')"
                )
                db.connection.execute(
                    """
                    INSERT INTO game_catalog(id, title_en, title_de, key, size_gb, max_players, genre_id, version)
                    VALUES ('demo', 'Demo Game', 'Demo Spiel', 'KEY', 1.2, '8', 1, '1')
                    """
                )

            repo = CatalogRepository(db.connection)
            en = repo.get_game("demo", locale="en")
            de = repo.get_game("demo", locale="de")
            self.assertEqual(en["title"], "Demo Game")
            self.assertEqual(de["title"], "Demo Spiel")
            targets = repo.list_sync_targets()
            self.assertEqual(len(targets), 1)
            self.assertEqual(targets[0]["id"], "demo")
            self.assertEqual(targets[0]["key"], "KEY")
            db.connection.close()

    def test_list_games_exposes_provider_type_and_skips_local_sync_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = open_database(str(Path(tmp) / "target.db"))
            with db.connection:
                db.connection.execute(
                    "INSERT INTO game_catalog(id, title_en, title_de, key, game_provider_type) VALUES ('local-demo', 'Local Demo', 'Lokale Demo', 'LOCAL', 'local')"
                )
                db.connection.execute(
                    "INSERT INTO game_catalog(id, title_en, title_de, key, game_provider_type) VALUES ('sync-demo', 'Sync Demo', 'Sync Demo', 'SYNC', 'resilio')"
                )
            repo = CatalogRepository(db.connection)
            payload = repo.list_games(ListQuery(page_size=10))
            providers = {item["id"]: item["game_provider_type"] for item in payload["items"]}
            self.assertEqual(providers["local-demo"], "local")
            self.assertEqual(providers["sync-demo"], "resilio")
            targets = repo.list_sync_targets()
            self.assertEqual([row["id"] for row in targets], ["sync-demo"])
            db.connection.close()

    def test_hidden_games_are_only_returned_in_hidden_visibility(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = open_database(str(Path(tmp) / "target.db"))
            with db.connection:
                db.connection.execute(
                    "INSERT INTO game_catalog(id, title_en, title_de, key) VALUES ('visible', 'Visible', 'Sichtbar', 'V')"
                )
                db.connection.execute(
                    "INSERT INTO game_catalog(id, title_en, title_de, key, hidden) VALUES ('hidden', 'Hidden', 'Ausgeblendet', 'H', 1)"
                )
            repo = CatalogRepository(db.connection)
            visible = repo.list_games(ListQuery(page_size=0))
            hidden = repo.list_games(ListQuery(page_size=0, visibility="hidden"))
            self.assertEqual([item["id"] for item in visible["items"]], ["visible"])
            self.assertEqual([item["id"] for item in hidden["items"]], ["hidden"])
            self.assertTrue(hidden["items"][0]["hidden"])
            self.assertTrue(repo.set_game_hidden("hidden", False))
            self.assertEqual(repo.list_games(ListQuery(page_size=0))["total"], 2)
            db.connection.close()

    def test_list_includes_metadata_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = open_database(str(Path(tmp) / "target.db"))
            metadata_root = Path(tmp) / "metadata"
            metadata_root.mkdir()
            (metadata_root / "demo.json").write_text(
                '{"title":{"en":"Meta Title","de":"Meta Titel"},'
                '"description":{"en":"Meta DESC EN","de":"Meta DESC DE"},'
                '"publisher":"Meta Publisher",'
                '"release_year":"2000",'
                '"size_gb":3.2,'
                '"max_players":"12",'
                '"version":"9999",'
                '"genre":{"en":"Arcade","de":"Arkade"},'
                '"runner":"wine","game_start":{"file":"game_start.cmd","args":[]},'
                '"website_url":"https://example.org/game",'
                '"links":[{"label":{"en":"Discord","de":"Discord"},'
                '"url":"https://example.org/discord"}],'
                '"image":"metadata/demo.jpg"}',
                encoding="utf-8",
            )
            with db.connection:
                db.connection.execute(
                    "INSERT INTO genres(id, name_en, name_de) VALUES (1, 'Shooter', 'Shooter')"
                )
                db.connection.execute(
                    """
                    INSERT INTO game_catalog(id, title_en, title_de, key, size_gb, max_players, genre_id, version)
                    VALUES ('demo', 'Demo Game', 'Demo Spiel', 'KEY', 1.2, '8', 1, '1')
                    """
                )

            repo = CatalogRepository(db.connection, metadata_root=metadata_root)
            payload = repo.list_games(ListQuery(page_size=10))
            self.assertEqual(len(payload["items"]), 1)
            item = payload["items"][0]
            self.assertEqual(item["title"], "Meta Title")
            self.assertEqual(item["readme"], "Meta DESC EN")
            self.assertEqual(item["publisher"], "Meta Publisher")
            self.assertEqual(item["release_year"], "2000")
            self.assertEqual(item["size_gb"], 3.2)
            self.assertEqual(item["max_players"], "12")
            self.assertEqual(item["version"], "9999")
            self.assertEqual(item["genre"], "Arcade")
            self.assertEqual(item["metadata"]["title"]["en"], "Meta Title")
            self.assertEqual(item["metadata"]["links"][0]["url"], "https://example.org/discord")
            detail = repo.get_game("demo", locale="de")
            self.assertIsNotNone(detail)
            assert detail is not None
            self.assertEqual(detail["title"], "Meta Titel")
            self.assertEqual(detail["readme"], "Meta DESC DE")
            self.assertEqual(detail["genre"], "Arkade")
            db.connection.close()

    def test_metadata_lookup_callback_overrides_when_file_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = open_database(str(Path(tmp) / "target.db"))
            with db.connection:
                db.connection.execute(
                    "INSERT INTO genres(id, name_en, name_de) VALUES (1, 'Shooter', 'Shooter')"
                )
                db.connection.execute(
                    """
                    INSERT INTO game_catalog(id, title_en, title_de, key, size_gb, max_players, genre_id, version)
                    VALUES ('demo', 'Demo Game', 'Demo Spiel', 'KEY', 1.2, '8', 1, '1')
                    """
                )
            repo = CatalogRepository(
                db.connection,
                metadata_root=Path(tmp) / "missing-metadata-root",
                metadata_lookup=lambda game_id: (
                    GameMetadata(
                        game_id=game_id,
                        title="Callback Title",
                        description="Callback Description",
                    )
                    if game_id == "demo"
                    else None
                ),
            )
            detail = repo.get_game("demo", locale="en")
            self.assertIsNotNone(detail)
            assert detail is not None
            self.assertEqual(detail["title"], "Callback Title")
            self.assertEqual(detail["readme"], "Callback Description")
            db.connection.close()

    def test_import_overwrites_existing_game_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = root / "legacy.db"
            self._create_legacy_db(legacy, version="1.0")

            db = open_database(str(root / "target.db"))
            import_legacy_catalog(db.connection, str(legacy))

            # Simulate upstream database update with new game version.
            conn = sqlite3.connect(legacy)
            try:
                conn.execute(
                    "UPDATE games SET game_version = '2.0' WHERE game_id = 'demo'"
                )
                conn.commit()
            finally:
                conn.close()

            import_legacy_catalog(db.connection, str(legacy))
            repo = CatalogRepository(db.connection)
            game = repo.get_game("demo", locale="en")
            self.assertIsNotNone(game)
            assert game is not None
            self.assertEqual(game["version"], "2.0")
            db.connection.close()

    def test_import_does_not_downgrade_existing_higher_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = root / "legacy.db"
            self._create_legacy_db(legacy, version="20260101")

            db = open_database(str(root / "target.db"))
            import_legacy_catalog(db.connection, str(legacy))

            conn = sqlite3.connect(legacy)
            try:
                conn.execute(
                    "UPDATE games SET game_version = '20250101' WHERE game_id = 'demo'"
                )
                conn.commit()
            finally:
                conn.close()

            import_legacy_catalog(db.connection, str(legacy))
            repo = CatalogRepository(db.connection)
            game = repo.get_game("demo", locale="en")
            self.assertIsNotNone(game)
            assert game is not None
            self.assertEqual(game["version"], "20260101")
            db.connection.close()

    def test_list_games_page_size_zero_returns_all_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = open_database(str(Path(tmp) / "target.db"))
            with db.connection:
                db.connection.execute(
                    "INSERT INTO genres(id, name_en, name_de) VALUES (1, 'Action', 'Action')"
                )
                for idx in range(140):
                    db.connection.execute(
                        """
                        INSERT INTO game_catalog(id, title_en, title_de, key, size_gb, max_players, genre_id, version)
                        VALUES (?, ?, ?, ?, 1.0, '8', 1, '1.0')
                        """,
                        (
                            f"game{idx:03d}",
                            f"Game {idx:03d}",
                            f"Spiel {idx:03d}",
                            f"KEY{idx:03d}",
                        ),
                    )

            repo = CatalogRepository(db.connection)
            payload = repo.list_games(ListQuery(page_size=0))
            self.assertEqual(payload["total"], 140)
            self.assertEqual(len(payload["items"]), 140)
            db.connection.close()

    def test_list_games_excludes_disabled_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = open_database(str(Path(tmp) / "target.db"))
            with db.connection:
                db.connection.execute(
                    "INSERT INTO genres(id, name_en, name_de) VALUES (1, 'Action', 'Action')"
                )
                db.connection.execute(
                    """
                    INSERT INTO game_catalog(id, title_en, title_de, key, size_gb, max_players, genre_id, version)
                    VALUES ('visible', 'Visible', 'Sichtbar', 'KEY1', 1.0, '8', 1, '1.0')
                    """
                )
                db.connection.execute(
                    """
                    INSERT INTO game_catalog(id, title_en, title_de, key, size_gb, max_players, genre_id, version)
                    VALUES ('hidden', 'Hidden', 'Versteckt', 'KEY2', 1.0, '8', 1, '1.0')
                    """
                )
            repo = CatalogRepository(db.connection)
            payload = repo.list_games(ListQuery(page_size=0, excluded_ids=("hidden",)))
            self.assertEqual(payload["total"], 1)
            self.assertEqual(len(payload["items"]), 1)
            self.assertEqual(payload["items"][0]["id"], "visible")
            db.connection.close()

    def test_lan_disabled_games_remain_visible_only_when_installed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = open_database(str(Path(tmp) / "target.db"))
            with db.connection:
                db.connection.execute(
                    "INSERT INTO genres(id, name_en, name_de) VALUES (1, 'Action', 'Action')"
                )
                for game_id in ("installed", "missing"):
                    db.connection.execute(
                        """
                        INSERT INTO game_catalog(id, title_en, title_de, key, size_gb, max_players, genre_id, version)
                        VALUES (?, ?, ?, ?, 1.0, '8', 1, '1.0')
                        """,
                        (game_id, game_id, game_id, game_id.upper()),
                    )
            repo = CatalogRepository(db.connection)
            repo.set_install_state("installed", "installed", "1.0")
            payload = repo.list_games(
                ListQuery(page_size=0, disabled_ids=("INSTALLED", "MISSING"))
            )
            self.assertEqual([item["id"] for item in payload["items"]], ["installed"])
            db.connection.close()

    def test_needs_update_flag_when_installed_version_differs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = open_database(str(Path(tmp) / "target.db"))
            with db.connection:
                db.connection.execute(
                    "INSERT INTO genres(id, name_en, name_de) VALUES (1, 'Action', 'Action')"
                )
                db.connection.execute(
                    """
                    INSERT INTO game_catalog(id, title_en, title_de, key, size_gb, max_players, genre_id, version)
                    VALUES ('demo', 'Demo Game', 'Demo Spiel', 'KEY', 1.2, '8', 1, '2.0')
                    """
                )
            repo = CatalogRepository(db.connection)
            repo.set_install_state("demo", "installed", "1.0")
            payload = repo.list_games(ListQuery(page_size=0))
            self.assertEqual(payload["items"][0]["id"], "demo")
            self.assertTrue(payload["items"][0]["needs_update"])
            detail = repo.get_game("demo", locale="en")
            self.assertIsNotNone(detail)
            assert detail is not None
            self.assertTrue(detail["needs_update"])
            db.connection.close()

    def test_index_version_marks_updates_and_updates_filter_uses_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = open_database(str(Path(tmp) / "target.db"))
            with db.connection:
                db.connection.execute(
                    "INSERT INTO genres(id, name_en, name_de) VALUES (1, 'Action', 'Action')"
                )
                db.connection.execute(
                    "INSERT INTO game_catalog(id, title_en, title_de, key, genre_id, version) "
                    "VALUES ('demo', 'Demo', 'Demo', 'K', 1, '1.0')"
                )
            metadata = GameMetadata(
                game_id="demo",
                title="Demo",
                version="2.0",
                game_provider_type="ouisync",
            )
            repo = CatalogRepository(
                db.connection, metadata_lookup=lambda _game_id: metadata
            )
            repo.set_install_state("demo", "installed", "1.0")

            updates = repo.list_games(ListQuery(installed="updates", page_size=25))
            all_games = repo.list_games(ListQuery(page_size=25))

            self.assertEqual(updates["total"], 1)
            self.assertEqual(updates["items"][0]["version"], "2.0")
            self.assertTrue(updates["items"][0]["needs_update"])
            self.assertTrue(all_games["items"][0]["needs_update"])
            db.connection.close()

    def test_list_genres_localized(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = open_database(str(Path(tmp) / "target.db"))
            with db.connection:
                db.connection.execute(
                    "INSERT INTO genres(id, name_en, name_de) VALUES (1, 'Action', 'Action')"
                )
                db.connection.execute(
                    "INSERT INTO genres(id, name_en, name_de) VALUES (2, 'Shooter', 'Shooter DE')"
                )

            repo = CatalogRepository(db.connection)
            en = repo.list_genres(locale="en")
            de = repo.list_genres(locale="de")
            self.assertEqual([item["name"] for item in en], ["Action", "Shooter"])
            self.assertEqual([item["name"] for item in de], ["Action", "Shooter DE"])
            db.connection.close()

    def test_updates_filter_returns_only_games_with_available_update(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = open_database(str(Path(tmp) / "target.db"))
            with db.connection:
                db.connection.execute(
                    "INSERT INTO genres(id, name_en, name_de) VALUES (1, 'Action', 'Action')"
                )
                db.connection.execute(
                    """
                    INSERT INTO game_catalog(id, title_en, title_de, key, size_gb, max_players, genre_id, version)
                    VALUES ('demo_old', 'Demo Old', 'Demo Alt', 'KEY1', 1.2, '8', 1, '2.0')
                    """
                )
                db.connection.execute(
                    """
                    INSERT INTO game_catalog(id, title_en, title_de, key, size_gb, max_players, genre_id, version)
                    VALUES ('demo_new', 'Demo New', 'Demo Neu', 'KEY2', 1.2, '8', 1, '2.0')
                    """
                )
            repo = CatalogRepository(db.connection)
            repo.set_install_state("demo_old", "installed", "1.0")
            repo.set_install_state("demo_new", "installed", "2.0")
            payload = repo.list_games(ListQuery(installed="updates", page_size=0))
            self.assertEqual(payload["total"], 1)
            self.assertEqual(len(payload["items"]), 1)
            self.assertEqual(payload["items"][0]["id"], "demo_old")
            db.connection.close()

    def test_version_sort_desc_orders_by_newest_update_date(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = open_database(str(Path(tmp) / "target.db"))
            with db.connection:
                db.connection.execute(
                    "INSERT INTO genres(id, name_en, name_de) VALUES (1, 'Action', 'Action')"
                )
                db.connection.execute(
                    """
                    INSERT INTO game_catalog(id, title_en, title_de, key, size_gb, max_players, genre_id, version)
                    VALUES ('older', 'Older', 'Aelter', 'KEY1', 1.0, '8', 1, '20240101')
                    """
                )
                db.connection.execute(
                    """
                    INSERT INTO game_catalog(id, title_en, title_de, key, size_gb, max_players, genre_id, version)
                    VALUES ('newer', 'Newer', 'Neuer', 'KEY2', 1.0, '8', 1, '20250101')
                    """
                )
            repo = CatalogRepository(db.connection)
            payload = repo.list_games(
                ListQuery(sort="version", order="desc", page_size=0)
            )
            self.assertEqual(payload["total"], 2)
            self.assertEqual(payload["items"][0]["id"], "newer")
            self.assertEqual(payload["items"][1]["id"], "older")
            db.connection.close()


class GameIndexMembershipTests(unittest.TestCase):
    def test_reconcile_catalog_preserves_user_hidden_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = open_database(str(Path(tmp) / "target.db"))
            repo = CatalogRepository(db.connection)
            entry = GameMetadata(
                game_id="indexed", title="Indexed", version="1.0",
                game_provider_type="ouisync",
            )
            repo.reconcile_game_index_catalog([entry])
            self.assertTrue(repo.set_game_hidden("indexed", True))

            repo.reconcile_game_index_catalog([replace(entry, version="1.1")])

            row = db.connection.execute(
                "SELECT hidden, version FROM game_catalog WHERE id = 'indexed'"
            ).fetchone()
            self.assertEqual(tuple(row), (1, "1.1"))
            db.connection.close()

    def test_reconcile_marks_missing_entries_pending_and_clears_on_readd(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = open_database(str(Path(tmp) / "target.db"))
            repo = CatalogRepository(db.connection)

            self.assertEqual(repo.reconcile_game_index_membership({"demo", "other"}), [])
            self.assertEqual(repo.reconcile_game_index_membership({"other"}), ["demo"])
            self.assertEqual(repo.reconcile_game_index_membership({"DEMO", "other"}), [])

            row = db.connection.execute(
                "SELECT present, pending_removal FROM game_index_catalog_entries "
                "WHERE game_id = 'demo' COLLATE NOCASE"
            ).fetchone()
            self.assertEqual(tuple(row), (1, 0))
            db.connection.close()


if __name__ == "__main__":
    unittest.main()
