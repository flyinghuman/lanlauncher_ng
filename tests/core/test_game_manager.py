"""Tests for game lifecycle manager logic."""

from __future__ import annotations

import json
import hashlib
import io
import os
import stat
import subprocess
import tempfile
import threading
import tarfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from src.core.catalog.install_support import InstallSupport
from src.core.catalog.metadata import GameMetadata, MetadataStore
from src.core.catalog.repository import CatalogRepository
from src.core.db.store import open_database
from src.core.launcher.game_manager import GameActionResult, GameLifecycleManager
from src.core.platform.base import ActionResult, StorageValidation
from src.core.platform.windows.adapter import WindowsPlatformAdapter


class LinuxStubAdapter:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str]]] = []

    def platform_name(self) -> str:
        return "linux"

    def normalize_path(self, raw_path: str) -> str:
        return raw_path

    def validate_storage_path(self, raw_path: str) -> StorageValidation:
        return StorageValidation(raw_path, True, True, True, True, "ok")

    def open_folder(self, raw_path: str) -> ActionResult:
        return ActionResult(True, "opened")

    def launch_executable(
        self, executable_path: str, args: list[str] | None = None
    ) -> ActionResult:
        self.calls.append((executable_path, args or []))
        return ActionResult(True, "launched")


class WindowsStubAdapter(LinuxStubAdapter):
    def platform_name(self) -> str:
        return "windows"


class GameLifecycleTests(unittest.TestCase):
    def _manager(
        self,
        base: Path,
        db_connection,
        platform_adapter,
        *,
        metadata_root: Path | None = None,
        metadata_lookup=None,
    ) -> GameLifecycleManager:
        checks = base / "checks.json"
        if not checks.exists():
            checks.write_text('{"games":{}}', encoding="utf-8")
        support = InstallSupport(str(base / "scripts"), str(checks))
        return GameLifecycleManager(
            repo=CatalogRepository(
                db_connection, metadata_root=metadata_root or (base / "metadata")
            ),
            platform_adapter=platform_adapter,
            install_support=support,
            library_path=str(base / "LAN"),
            unrar_path=str(base / "unrar.exe"),
            windows_drive_letter="D",
            windows_lan_root="LAN",
            linux_cmd_wrapper_path=str(
                base / "scripts" / "wrappers" / "linux" / "run-cmd-wrapper.sh"
            ),
            metadata_store=MetadataStore(metadata_root or (base / "metadata")),
            metadata_lookup=metadata_lookup,
        )

    def test_archive_path_probes_legacy_and_portable_extensions_case_insensitively(
        self,
    ) -> None:
        for filename in ("demo.eti", "demo.rar", "demo.tar.gz", "DEMO.RAR"):
            with self.subTest(filename=filename), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                db = open_database(str(base / "db.sqlite"))
                game_dir = base / "LAN" / "demo"
                game_dir.mkdir(parents=True)
                archive = game_dir / filename
                archive.write_bytes(b"archive")
                manager = self._manager(base, db.connection, LinuxStubAdapter())

                self.assertEqual(manager.archive_path("demo"), archive)
                db.connection.close()

    def test_archive_path_ignores_symlink_to_archive_outside_game_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            db = open_database(str(base / "db.sqlite"))
            game_dir = base / "LAN" / "demo"
            game_dir.mkdir(parents=True)
            outside_archive = base / "outside.eti"
            outside_archive.write_bytes(b"not a game source")
            (game_dir / "demo.eti").symlink_to(outside_archive)
            manager = self._manager(base, db.connection, LinuxStubAdapter())

            archive = manager.archive_path("demo")

            self.assertNotEqual(archive, outside_archive)
            self.assertFalse(archive.is_file())
            db.connection.close()

    def test_install_extracts_metadata_selected_tar_gz_and_checks_sha256(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            db = open_database(str(base / "db.sqlite"))
            with db.connection:
                db.connection.execute(
                    "INSERT INTO game_catalog(id, title_en, title_de, key, version) VALUES ('demo','Demo','Demo','K','1')"
                )
            game_dir = base / "LAN" / "demo"
            game_dir.mkdir(parents=True)
            archive = game_dir / "package.tar.gz"
            content = b"portable game data"
            with tarfile.open(archive, "w:gz") as output:
                member = tarfile.TarInfo("assets/readme.txt")
                member.size = len(content)
                output.addfile(member, io.BytesIO(content))
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            (game_dir / "metadata.json").write_text(
                json.dumps(
                    {
                        "game_id": "demo",
                        "title": "Demo",
                        "distribution": {
                            "schema_version": 1,
                            "archive": {
                                "file": "package.tar.gz",
                                "format": "tar.gz",
                                "sha256": digest,
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )
            manager = self._manager(base, db.connection, LinuxStubAdapter())

            result = manager.install("demo")

            self.assertTrue(result.ok, result.message)
            self.assertEqual(
                (game_dir / "local" / "assets" / "readme.txt").read_bytes(), content
            )
            self.assertFalse((game_dir / "local" / "metadata.json").exists())
            self.assertEqual(manager.archive_path("demo"), archive)
            db.connection.close()

    def test_ouisync_install_rejects_archive_version_file_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            db = open_database(str(base / "db.sqlite"))
            with db.connection:
                db.connection.execute(
                    "INSERT INTO game_catalog(id, title_en, title_de, key, version) "
                    "VALUES ('demo','Demo','Demo','K','2.0')"
                )
            game_dir = base / "LAN" / "demo"
            game_dir.mkdir(parents=True)
            archive = game_dir / "demo.tar.gz"
            version_data = b"1.0\n"
            with tarfile.open(archive, "w:gz") as output:
                member = tarfile.TarInfo("version.ini")
                member.size = len(version_data)
                output.addfile(member, io.BytesIO(version_data))
            archive_digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            index_metadata = GameMetadata(
                game_id="demo",
                version="2.0",
                game_provider_type="ouisync",
                archive_file="demo.tar.gz",
                archive_format="tar.gz",
                archive_sha256=archive_digest,
                archive_version_file="version.ini",
            )
            manager = self._manager(
                base,
                db.connection,
                LinuxStubAdapter(),
                metadata_lookup=lambda _game_id: index_metadata,
            )

            result = manager.install("demo")

            self.assertFalse(result.ok)
            self.assertEqual(result.message, "archive_version_mismatch")
            self.assertFalse((game_dir / "local").exists())
            db.connection.close()

    def test_install_extracts_archive_directly_from_temporary_mount(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            db = open_database(str(base / "db.sqlite"))
            with db.connection:
                db.connection.execute(
                    "INSERT INTO game_catalog(id, title_en, title_de, key, version) VALUES ('demo','Demo','Demo','K','1')"
                )
            game_dir = base / "LAN" / "demo"
            metadata_root = game_dir / ".ouisync"
            metadata_root.mkdir(parents=True)
            mounted = base / "temporary-mount" / "demo"
            mounted.mkdir(parents=True)
            archive = mounted / "release.tar.gz"
            content = b"extracted directly from the temporary mount"
            with tarfile.open(archive, "w:gz") as output:
                member = tarfile.TarInfo("game/data.bin")
                member.size = len(content)
                output.addfile(member, io.BytesIO(content))
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            (metadata_root / "metadata.json").write_text(
                json.dumps(
                    {
                        "game_id": "demo",
                        "distribution": {
                            "archive": {
                                "file": "release.tar.gz",
                                "format": "tar.gz",
                                "sha256": digest,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            manager = self._manager(base, db.connection, LinuxStubAdapter())

            result = manager.install("demo", archive_source_root=mounted)

            self.assertTrue(result.ok, result.message)
            self.assertEqual(
                (game_dir / "local" / "game" / "data.bin").read_bytes(), content
            )
            self.assertFalse((game_dir / ".ouisync" / "release.tar.gz").exists())
            db.connection.close()

    def test_ouisync_metadata_media_and_archive_are_read_in_place(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            db = open_database(str(base / "db.sqlite"))
            with db.connection:
                db.connection.execute(
                    "INSERT INTO game_catalog(id, title_en, title_de, key, version) VALUES ('demo','Demo','Demo','K','1')"
                )
            game_dir = base / "LAN" / "demo"
            source_dir = game_dir / ".ouisync"
            source_dir.mkdir(parents=True)
            cover = source_dir / "cover.webp"
            cover.write_bytes(b"cover")
            archive = source_dir / "demo.tar.gz"
            content = b"from the Ouisync source"
            with tarfile.open(archive, "w:gz") as output:
                member = tarfile.TarInfo("game/data.bin")
                member.size = len(content)
                output.addfile(member, io.BytesIO(content))
            (source_dir / "metadata.json").write_text(
                json.dumps(
                    {
                        "game_id": "demo",
                        "title": "Demo from Ouisync",
                        "runner": "native",
                        "game_start": {
                            "file": "game_start.sh",
                            "args": ["--fullscreen"],
                        },
                        "installer_tasks": [
                            {"name": "metadata-only", "args": "preserve"}
                        ],
                        "media": {"image": "cover.webp"},
                        "distribution": {
                            "schema_version": 1,
                            "archive": {"file": "demo.tar.gz", "format": "tar.gz"},
                        },
                    }
                ),
                encoding="utf-8",
            )
            manager = self._manager(base, db.connection, LinuxStubAdapter())

            metadata = manager._metadata("demo")
            result = manager.install("demo")

            self.assertIsNotNone(metadata)
            assert metadata is not None
            self.assertEqual(metadata.title, "Demo from Ouisync")
            self.assertEqual(metadata.runner, "native")
            self.assertEqual(metadata.game_start_file, "game_start.sh")
            self.assertEqual(metadata.game_start_args, ["--fullscreen"])
            self.assertEqual(metadata.installer_tasks[0]["name"], "metadata-only")
            self.assertEqual(metadata.image, "cover.webp")
            self.assertEqual(Path(metadata.source_file), source_dir / "metadata.json")
            self.assertEqual(manager.archive_path("demo"), archive)
            self.assertTrue(result.ok, result.message)
            self.assertEqual(
                (game_dir / "local" / "game" / "data.bin").read_bytes(), content
            )
            self.assertTrue(archive.is_file())
            self.assertTrue(cover.is_file())
            self.assertFalse((game_dir / "local" / "metadata.json").exists())
            db.connection.close()

    def test_game_root_metadata_json_is_used_as_portable_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            db = open_database(str(base / "db.sqlite"))
            game_dir = base / "LAN" / "demo"
            game_dir.mkdir(parents=True)
            (game_dir / "cover.jpg").write_bytes(b"cover")
            (game_dir / "metadata.json").write_text(
                json.dumps({"title": "Game root", "media": {"image": "cover.jpg"}}),
                encoding="utf-8",
            )
            manager = self._manager(base, db.connection, LinuxStubAdapter())

            metadata = manager._metadata("demo")

            self.assertIsNotNone(metadata)
            assert metadata is not None
            self.assertEqual(metadata.title, "Game root")
            self.assertEqual(metadata.image, "cover.jpg")
            self.assertEqual(Path(metadata.source_file), game_dir / "metadata.json")
            db.connection.close()

    def test_tar_gz_archive_rejects_path_traversal_and_symlink_members(self) -> None:
        for member_name, kind in (("../../outside.txt", "file"), ("link", "symlink")):
            with self.subTest(member=member_name), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                db = open_database(str(base / "db.sqlite"))
                with db.connection:
                    db.connection.execute(
                        "INSERT INTO game_catalog(id, title_en, title_de, key, version) VALUES ('demo','Demo','Demo','K','1')"
                    )
                game_dir = base / "LAN" / "demo"
                game_dir.mkdir(parents=True)
                archive = game_dir / "demo.tar.gz"
                with tarfile.open(archive, "w:gz") as output:
                    member = tarfile.TarInfo(member_name)
                    if kind == "file":
                        member.size = 4
                        output.addfile(member, io.BytesIO(b"evil"))
                    else:
                        member.type = tarfile.SYMTYPE
                        member.linkname = "../../outside.txt"
                        output.addfile(member)
                manager = self._manager(base, db.connection, LinuxStubAdapter())

                result = manager.install("demo")

                self.assertFalse(result.ok)
                self.assertEqual(result.message, "archive_member_invalid")
                self.assertFalse((base / "outside.txt").exists())
                self.assertFalse((game_dir / "local" / "link").exists())
                db.connection.close()

    def _install_tar_members(self, base: Path, members: list[tuple[str, str, bytes, int, str]]):
        db = open_database(str(base / "db.sqlite"))
        self.addCleanup(db.connection.close)
        with db.connection:
            db.connection.execute(
                "INSERT INTO game_catalog(id, title_en, title_de, key, version) VALUES ('demo','Demo','Demo','K','1')"
            )
        game_dir = base / "LAN" / "demo"
        game_dir.mkdir(parents=True)
        with tarfile.open(game_dir / "demo.tar.gz", "w:gz") as output:
            for name, kind, content, mode, linkname in members:
                member = tarfile.TarInfo(name)
                member.mode = mode
                if kind == "hardlink":
                    member.type = tarfile.LNKTYPE
                    member.linkname = linkname
                    output.addfile(member)
                else:
                    member.size = len(content)
                    output.addfile(member, io.BytesIO(content))
        manager = self._manager(base, db.connection, LinuxStubAdapter())
        return manager.install("demo"), game_dir / "local"

    def test_tar_gz_archive_materializes_hard_links_as_copies(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result, local = self._install_tar_members(
                Path(tmp),
                [
                    ("app/AppRun", "file", b"#!/bin/sh\n", 0o777, ""),
                    ("app/usr/bin/game", "hardlink", b"", 0o777, "app/AppRun"),
                ],
            )

            self.assertTrue(result.ok, result.message)
            self.assertEqual((local / "app/usr/bin/game").read_bytes(), b"#!/bin/sh\n")
            self.assertNotEqual(
                (local / "app/usr/bin/game").stat().st_ino,
                (local / "app/AppRun").stat().st_ino,
            )

    def test_tar_gz_archive_rejects_unsafe_hard_links(self) -> None:
        for linkname in ("../../outside.txt", "/etc/passwd", "app/missing", "app/later"):
            with self.subTest(linkname=linkname), tempfile.TemporaryDirectory() as tmp:
                result, local = self._install_tar_members(
                    Path(tmp),
                    [
                        ("app/AppRun", "file", b"run", 0o755, ""),
                        ("app/link", "hardlink", b"", 0o755, linkname),
                        ("app/later", "file", b"later", 0o644, ""),
                    ],
                )

                self.assertFalse(result.ok)
                self.assertEqual(result.message, "archive_member_invalid")
                self.assertFalse((local / "app" / "link").exists())

    @unittest.skipIf(os.name == "nt", "POSIX permission bits")
    def test_tar_gz_archive_keeps_only_the_executable_bit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result, local = self._install_tar_members(
                Path(tmp),
                [
                    ("AppRun", "file", b"run", 0o6777, ""),
                    ("data.cfg", "file", b"cfg", 0o666, ""),
                    ("link", "hardlink", b"", 0o6777, "AppRun"),
                ],
            )

            self.assertTrue(result.ok, result.message)
            self.assertEqual(stat.S_IMODE((local / "AppRun").stat().st_mode), 0o755)
            self.assertEqual(stat.S_IMODE((local / "data.cfg").stat().st_mode), 0o644)
            self.assertEqual(stat.S_IMODE((local / "link").stat().st_mode), 0o755)

    def test_tar_gz_archive_rejects_existing_local_symlink_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            db = open_database(str(base / "db.sqlite"))
            with db.connection:
                db.connection.execute(
                    "INSERT INTO game_catalog(id, title_en, title_de, key, version) VALUES ('demo','Demo','Demo','K','1')"
                )
            game_dir = base / "LAN" / "demo"
            game_dir.mkdir(parents=True)
            archive = game_dir / "demo.tar.gz"
            with tarfile.open(archive, "w:gz") as output:
                member = tarfile.TarInfo("content.txt")
                member.size = 4
                output.addfile(member, io.BytesIO(b"safe"))
            outside = base / "outside"
            outside.mkdir()
            (game_dir / "local").symlink_to(outside, target_is_directory=True)
            manager = self._manager(base, db.connection, LinuxStubAdapter())

            result = manager.install("demo")

            self.assertFalse(result.ok)
            self.assertEqual(result.message, "archive_target_invalid")
            self.assertEqual(list(outside.iterdir()), [])
            db.connection.close()

    def test_archive_checksum_mismatch_stops_before_extracting(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            db = open_database(str(base / "db.sqlite"))
            with db.connection:
                db.connection.execute(
                    "INSERT INTO game_catalog(id, title_en, title_de, key, version) VALUES ('demo','Demo','Demo','K','1')"
                )
            game_dir = base / "LAN" / "demo"
            game_dir.mkdir(parents=True)
            archive = game_dir / "demo.tar.gz"
            archive.write_bytes(b"not the signed archive")
            (game_dir / "metadata.json").write_text(
                json.dumps(
                    {
                        "title": "Demo",
                        "distribution": {
                            "archive": {"file": "demo.tar.gz", "sha256": "0" * 64}
                        },
                    }
                ),
                encoding="utf-8",
            )
            manager = self._manager(base, db.connection, LinuxStubAdapter())

            result = manager.install("demo")

            self.assertFalse(result.ok)
            self.assertEqual(result.message, "archive_checksum_mismatch")
            self.assertFalse((game_dir / "local").exists())
            db.connection.close()

    def test_status_and_update_detection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            db = open_database(str(base / "db.sqlite"))
            with db.connection:
                db.connection.execute(
                    "INSERT INTO game_catalog(id, title_en, title_de, key, version) VALUES ('blobby','Blobby','Blobby','K','20250101')"
                )

            checks = base / "checks.json"
            checks.write_text(
                '{"games":{"blobby":{"markers":["local/done.txt"]}}}', encoding="utf-8"
            )

            game_dir = base / "LAN" / "blobby"
            (game_dir / "local").mkdir(parents=True, exist_ok=True)
            (game_dir / "local" / "done.txt").write_text("ok", encoding="utf-8")
            (game_dir / "version.ini").write_text(
                "[version]\nlocal=20240101\n", encoding="utf-8"
            )

            support = InstallSupport(str(base / "scripts"), str(checks))
            manager = GameLifecycleManager(
                repo=CatalogRepository(db.connection),
                platform_adapter=WindowsPlatformAdapter(),
                install_support=support,
                library_path=str(base / "LAN"),
                unrar_path=str(base / "unrar.exe"),
                windows_drive_letter="D",
                windows_lan_root="LAN",
                linux_cmd_wrapper_path=str(
                    base / "scripts" / "wrappers" / "linux" / "run-cmd-wrapper.sh"
                ),
            )

            status = manager.check_status("blobby")
            self.assertTrue(status.ok)
            self.assertTrue(status.details["needs_update"])
            db.connection.close()

    def test_install_uses_unrar(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            db = open_database(str(base / "db.sqlite"))
            with db.connection:
                db.connection.execute(
                    "INSERT INTO game_catalog(id, title_en, title_de, key, version) VALUES ('blobby','Blobby','Blobby','K','1')"
                )

            checks = base / "checks.json"
            checks.write_text('{"games":{}}', encoding="utf-8")
            support = InstallSupport(str(base / "scripts"), str(checks))

            game_dir = base / "LAN" / "blobby"
            game_dir.mkdir(parents=True, exist_ok=True)
            (game_dir / "blobby.rar").write_bytes(b"rar")
            (game_dir / "local").mkdir(parents=True, exist_ok=True)

            unrar = base / "unrar.exe"
            unrar.write_text("stub", encoding="utf-8")

            manager = GameLifecycleManager(
                repo=CatalogRepository(db.connection),
                platform_adapter=WindowsPlatformAdapter(),
                install_support=support,
                library_path=str(base / "LAN"),
                unrar_path=str(unrar),
                windows_drive_letter="D",
                windows_lan_root="LAN",
                linux_cmd_wrapper_path=str(
                    base / "scripts" / "wrappers" / "linux" / "run-cmd-wrapper.sh"
                ),
            )

            with patch("src.core.launcher.game_manager.subprocess.Popen") as mocked:
                process = mocked.return_value
                process.stdout = ["ok\n"]
                process.wait.return_value = 0
                result = manager.install("blobby")

            self.assertTrue(result.ok)
            self.assertEqual(result.message, "installed")
            self.assertTrue(mocked.called)
            cmd = mocked.call_args.args[0]
            self.assertIn("-ol-", cmd)
            self.assertIn(str(game_dir / "blobby.rar"), cmd)
            self.assertEqual(Path(cmd[-1]), game_dir / "local")
            self.assertEqual(
                (game_dir / "version.ini").read_text(encoding="utf-8").strip(), "1"
            )
            db.connection.close()

    def test_windows_install_hides_unrar_console_and_streams_progress(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            db = open_database(str(base / "db.sqlite"))
            with db.connection:
                db.connection.execute(
                    "INSERT INTO game_catalog(id, title_en, title_de, key, version) VALUES ('blobby','Blobby','Blobby','K','1')"
                )

            checks = base / "checks.json"
            checks.write_text('{"games":{}}', encoding="utf-8")
            support = InstallSupport(str(base / "scripts"), str(checks))

            game_dir = base / "LAN" / "blobby"
            game_dir.mkdir(parents=True, exist_ok=True)
            (game_dir / "blobby.eti").write_bytes(b"rar")
            (game_dir / "local").mkdir(parents=True, exist_ok=True)

            unrar = base / "unrar.exe"
            unrar.write_text("stub", encoding="utf-8")

            manager = GameLifecycleManager(
                repo=CatalogRepository(db.connection),
                platform_adapter=WindowsPlatformAdapter(),
                install_support=support,
                library_path=str(base / "LAN"),
                unrar_path=str(unrar),
                windows_drive_letter="D",
                windows_lan_root="LAN",
                linux_cmd_wrapper_path=str(
                    base / "scripts" / "wrappers" / "linux" / "run-cmd-wrapper.sh"
                ),
            )
            lines: list[str] = []

            with patch("src.core.launcher.game_manager.subprocess.Popen") as mocked:
                process = mocked.return_value
                process.stdout.read.side_effect = [
                    "Extracting 10%\r",
                    "Extracting 100%\n",
                    "",
                ]
                process.wait.return_value = 0
                result = manager.install(
                    "blobby", output_callback=lambda line: lines.append(line)
                )

            self.assertTrue(result.ok)
            self.assertTrue(
                any("Extracting 10%" in line for line in lines),
                lines,
            )
            self.assertTrue(
                any("Extracting 100%" in line for line in lines),
                lines,
            )
            self.assertIn("creationflags", mocked.call_args.kwargs)
            if hasattr(subprocess, "STARTUPINFO"):
                self.assertIn("startupinfo", mocked.call_args.kwargs)
            db.connection.close()

    def test_install_serializes_archive_extraction(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            db = open_database(str(base / "db.sqlite"))
            with db.connection:
                db.connection.executemany(
                    "INSERT INTO game_catalog(id, title_en, title_de, key, version) VALUES (?, ?, ?, 'K', '1')",
                    [
                        ("g1", "G1", "G1"),
                        ("g2", "G2", "G2"),
                    ],
                )

            checks = base / "checks.json"
            checks.write_text('{"games":{}}', encoding="utf-8")
            support = InstallSupport(str(base / "scripts"), str(checks))
            for game_id in ("g1", "g2"):
                game_dir = base / "LAN" / game_id
                game_dir.mkdir(parents=True, exist_ok=True)
                (game_dir / f"{game_id}.eti").write_bytes(b"rar")
                (game_dir / "local").mkdir(parents=True, exist_ok=True)

            unrar = base / "unrar.exe"
            unrar.write_text("stub", encoding="utf-8")

            manager = GameLifecycleManager(
                repo=CatalogRepository(db.connection),
                platform_adapter=WindowsPlatformAdapter(),
                install_support=support,
                library_path=str(base / "LAN"),
                unrar_path=str(unrar),
                windows_drive_letter="D",
                windows_lan_root="LAN",
                linux_cmd_wrapper_path=str(
                    base / "scripts" / "wrappers" / "linux" / "run-cmd-wrapper.sh"
                ),
            )

            started = threading.Event()
            release = threading.Event()
            start_order: list[str] = []
            wait_lines: list[str] = []

            class _Stdout:
                def __init__(self, game_id: str) -> None:
                    self._game_id = game_id
                    self._done = False

                def read(self, _size: int) -> str:
                    if self._done:
                        return ""
                    self._done = True
                    started.set()
                    release.wait(timeout=2.0)
                    return f"{self._game_id} done\n"

            def _install(game_id: str) -> None:
                manager.install(
                    game_id,
                    output_callback=lambda line, gid=game_id: wait_lines.append(
                        f"{gid}:{line}"
                    ),
                )

            with patch("src.core.launcher.game_manager.subprocess.Popen") as mocked:

                def _make_process(*args, **kwargs):
                    archive_arg = next(
                        part
                        for part in args[0]
                        if str(part).lower().endswith((".eti", ".rar", ".tar.gz"))
                    )
                    game_id = Path(archive_arg).name.split(".", 1)[0]
                    start_order.append(game_id)
                    proc = type("Proc", (), {})()
                    proc.stdout = _Stdout(game_id)
                    proc.wait = lambda: 0
                    return proc

                mocked.side_effect = _make_process
                thread_1 = threading.Thread(target=_install, args=("g1",))
                thread_2 = threading.Thread(target=_install, args=("g2",))
                thread_1.start()
                started.wait(timeout=2.0)
                thread_2.start()
                time.sleep(0.1)
                self.assertEqual(start_order, ["g1"])
                self.assertTrue(
                    any(
                        "g2:another archive extraction is active" in line
                        for line in wait_lines
                    ),
                    wait_lines,
                )
                release.set()
                thread_1.join(timeout=2.0)
                thread_2.join(timeout=2.0)

            self.assertEqual(start_order, ["g1", "g2"])
            db.connection.close()

    def test_linux_uses_wrapper_when_only_cmd_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            db = open_database(str(base / "db.sqlite"))
            with db.connection:
                db.connection.execute(
                    "INSERT INTO game_catalog(id, title_en, title_de, key, version) VALUES ('blobby','Blobby','Blobby','K','1')"
                )

            checks = base / "checks.json"
            checks.write_text('{"games":{}}', encoding="utf-8")
            support = InstallSupport(str(base / "scripts"), str(checks))
            platform = LinuxStubAdapter()

            game_dir = base / "LAN" / "blobby"
            game_dir.mkdir(parents=True, exist_ok=True)
            (game_dir / "game_start.cmd").write_text("@echo off", encoding="utf-8")
            (game_dir / "local").mkdir(parents=True, exist_ok=True)

            wrapper = base / "scripts" / "wrappers" / "linux" / "run-cmd-wrapper.sh"
            wrapper.parent.mkdir(parents=True, exist_ok=True)
            wrapper.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")

            manager = GameLifecycleManager(
                repo=CatalogRepository(db.connection),
                platform_adapter=platform,
                install_support=support,
                library_path=str(base / "LAN"),
                unrar_path=str(base / "unrar.exe"),
                windows_drive_letter="D",
                windows_lan_root="LAN",
                linux_cmd_wrapper_path=str(wrapper),
            )

            with patch(
                "src.core.launcher.game_manager.shutil.which",
                side_effect=lambda name: "/usr/bin/wine" if name == "wine" else None,
            ):
                result = manager.start_game("blobby", server=False)
            self.assertTrue(result.ok)
            self.assertEqual(result.message, "launched")
            self.assertEqual(result.details.get("launch_method"), "linux_cmd_wrapper")
            self.assertEqual(result.details.get("runtime"), "wine")
            self.assertIn(
                "--runtime wine", result.details.get("launch_command_display", "")
            )
            self.assertEqual(len(platform.calls), 1)
            launched, args = platform.calls[0]
            self.assertEqual(Path(launched), wrapper)
            self.assertEqual(
                args,
                [
                    "--runtime",
                    "wine",
                    "--runtime-binary",
                    "/usr/bin/wine",
                    "--compat-data-path",
                    str(game_dir / ".compatdata" / "wine"),
                    str(game_dir / "game_start.cmd"),
                    str(game_dir),
                    "blobby",
                    "en",
                    "",
                ],
            )
            db.connection.close()

    def test_linux_runtime_unavailable_when_cmd_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            db = open_database(str(base / "db.sqlite"))
            with db.connection:
                db.connection.execute(
                    "INSERT INTO game_catalog(id, title_en, title_de, key, version) VALUES ('blobby','Blobby','Blobby','K','1')"
                )

            checks = base / "checks.json"
            checks.write_text('{"games":{}}', encoding="utf-8")
            support = InstallSupport(str(base / "scripts"), str(checks))
            platform = LinuxStubAdapter()

            game_dir = base / "LAN" / "blobby"
            game_dir.mkdir(parents=True, exist_ok=True)
            (game_dir / "game_start.cmd").write_text("@echo off", encoding="utf-8")
            (game_dir / "local").mkdir(parents=True, exist_ok=True)

            wrapper = base / "scripts" / "wrappers" / "linux" / "run-cmd-wrapper.sh"
            wrapper.parent.mkdir(parents=True, exist_ok=True)
            wrapper.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")

            manager = GameLifecycleManager(
                repo=CatalogRepository(db.connection),
                platform_adapter=platform,
                install_support=support,
                library_path=str(base / "LAN"),
                unrar_path=str(base / "unrar.exe"),
                windows_drive_letter="D",
                windows_lan_root="LAN",
                linux_cmd_wrapper_path=str(wrapper),
            )
            manager.set_linux_runtime_settings("proton-ge", "", "")

            with patch(
                "src.core.launcher.game_manager.shutil.which", return_value=None
            ):
                result = manager.start_game("blobby", server=False)

            self.assertFalse(result.ok)
            self.assertEqual(result.message, "linux_windows_runtime_unavailable")
            self.assertEqual(len(platform.calls), 0)
            db.connection.close()

    def test_linux_uses_proton_wrapper_with_compat_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            db = open_database(str(base / "db.sqlite"))
            with db.connection:
                db.connection.execute(
                    "INSERT INTO game_catalog(id, title_en, title_de, key, version) VALUES ('blobby','Blobby','Blobby','K','1')"
                )

            checks = base / "checks.json"
            checks.write_text('{"games":{}}', encoding="utf-8")
            support = InstallSupport(str(base / "scripts"), str(checks))
            platform = LinuxStubAdapter()

            game_dir = base / "LAN" / "blobby"
            game_dir.mkdir(parents=True, exist_ok=True)
            (game_dir / "game_start.cmd").write_text("@echo off", encoding="utf-8")
            (game_dir / "local").mkdir(parents=True, exist_ok=True)

            wrapper = base / "scripts" / "wrappers" / "linux" / "run-cmd-wrapper.sh"
            wrapper.parent.mkdir(parents=True, exist_ok=True)
            wrapper.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")

            proton = base / "vendor" / "proton" / "proton"
            proton.parent.mkdir(parents=True, exist_ok=True)
            proton.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")

            manager = GameLifecycleManager(
                repo=CatalogRepository(db.connection),
                platform_adapter=platform,
                install_support=support,
                library_path=str(base / "LAN"),
                unrar_path=str(base / "unrar.exe"),
                windows_drive_letter="D",
                windows_lan_root="LAN",
                linux_cmd_wrapper_path=str(wrapper),
            )
            manager.set_linux_runtime_settings("proton", str(proton), "")

            result = manager.start_game("blobby", server=False)

            self.assertTrue(result.ok)
            self.assertEqual(len(platform.calls), 1)
            launched, args = platform.calls[0]
            self.assertEqual(Path(launched), wrapper)
            self.assertEqual(
                args[0:4], ["--runtime", "proton", "--runtime-binary", str(proton)]
            )
            self.assertEqual(
                args[4:6],
                ["--compat-data-path", str(game_dir / ".compatdata" / "proton")],
            )
            self.assertEqual(args[6], str(game_dir / "game_start.cmd"))
            db.connection.close()

    def test_install_runs_optional_game_setup_cmd(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            db = open_database(str(base / "db.sqlite"))
            with db.connection:
                db.connection.execute(
                    "INSERT INTO game_catalog(id, title_en, title_de, key, version) VALUES ('blobby','Blobby','Blobby','K','1')"
                )

            checks = base / "checks.json"
            checks.write_text('{"games":{}}', encoding="utf-8")
            support = InstallSupport(str(base / "scripts"), str(checks))
            platform = WindowsStubAdapter()

            game_dir = base / "LAN" / "blobby"
            game_dir.mkdir(parents=True, exist_ok=True)
            (game_dir / "blobby.eti").write_bytes(b"rar")
            (game_dir / "local").mkdir(parents=True, exist_ok=True)
            (game_dir / "game_setup.cmd").write_text("@echo off", encoding="utf-8")

            unrar = base / "unrar.exe"
            unrar.write_text("stub", encoding="utf-8")

            manager = GameLifecycleManager(
                repo=CatalogRepository(db.connection),
                platform_adapter=platform,
                install_support=support,
                library_path=str(base / "LAN"),
                unrar_path=str(unrar),
                windows_drive_letter="D",
                windows_lan_root="LAN",
                linux_cmd_wrapper_path=str(
                    base / "scripts" / "wrappers" / "linux" / "run-cmd-wrapper.sh"
                ),
            )

            with (
                patch(
                    "src.core.launcher.game_manager.subprocess.Popen"
                ) as mocked_popen,
                patch("src.core.launcher.game_manager.subprocess.run") as mocked_run,
            ):
                process = mocked_popen.return_value
                process.stdout = ["ok\n"]
                process.wait.return_value = 0
                mocked_run.return_value.returncode = 0
                result = manager.install("blobby")

            self.assertTrue(result.ok)
            self.assertEqual(len(platform.calls), 0)
            self.assertTrue(mocked_popen.called)
            self.assertTrue(mocked_run.called)
            run_args, run_kwargs = mocked_run.call_args
            self.assertEqual(run_args[0][:2], ["cmd.exe", "/c"])
            self.assertEqual(Path(run_args[0][2]), game_dir / "game_setup.cmd")
            self.assertEqual(Path(run_kwargs["cwd"]), game_dir)
            self.assertIn("creationflags", run_kwargs)
            db.connection.close()

    def test_install_fails_when_game_setup_returns_nonzero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            db = open_database(str(base / "db.sqlite"))
            with db.connection:
                db.connection.execute(
                    "INSERT INTO game_catalog(id, title_en, title_de, key, version) VALUES ('blobby','Blobby','Blobby','K','1')"
                )

            checks = base / "checks.json"
            checks.write_text('{"games":{}}', encoding="utf-8")
            support = InstallSupport(str(base / "scripts"), str(checks))
            platform = WindowsStubAdapter()

            game_dir = base / "LAN" / "blobby"
            game_dir.mkdir(parents=True, exist_ok=True)
            (game_dir / "blobby.eti").write_bytes(b"rar")
            (game_dir / "local").mkdir(parents=True, exist_ok=True)
            (game_dir / "game_setup.cmd").write_text("@echo off", encoding="utf-8")

            unrar = base / "unrar.exe"
            unrar.write_text("stub", encoding="utf-8")

            manager = GameLifecycleManager(
                repo=CatalogRepository(db.connection),
                platform_adapter=platform,
                install_support=support,
                library_path=str(base / "LAN"),
                unrar_path=str(unrar),
                windows_drive_letter="D",
                windows_lan_root="LAN",
                linux_cmd_wrapper_path=str(
                    base / "scripts" / "wrappers" / "linux" / "run-cmd-wrapper.sh"
                ),
            )

            with (
                patch(
                    "src.core.launcher.game_manager.subprocess.Popen"
                ) as mocked_popen,
                patch("src.core.launcher.game_manager.subprocess.run") as mocked_run,
            ):
                process = mocked_popen.return_value
                process.stdout = ["ok\n"]
                process.wait.return_value = 0
                mocked_run.return_value.returncode = 2
                result = manager.install("blobby")

            self.assertFalse(result.ok)
            self.assertEqual(result.message, "game_setup_failed")
            self.assertEqual(len(platform.calls), 0)
            self.assertTrue(mocked_run.called)
            db.connection.close()

    def test_linux_install_uses_system_unrar_and_runs_game_setup_sh(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            db = open_database(str(base / "db.sqlite"))
            with db.connection:
                db.connection.execute(
                    "INSERT INTO game_catalog(id, title_en, title_de, key, version) VALUES ('blobby','Blobby','Blobby','K','1')"
                )

            checks = base / "checks.json"
            checks.write_text('{"games":{}}', encoding="utf-8")
            support = InstallSupport(str(base / "scripts"), str(checks))
            platform = LinuxStubAdapter()

            game_dir = base / "LAN" / "blobby"
            game_dir.mkdir(parents=True, exist_ok=True)
            (game_dir / "blobby.eti").write_bytes(b"rar")
            (game_dir / "local").mkdir(parents=True, exist_ok=True)
            (game_dir / "game_setup.sh").write_text(
                "#!/usr/bin/env bash\nexit 0\n", encoding="utf-8"
            )

            manager = GameLifecycleManager(
                repo=CatalogRepository(db.connection),
                platform_adapter=platform,
                install_support=support,
                library_path=str(base / "LAN"),
                unrar_path=str(base / "unrar.exe"),
                windows_drive_letter="D",
                windows_lan_root="LAN",
                linux_cmd_wrapper_path=str(
                    base / "scripts" / "wrappers" / "linux" / "run-cmd-wrapper.sh"
                ),
            )

            with (
                patch(
                    "src.core.launcher.game_manager.shutil.which",
                    return_value="/usr/bin/unrar",
                ),
                patch(
                    "src.core.launcher.game_manager.subprocess.Popen"
                ) as mocked_popen,
                patch("src.core.launcher.game_manager.subprocess.run") as mocked_run,
            ):
                process = mocked_popen.return_value
                process.stdout = ["ok\n"]
                process.wait.return_value = 0
                mocked_run.return_value.returncode = 0
                result = manager.install("blobby")

            self.assertTrue(result.ok)
            popen_cmd = mocked_popen.call_args.args[0]
            self.assertEqual(popen_cmd[0], "/usr/bin/unrar")
            run_args, run_kwargs = mocked_run.call_args
            self.assertEqual(run_args[0][0], "bash")
            self.assertEqual(Path(run_args[0][1]), game_dir / "game_setup.sh")
            self.assertEqual(Path(run_kwargs["cwd"]), game_dir)
            db.connection.close()

    def test_linux_install_fails_when_system_unrar_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            db = open_database(str(base / "db.sqlite"))
            with db.connection:
                db.connection.execute(
                    "INSERT INTO game_catalog(id, title_en, title_de, key, version) VALUES ('blobby','Blobby','Blobby','K','1')"
                )

            checks = base / "checks.json"
            checks.write_text('{"games":{}}', encoding="utf-8")
            support = InstallSupport(str(base / "scripts"), str(checks))
            platform = LinuxStubAdapter()

            game_dir = base / "LAN" / "blobby"
            game_dir.mkdir(parents=True, exist_ok=True)
            (game_dir / "blobby.eti").write_bytes(b"rar")

            manager = GameLifecycleManager(
                repo=CatalogRepository(db.connection),
                platform_adapter=platform,
                install_support=support,
                library_path=str(base / "LAN"),
                unrar_path=str(base / "unrar.exe"),
                windows_drive_letter="D",
                windows_lan_root="LAN",
                linux_cmd_wrapper_path=str(
                    base / "scripts" / "wrappers" / "linux" / "run-cmd-wrapper.sh"
                ),
            )

            with patch(
                "src.core.launcher.game_manager.shutil.which", return_value=None
            ):
                result = manager.install("blobby")

            self.assertFalse(result.ok)
            self.assertEqual(result.message, "unrar_missing")
            db.connection.close()

    def test_windows_start_passes_expected_cmd_arguments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            db = open_database(str(base / "db.sqlite"))
            with db.connection:
                db.connection.execute(
                    "INSERT INTO game_catalog(id, title_en, title_de, key, version) VALUES ('blobby','Blobby','Blobby','K','1')"
                )

            checks = base / "checks.json"
            checks.write_text('{"games":{}}', encoding="utf-8")
            support = InstallSupport(str(base / "scripts"), str(checks))
            platform = WindowsStubAdapter()

            game_dir = base / "LAN" / "blobby"
            game_dir.mkdir(parents=True, exist_ok=True)
            (game_dir / "game_start.cmd").write_text("@echo off", encoding="utf-8")
            (game_dir / "local").mkdir(parents=True, exist_ok=True)

            manager = GameLifecycleManager(
                repo=CatalogRepository(db.connection),
                platform_adapter=platform,
                install_support=support,
                library_path=str(base / "LAN"),
                unrar_path=str(base / "unrar.exe"),
                windows_drive_letter="D",
                windows_lan_root="LAN",
                linux_cmd_wrapper_path=str(
                    base / "scripts" / "wrappers" / "linux" / "run-cmd-wrapper.sh"
                ),
            )

            result = manager.start_game(
                "blobby", server=False, game_lang="de", player="Chris"
            )
            self.assertTrue(result.ok)
            self.assertEqual(result.details.get("launch_method"), "windows_cmd")
            self.assertEqual(result.details.get("runtime"), "native")
            self.assertIn(
                "game_start.cmd", result.details.get("launch_command_display", "")
            )
            self.assertEqual(len(platform.calls), 1)
            launched, args = platform.calls[0]
            self.assertEqual(Path(launched), game_dir / "game_start.cmd")
            self.assertEqual(args, [str(game_dir), "blobby", "de", "Chris"])
            db.connection.close()

    def test_linux_start_uses_runtime_override_when_provided(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            db = open_database(str(base / "db.sqlite"))
            with db.connection:
                db.connection.execute(
                    "INSERT INTO game_catalog(id, title_en, title_de, key, version) VALUES ('blobby','Blobby','Blobby','K','1')"
                )

            checks = base / "checks.json"
            checks.write_text('{"games":{}}', encoding="utf-8")
            support = InstallSupport(str(base / "scripts"), str(checks))
            platform = LinuxStubAdapter()

            game_dir = base / "LAN" / "blobby"
            game_dir.mkdir(parents=True, exist_ok=True)
            (game_dir / "game_start.cmd").write_text("@echo off", encoding="utf-8")
            (game_dir / "local").mkdir(parents=True, exist_ok=True)

            wrapper = base / "scripts" / "wrappers" / "linux" / "run-cmd-wrapper.sh"
            wrapper.parent.mkdir(parents=True, exist_ok=True)
            wrapper.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")

            proton = base / "vendor" / "proton" / "proton"
            proton.parent.mkdir(parents=True, exist_ok=True)
            proton.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")

            manager = GameLifecycleManager(
                repo=CatalogRepository(db.connection),
                platform_adapter=platform,
                install_support=support,
                library_path=str(base / "LAN"),
                unrar_path=str(base / "unrar.exe"),
                windows_drive_letter="D",
                windows_lan_root="LAN",
                linux_cmd_wrapper_path=str(wrapper),
            )
            manager.set_linux_runtime_settings("proton", str(proton), "")

            with patch(
                "src.core.launcher.game_manager.shutil.which",
                side_effect=lambda name: "/usr/bin/wine" if name == "wine" else None,
            ):
                result = manager.start_game(
                    "blobby",
                    server=False,
                    linux_runtime_override="wine",
                )

            self.assertTrue(result.ok)
            self.assertEqual(result.details.get("runtime"), "wine")
            self.assertEqual(len(platform.calls), 1)
            _launched, args = platform.calls[0]
            self.assertEqual(
                args[0:4], ["--runtime", "wine", "--runtime-binary", "/usr/bin/wine"]
            )
            self.assertIn(
                "--compat-data-path",
                args,
            )
            self.assertIn(
                str(game_dir / ".compatdata" / "wine"),
                args,
            )
            db.connection.close()

    def test_linux_start_passes_hold_open_flag_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            db = open_database(str(base / "db.sqlite"))
            with db.connection:
                db.connection.execute(
                    "INSERT INTO game_catalog(id, title_en, title_de, key, version) VALUES ('blobby','Blobby','Blobby','K','1')"
                )

            checks = base / "checks.json"
            checks.write_text('{"games":{}}', encoding="utf-8")
            support = InstallSupport(str(base / "scripts"), str(checks))
            platform = LinuxStubAdapter()

            game_dir = base / "LAN" / "blobby"
            game_dir.mkdir(parents=True, exist_ok=True)
            (game_dir / "game_start.cmd").write_text("@echo off", encoding="utf-8")
            (game_dir / "local").mkdir(parents=True, exist_ok=True)

            wrapper = base / "scripts" / "wrappers" / "linux" / "run-cmd-wrapper.sh"
            wrapper.parent.mkdir(parents=True, exist_ok=True)
            wrapper.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")

            manager = GameLifecycleManager(
                repo=CatalogRepository(db.connection),
                platform_adapter=platform,
                install_support=support,
                library_path=str(base / "LAN"),
                unrar_path=str(base / "unrar.exe"),
                windows_drive_letter="D",
                windows_lan_root="LAN",
                linux_cmd_wrapper_path=str(wrapper),
            )
            manager.set_linux_runtime_settings("wine", "", "")

            with patch(
                "src.core.launcher.game_manager.shutil.which",
                side_effect=lambda name: "/usr/bin/wine" if name == "wine" else None,
            ):
                result = manager.start_game(
                    "blobby",
                    server=False,
                    linux_leave_terminal_open=True,
                )

            self.assertTrue(result.ok)
            self.assertEqual(len(platform.calls), 1)
            _launched, args = platform.calls[0]
            self.assertIn("--hold-open", args)
            self.assertTrue(result.details.get("leave_terminal_open"))
            db.connection.close()

    def test_start_game_recovers_missing_local_by_running_install(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            db = open_database(str(base / "db.sqlite"))
            with db.connection:
                db.connection.execute(
                    "INSERT INTO game_catalog(id, title_en, title_de, key, version) VALUES ('blobby','Blobby','Blobby','K','1')"
                )

            checks = base / "checks.json"
            checks.write_text('{"games":{}}', encoding="utf-8")
            support = InstallSupport(str(base / "scripts"), str(checks))
            platform = WindowsStubAdapter()

            game_dir = base / "LAN" / "blobby"
            game_dir.mkdir(parents=True, exist_ok=True)
            (game_dir / "game_start.cmd").write_text("@echo off", encoding="utf-8")
            (game_dir / "blobby.eti").write_bytes(b"rar")
            # No local folder -> start should run install recovery first.

            manager = GameLifecycleManager(
                repo=CatalogRepository(db.connection),
                platform_adapter=platform,
                install_support=support,
                library_path=str(base / "LAN"),
                unrar_path=str(base / "unrar.exe"),
                windows_drive_letter="D",
                windows_lan_root="LAN",
                linux_cmd_wrapper_path=str(
                    base / "scripts" / "wrappers" / "linux" / "run-cmd-wrapper.sh"
                ),
            )

            with patch.object(
                manager,
                "install",
                return_value=GameActionResult(
                    True, "install", "blobby", "installed", {}
                ),
            ) as mocked_install:
                result = manager.start_game("blobby", server=False)

            self.assertTrue(result.ok)
            self.assertTrue(mocked_install.called)
            self.assertEqual(len(platform.calls), 1)
            db.connection.close()

    def test_start_game_fails_when_recovery_install_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            db = open_database(str(base / "db.sqlite"))
            with db.connection:
                db.connection.execute(
                    "INSERT INTO game_catalog(id, title_en, title_de, key, version) VALUES ('blobby','Blobby','Blobby','K','1')"
                )

            checks = base / "checks.json"
            checks.write_text('{"games":{}}', encoding="utf-8")
            support = InstallSupport(str(base / "scripts"), str(checks))
            platform = WindowsStubAdapter()

            game_dir = base / "LAN" / "blobby"
            game_dir.mkdir(parents=True, exist_ok=True)
            (game_dir / "game_start.cmd").write_text("@echo off", encoding="utf-8")
            (game_dir / "blobby.eti").write_bytes(b"rar")
            # No local folder -> recovery attempted and failed.

            manager = GameLifecycleManager(
                repo=CatalogRepository(db.connection),
                platform_adapter=platform,
                install_support=support,
                library_path=str(base / "LAN"),
                unrar_path=str(base / "unrar.exe"),
                windows_drive_letter="D",
                windows_lan_root="LAN",
                linux_cmd_wrapper_path=str(
                    base / "scripts" / "wrappers" / "linux" / "run-cmd-wrapper.sh"
                ),
            )

            with patch.object(
                manager,
                "install",
                return_value=GameActionResult(
                    False,
                    "install",
                    "blobby",
                    "unrar_failed",
                    {"code": 2},
                ),
            ) as mocked_install:
                result = manager.start_game("blobby", server=False)

            self.assertFalse(result.ok)
            self.assertEqual(result.message, "start_install_recovery_failed")
            self.assertTrue(mocked_install.called)
            self.assertEqual(len(platform.calls), 0)
            db.connection.close()

    def test_status_supports_plain_text_version_ini(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            db = open_database(str(base / "db.sqlite"))
            with db.connection:
                db.connection.execute(
                    "INSERT INTO game_catalog(id, title_en, title_de, key, version) VALUES ('blobby','Blobby','Blobby','K','20250101')"
                )

            checks = base / "checks.json"
            checks.write_text('{"games":{}}', encoding="utf-8")
            support = InstallSupport(str(base / "scripts"), str(checks))
            game_dir = base / "LAN" / "blobby"
            game_dir.mkdir(parents=True, exist_ok=True)
            (game_dir / "version.ini").write_text("20161024\n", encoding="utf-8")

            manager = GameLifecycleManager(
                repo=CatalogRepository(db.connection),
                platform_adapter=WindowsPlatformAdapter(),
                install_support=support,
                library_path=str(base / "LAN"),
                unrar_path=str(base / "unrar.exe"),
                windows_drive_letter="D",
                windows_lan_root="LAN",
                linux_cmd_wrapper_path=str(
                    base / "scripts" / "wrappers" / "linux" / "run-cmd-wrapper.sh"
                ),
            )
            status = manager.check_status("blobby")
            self.assertEqual(status.details["installed_version"], "20161024")
            self.assertTrue(status.details["needs_update"])
            db.connection.close()

    def test_windows_start_uses_metadata_game_start_and_args(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            db = open_database(str(base / "db.sqlite"))
            with db.connection:
                db.connection.execute(
                    "INSERT INTO game_catalog(id, title_en, title_de, key, version) VALUES ('blobby','Blobby','Blobby','K','1')"
                )
            metadata_root = base / "metadata"
            metadata_root.mkdir(parents=True, exist_ok=True)
            (metadata_root / "blobby.json").write_text(
                json.dumps(
                    {
                        "game_start": {
                            "file": "custom/game_start_custom.cmd",
                            "args": ["--windowed", "$GAMEDIR/local"],
                        }
                    }
                ),
                encoding="utf-8",
            )

            platform = WindowsStubAdapter()
            manager = self._manager(
                base,
                db.connection,
                platform,
                metadata_root=metadata_root,
            )
            game_dir = base / "LAN" / "blobby"
            (game_dir / "local").mkdir(parents=True, exist_ok=True)
            custom = game_dir / "custom" / "game_start_custom.cmd"
            custom.parent.mkdir(parents=True, exist_ok=True)
            custom.write_text("@echo off", encoding="utf-8")

            result = manager.start_game(
                "blobby", server=False, game_lang="de", player="Chris"
            )
            self.assertTrue(result.ok)
            self.assertEqual(result.details.get("launch_method"), "windows_cmd")
            self.assertEqual(len(platform.calls), 1)
            launched, args = platform.calls[0]
            self.assertEqual(Path(launched), custom)
            self.assertEqual(
                args,
                [
                    str(game_dir),
                    "blobby",
                    "de",
                    "Chris",
                    "--windowed",
                    f"{game_dir}/local",
                ],
            )
            db.connection.close()

    def test_linux_start_uses_metadata_runner_as_runtime_hint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            db = open_database(str(base / "db.sqlite"))
            with db.connection:
                db.connection.execute(
                    "INSERT INTO game_catalog(id, title_en, title_de, key, version) VALUES ('blobby','Blobby','Blobby','K','1')"
                )
            metadata_root = base / "metadata"
            metadata_root.mkdir(parents=True, exist_ok=True)
            (metadata_root / "blobby.json").write_text(
                json.dumps({"runner": "proton"}), encoding="utf-8"
            )
            platform = LinuxStubAdapter()
            manager = self._manager(
                base,
                db.connection,
                platform,
                metadata_root=metadata_root,
            )

            game_dir = base / "LAN" / "blobby"
            game_dir.mkdir(parents=True, exist_ok=True)
            (game_dir / "game_start.cmd").write_text("@echo off", encoding="utf-8")
            (game_dir / "local").mkdir(parents=True, exist_ok=True)

            wrapper = base / "scripts" / "wrappers" / "linux" / "run-cmd-wrapper.sh"
            wrapper.parent.mkdir(parents=True, exist_ok=True)
            wrapper.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            proton = base / "vendor" / "proton" / "proton"
            proton.parent.mkdir(parents=True, exist_ok=True)
            proton.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            manager.set_linux_runtime_settings("wine", str(proton), "")

            with patch(
                "src.core.launcher.game_manager.shutil.which",
                side_effect=lambda name: "/usr/bin/wine" if name == "wine" else None,
            ):
                result = manager.start_game("blobby", server=False)

            self.assertTrue(result.ok)
            self.assertEqual(result.details.get("runtime"), "proton")
            self.assertEqual(len(platform.calls), 1)
            _launched, args = platform.calls[0]
            self.assertEqual(
                args[0:4], ["--runtime", "proton", "--runtime-binary", str(proton)]
            )
            db.connection.close()

    def test_linux_install_runs_metadata_winetricks_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            db = open_database(str(base / "db.sqlite"))
            with db.connection:
                db.connection.execute(
                    "INSERT INTO game_catalog(id, title_en, title_de, key, version) VALUES ('blobby','Blobby','Blobby','K','1')"
                )
            metadata_root = base / "metadata"
            metadata_root.mkdir(parents=True, exist_ok=True)
            (metadata_root / "blobby.json").write_text(
                json.dumps(
                    {
                        "runner": "wine",
                        "installer_tasks": [
                            {"name": "winetricks", "app": "directplay"}
                        ],
                    }
                ),
                encoding="utf-8",
            )
            platform = LinuxStubAdapter()
            manager = self._manager(
                base,
                db.connection,
                platform,
                metadata_root=metadata_root,
            )
            game_dir = base / "LAN" / "blobby"
            game_dir.mkdir(parents=True, exist_ok=True)
            (game_dir / "blobby.eti").write_bytes(b"rar")
            (game_dir / "local").mkdir(parents=True, exist_ok=True)

            popen_calls: list[list[str]] = []

            def _make_process(*args, **_kwargs):
                cmd = list(args[0])
                popen_calls.append(cmd)
                proc = type("Proc", (), {})()
                proc.stdout = ["ok\n"]
                proc.wait = lambda: 0
                return proc

            with (
                patch(
                    "src.core.launcher.game_manager.shutil.which",
                    side_effect=lambda name: {
                        "unrar": "/usr/bin/unrar",
                        "wine": "/usr/bin/wine",
                        "winetricks": "/usr/bin/winetricks",
                    }.get(name),
                ),
                patch(
                    "src.core.launcher.game_manager.subprocess.Popen"
                ) as mocked_popen,
            ):
                mocked_popen.side_effect = _make_process
                result = manager.install("blobby")

            self.assertTrue(result.ok)
            self.assertGreaterEqual(len(popen_calls), 2)
            self.assertEqual(popen_calls[0][0], "/usr/bin/winetricks")
            self.assertIn("directplay", popen_calls[0])
            self.assertEqual(popen_calls[1][0], "/usr/bin/unrar")
            db.connection.close()

    def test_metadata_fallback_reads_game_local_metadata_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            db = open_database(str(base / "db.sqlite"))
            with db.connection:
                db.connection.execute(
                    "INSERT INTO game_catalog(id, title_en, title_de, key, version) VALUES ('blobby','Blobby','Blobby','K','1')"
                )
            platform = WindowsStubAdapter()
            manager = self._manager(
                base, db.connection, platform, metadata_root=base / "metadata"
            )

            game_dir = base / "LAN" / "blobby"
            (game_dir / "local").mkdir(parents=True, exist_ok=True)
            (game_dir / "metadata").mkdir(parents=True, exist_ok=True)
            (game_dir / "metadata" / "blobby.json").write_text(
                json.dumps(
                    {
                        "game_start": {
                            "file": "custom/game_start_custom.cmd",
                            "args": ["--custom-flag"],
                        }
                    }
                ),
                encoding="utf-8",
            )
            custom = game_dir / "custom" / "game_start_custom.cmd"
            custom.parent.mkdir(parents=True, exist_ok=True)
            custom.write_text("@echo off", encoding="utf-8")

            result = manager.start_game("blobby", server=False)
            self.assertTrue(result.ok)
            self.assertEqual(len(platform.calls), 1)
            launched, args = platform.calls[0]
            self.assertEqual(Path(launched), custom)
            self.assertIn("--custom-flag", args)
            db.connection.close()

    def test_linux_setup_cmd_forces_wine_prefix_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            db = open_database(str(base / "db.sqlite"))
            with db.connection:
                db.connection.execute(
                    "INSERT INTO game_catalog(id, title_en, title_de, key, version) VALUES ('blobby','Blobby','Blobby','K','1')"
                )
            checks = base / "checks.json"
            checks.write_text('{"games":{}}', encoding="utf-8")
            support = InstallSupport(str(base / "scripts"), str(checks))
            platform = LinuxStubAdapter()
            manager = GameLifecycleManager(
                repo=CatalogRepository(db.connection),
                platform_adapter=platform,
                install_support=support,
                library_path=str(base / "LAN"),
                unrar_path=str(base / "unrar.exe"),
                windows_drive_letter="D",
                windows_lan_root="LAN",
                linux_cmd_wrapper_path=str(
                    base / "scripts" / "wrappers" / "linux" / "run-cmd-wrapper.sh"
                ),
            )
            manager.set_linux_runtime_settings("proton-ge", "", "")

            game_dir = base / "LAN" / "blobby"
            game_dir.mkdir(parents=True, exist_ok=True)
            (game_dir / "blobby.eti").write_bytes(b"rar")
            (game_dir / "local").mkdir(parents=True, exist_ok=True)
            (game_dir / "game_setup.cmd").write_text("@echo off", encoding="utf-8")
            wrapper = base / "scripts" / "wrappers" / "linux" / "run-cmd-wrapper.sh"
            wrapper.parent.mkdir(parents=True, exist_ok=True)
            wrapper.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            unrar = base / "unrar"
            unrar.write_text("stub", encoding="utf-8")

            with (
                patch(
                    "src.core.launcher.game_manager.shutil.which",
                    side_effect=lambda name: {
                        "unrar": "/usr/bin/unrar",
                        "wine": "/usr/bin/wine",
                    }.get(name),
                ),
                patch(
                    "src.core.launcher.game_manager.subprocess.Popen"
                ) as mocked_popen,
                patch("src.core.launcher.game_manager.subprocess.run") as mocked_run,
            ):
                proc = mocked_popen.return_value
                proc.stdout = ["ok\n"]
                proc.wait.return_value = 0
                mocked_run.return_value.returncode = 0
                result = manager.install("blobby")

            self.assertTrue(result.ok)
            run_args, _run_kwargs = mocked_run.call_args
            command = run_args[0]
            self.assertEqual(command[0], str(wrapper))
            self.assertEqual(
                command[1:5], ["--runtime", "wine", "--runtime-binary", "/usr/bin/wine"]
            )
            self.assertIn(str(game_dir / ".compatdata" / "wine"), command)
            db.connection.close()

    def test_linux_setup_cmd_uses_absolute_wrapper_when_config_path_is_relative(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            db = open_database(str(base / "db.sqlite"))
            with db.connection:
                db.connection.execute(
                    "INSERT INTO game_catalog(id, title_en, title_de, key, version) VALUES ('blobby','Blobby','Blobby','K','1')"
                )
            checks = base / "checks.json"
            checks.write_text('{"games":{}}', encoding="utf-8")
            support = InstallSupport(str(base / "scripts"), str(checks))
            platform = LinuxStubAdapter()

            wrapper = base / "scripts" / "wrappers" / "linux" / "run-cmd-wrapper.sh"
            wrapper.parent.mkdir(parents=True, exist_ok=True)
            wrapper.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            game_dir = base / "LAN" / "blobby"
            game_dir.mkdir(parents=True, exist_ok=True)
            (game_dir / "blobby.eti").write_bytes(b"rar")
            (game_dir / "local").mkdir(parents=True, exist_ok=True)
            (game_dir / "game_setup.cmd").write_text("@echo off", encoding="utf-8")

            previous_cwd = Path.cwd()
            try:
                os.chdir(base)
                manager = GameLifecycleManager(
                    repo=CatalogRepository(db.connection),
                    platform_adapter=platform,
                    install_support=support,
                    library_path=str(base / "LAN"),
                    unrar_path=str(base / "unrar.exe"),
                    windows_drive_letter="D",
                    windows_lan_root="LAN",
                    linux_cmd_wrapper_path="scripts/wrappers/linux/run-cmd-wrapper.sh",
                )
                manager.set_linux_runtime_settings("proton-ge", "", "")

                with (
                    patch(
                        "src.core.launcher.game_manager.shutil.which",
                        side_effect=lambda name: {
                            "unrar": "/usr/bin/unrar",
                            "wine": "/usr/bin/wine",
                        }.get(name),
                    ),
                    patch(
                        "src.core.launcher.game_manager.subprocess.Popen"
                    ) as mocked_popen,
                    patch(
                        "src.core.launcher.game_manager.subprocess.run"
                    ) as mocked_run,
                ):
                    proc = mocked_popen.return_value
                    proc.stdout = ["ok\n"]
                    proc.wait.return_value = 0
                    mocked_run.return_value.returncode = 0
                    result = manager.install("blobby")

                self.assertTrue(result.ok)
                run_args, _run_kwargs = mocked_run.call_args
                command = run_args[0]
                self.assertEqual(command[0], str(wrapper.resolve()))
            finally:
                os.chdir(previous_cwd)
                db.connection.close()


if __name__ == "__main__":
    unittest.main()
