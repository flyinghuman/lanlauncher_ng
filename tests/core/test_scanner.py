"""Tests for install-state scanner cache invalidation."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.core.catalog.install_support import InstallSupport
from src.core.catalog.repository import CatalogRepository
from src.core.catalog.scanner import InstallStateScanner
from src.core.db.store import open_database


class InstallScannerTests(unittest.TestCase):
    def test_scanner_updates_install_state_and_respects_ttl(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            library = tmp_path / "library"
            library.mkdir(parents=True, exist_ok=True)

            db = open_database(str(tmp_path / "app.db"))
            with db.connection:
                db.connection.execute(
                    "INSERT INTO game_catalog(id, title_en, title_de, key) VALUES ('g1', 'G1', 'G1', 'K1')"
                )
                db.connection.execute(
                    "INSERT INTO game_catalog(id, title_en, title_de, key) VALUES ('g2', 'G2', 'G2', 'K2')"
                )

            (library / "g1").mkdir(parents=True, exist_ok=True)
            checks = tmp_path / "checks.json"
            checks.write_text(
                '{"games":{"g1":{"markers":["installed.ok"]},"g2":{"markers":["installed.ok"]}}}',
                encoding="utf-8",
            )
            (library / "g1" / "installed.ok").write_text("ok", encoding="utf-8")

            repo = CatalogRepository(db.connection)
            support = InstallSupport(
                scripts_root=str(tmp_path / "scripts"),
                checks_path=str(checks),
            )
            scanner = InstallStateScanner(repo, str(library), support, ttl_seconds=999)
            first = scanner.scan(force=True)
            second = scanner.scan(force=False)

            self.assertEqual(first.scanned, 2)
            self.assertEqual(first.installed, 1)
            self.assertEqual(first.missing, 1)
            self.assertEqual(second.scanned, 0)
            db.connection.close()

    def test_scanner_library_path_can_be_updated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            first_library = tmp_path / "lib-a"
            second_library = tmp_path / "lib-b"
            first_library.mkdir(parents=True, exist_ok=True)
            second_library.mkdir(parents=True, exist_ok=True)
            (second_library / "g1" / "local").mkdir(parents=True, exist_ok=True)

            db = open_database(str(tmp_path / "app.db"))
            with db.connection:
                db.connection.execute(
                    "INSERT INTO game_catalog(id, title_en, title_de, key) VALUES ('g1', 'G1', 'G1', 'K1')"
                )

            checks = tmp_path / "checks.json"
            checks.write_text('{"games":{}}', encoding="utf-8")
            repo = CatalogRepository(db.connection)
            support = InstallSupport(str(tmp_path / "scripts"), str(checks))
            scanner = InstallStateScanner(
                repo, str(first_library), support, ttl_seconds=999
            )

            first = scanner.scan(force=True)
            self.assertEqual(first.installed, 0)

            (second_library / "g1" / "game_start.sh").write_text(
                "#!/usr/bin/env bash\n",
                encoding="utf-8",
            )
            scanner.set_library_path(str(second_library))
            second = scanner.scan(force=False)
            self.assertEqual(second.installed, 1)
            db.connection.close()

    def test_scanner_accepts_plain_text_version_ini(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            library = tmp_path / "library"
            game_dir = library / "g1"
            game_dir.mkdir(parents=True, exist_ok=True)
            (game_dir / "version.ini").write_text("20161024\n", encoding="utf-8")
            (game_dir / "local").mkdir(parents=True, exist_ok=True)
            (game_dir / "game_start.sh").write_text(
                "#!/usr/bin/env bash\n",
                encoding="utf-8",
            )

            db = open_database(str(tmp_path / "app.db"))
            with db.connection:
                db.connection.execute(
                    "INSERT INTO game_catalog(id, title_en, title_de, key, version) VALUES ('g1', 'G1', 'G1', 'K1', '20250101')"
                )

            checks = tmp_path / "checks.json"
            checks.write_text('{"games":{}}', encoding="utf-8")
            repo = CatalogRepository(db.connection)
            support = InstallSupport(str(tmp_path / "scripts"), str(checks))
            scanner = InstallStateScanner(repo, str(library), support, ttl_seconds=999)

            stats = scanner.scan(force=True)
            self.assertEqual(stats.installed, 1)
            detail = repo.get_game("g1", locale="en")
            self.assertIsNotNone(detail)
            assert detail is not None
            self.assertEqual(detail["installed_version"], "20161024")
            self.assertTrue(detail["needs_update"])
            db.connection.close()

    def test_scanner_requires_local_folder_and_game_start_script(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            library = tmp_path / "library"
            game_dir = library / "g1"
            game_dir.mkdir(parents=True, exist_ok=True)

            db = open_database(str(tmp_path / "app.db"))
            with db.connection:
                db.connection.execute(
                    "INSERT INTO game_catalog(id, title_en, title_de, key) VALUES ('g1', 'G1', 'G1', 'K1')"
                )

            checks = tmp_path / "checks.json"
            checks.write_text('{"games":{}}', encoding="utf-8")
            repo = CatalogRepository(db.connection)
            support = InstallSupport(str(tmp_path / "scripts"), str(checks))
            scanner = InstallStateScanner(repo, str(library), support, ttl_seconds=999)

            (game_dir / "local").mkdir(parents=True, exist_ok=True)
            stats_local_only = scanner.scan(force=True)
            self.assertEqual(stats_local_only.installed, 0)

            (game_dir / "game_start.sh").write_text(
                "#!/usr/bin/env bash\n",
                encoding="utf-8",
            )
            stats_ready = scanner.scan(force=True)
            self.assertEqual(stats_ready.installed, 1)
            db.connection.close()

    def test_scanner_treats_local_games_as_playable_with_start_script_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            library = tmp_path / "library"
            game_dir = library / "local-demo"
            game_dir.mkdir(parents=True, exist_ok=True)
            (game_dir / "game_start.sh").write_text(
                "#!/usr/bin/env bash\n",
                encoding="utf-8",
            )

            db = open_database(str(tmp_path / "app.db"))
            with db.connection:
                db.connection.execute(
                    """
                    INSERT INTO game_catalog(id, title_en, title_de, key, game_provider_type)
                    VALUES ('local-demo', 'Local Demo', 'Lokale Demo', 'K1', 'local')
                    """
                )

            checks = tmp_path / "checks.json"
            checks.write_text('{"games":{}}', encoding="utf-8")
            repo = CatalogRepository(db.connection)
            support = InstallSupport(str(tmp_path / "scripts"), str(checks))
            scanner = InstallStateScanner(repo, str(library), support, ttl_seconds=999)

            stats = scanner.scan(force=True)
            self.assertEqual(stats.installed, 1)
            detail = repo.get_game("local-demo", locale="en")
            self.assertIsNotNone(detail)
            assert detail is not None
            self.assertEqual(detail["install_state"], "installed")
            db.connection.close()

    def test_scanner_keeps_installing_state_when_game_folder_not_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            library = tmp_path / "library"
            library.mkdir(parents=True, exist_ok=True)

            db = open_database(str(tmp_path / "app.db"))
            with db.connection:
                db.connection.execute(
                    "INSERT INTO game_catalog(id, title_en, title_de, key) VALUES ('g1', 'G1', 'G1', 'K1')"
                )

            checks = tmp_path / "checks.json"
            checks.write_text('{"games":{}}', encoding="utf-8")
            repo = CatalogRepository(db.connection)
            repo.set_install_state("g1", "installing", "")
            support = InstallSupport(str(tmp_path / "scripts"), str(checks))
            scanner = InstallStateScanner(repo, str(library), support, ttl_seconds=999)

            scanner.scan(force=True)
            self.assertEqual(repo.current_install_state("g1"), "installing")
            db.connection.close()

    def test_scanner_keeps_downloading_state_when_game_folder_not_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            library = tmp_path / "library"
            library.mkdir(parents=True, exist_ok=True)

            db = open_database(str(tmp_path / "app.db"))
            with db.connection:
                db.connection.execute(
                    "INSERT INTO game_catalog(id, title_en, title_de, key) VALUES ('g1', 'G1', 'G1', 'K1')"
                )

            checks = tmp_path / "checks.json"
            checks.write_text('{"games":{}}', encoding="utf-8")
            repo = CatalogRepository(db.connection)
            repo.set_install_state("g1", "downloading", "")
            support = InstallSupport(str(tmp_path / "scripts"), str(checks))
            scanner = InstallStateScanner(repo, str(library), support, ttl_seconds=999)

            scanner.scan(force=True)
            self.assertEqual(repo.current_install_state("g1"), "downloading")
            db.connection.close()


if __name__ == "__main__":
    unittest.main()
