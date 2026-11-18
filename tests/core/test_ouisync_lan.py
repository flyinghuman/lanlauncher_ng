from __future__ import annotations

import tempfile
import unittest
import json
import os
import platform
from pathlib import Path
from types import SimpleNamespace
from unittest import skipUnless

from src.core.catalog.lan_publish import publish_shared_games
from src.core.sync.ouisync_lan import publish_lan_game
from src.core.sync.ouisync_provider import OuisyncSyncProvider


class _Repository:
    def __init__(self) -> None:
        self.entries = {
            "stale.txt": False,
            "nested": True,
            "nested/old.txt": False,
        }
        self.removed: list[tuple[str, bool]] = []
        self.sync_enabled = False

    async def get_path(self) -> str:
        return "repo-handle"

    async def mount(self) -> str:
        self.mount_path.mkdir(parents=True, exist_ok=True)
        return str(self.mount_path)

    async def unmount(self) -> None:
        self.unmounted = True

    async def read_directory(self, *, path: str) -> list[SimpleNamespace]:
        prefix = path.strip("/")
        result = []
        entries = dict(self.entries)
        if getattr(self, "mount_path", None) and self.mount_path.exists():
            for child in self.mount_path.rglob("*"):
                relative = child.relative_to(self.mount_path).as_posix()
                entries[relative] = child.is_dir()
        for name, is_directory in entries.items():
            parent, _, leaf = name.rpartition("/")
            if parent == prefix:
                result.append(
                    SimpleNamespace(name=leaf, entry_type=2 if is_directory else 1)
                )
        return result

    async def remove_directory(self, *, path: str, recursive: bool = False) -> None:
        name = path.strip("/")
        self.removed.append((name, True))
        for item in list(self.entries):
            if item == name or item.startswith(name + "/"):
                self.entries.pop(item)

    async def remove_file(self, *, path: str) -> None:
        name = path.strip("/")
        self.removed.append((name, False))
        self.entries.pop(name, None)

    async def create_directory(self, *, path: str) -> None:
        self.entries[path.strip("/")] = True

    async def set_sync_enabled(self, *, enabled: bool) -> None:
        self.sync_enabled = enabled

    async def set_dht_enabled(self, *, enabled: bool) -> None:
        self.dht_enabled = enabled

    async def is_dht_enabled(self) -> bool:
        return bool(getattr(self, "dht_enabled", False))

    async def set_pex_enabled(self, *, enabled: bool) -> None:
        self.pex_enabled = enabled

    async def is_pex_enabled(self) -> bool:
        return bool(getattr(self, "pex_enabled", False))

    async def is_sync_enabled(self) -> bool:
        return self.sync_enabled

    async def share(self, *, access_mode: object) -> str:
        self.access_mode = access_mode
        return "private-read-token"

    async def get_info_hash(self) -> str:
        return "A1B2C3"

    async def close(self) -> None:
        self.closed = True


class _Session:
    def __init__(self, repository: _Repository) -> None:
        self.repository = repository
        self.mount_root: Path | None = None

    async def set_mount_root(self, *, path: str) -> None:
        self.mount_root = Path(path)
        self.mount_root.mkdir(parents=True, exist_ok=True)
        self.repository.mount_path = self.mount_root / "lan-repository"

    async def open_repository(self, *, path: str) -> _Repository:
        return self.repository

    async def create_repository(self, **kwargs: object) -> _Repository:
        self.create_kwargs = kwargs
        return self.repository

    async def copy(
        self, *, src_repo: str | None, src_path: str, dst_repo: str, dst_path: str
    ) -> None:
        raise AssertionError("Publisher must copy through the temporary mount")


class OuisyncLanPublisherTests(unittest.IsolatedAsyncioTestCase):
    async def test_mirrors_only_synced_sources_and_returns_read_only_capability(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            game = Path(temporary) / "demo"
            source = game / ".ouisync"
            source.mkdir(parents=True)
            (source / "metadata.json").write_text(
                '{"game_id":"demo","title":{"en":"Demo","de":"Demo"}}', encoding="utf-8"
            )
            (game / "metadata.json").write_text(
                '{"game_id":"demo","title":{"en":"Old root copy"}}',
                encoding="utf-8",
            )
            (source / "demo.tar.gz").write_bytes(b"archive")
            (source / "lan-repository").mkdir()
            (source / "lan-repository" / "private.db").write_text(
                "internal", encoding="utf-8"
            )
            (source / "repository.ouisyncdb").write_text("internal", encoding="utf-8")
            (source / "lan-repository.ouisyncdb-wal").write_text(
                "internal", encoding="utf-8"
            )
            (source / "demo").mkdir()
            (source / "demo" / "private.db").write_text("internal", encoding="utf-8")
            (source / "demo.ouisyncdb").write_text("internal", encoding="utf-8")
            (source / "demo.ouisyncdb-wal").write_text("internal", encoding="utf-8")
            (source / ".llng-materialized.json").write_text("[]", encoding="utf-8")
            (source / ".llng-ouisync-stage-test").mkdir()
            (game / "game_start.sh").write_text("launch", encoding="utf-8")
            (game / "user-note.txt").write_text("shared", encoding="utf-8")
            (game / "local").mkdir()
            (game / "local" / "settings.ini").write_text(
                "client local", encoding="utf-8"
            )

            repository = _Repository()
            session = _Session(repository)
            api = SimpleNamespace(AccessMode=SimpleNamespace(READ="read"))
            result = await publish_lan_game(session, api, str(game))
            (source / "demo.tar.gz").write_bytes(b"updated archive")
            result = await publish_lan_game(session, api, str(game))
            self.assertEqual(
                (repository.mount_path / "demo.tar.gz").read_bytes(),
                b"updated archive",
            )
            copied_names = {path.name for path in repository.mount_path.iterdir()}
            self.assertEqual(
                copied_names,
                {"metadata.json", "demo.tar.gz", "game_start.sh", "user-note.txt"},
            )
            self.assertIn(
                '"Demo"',
                (repository.mount_path / "metadata.json").read_text(encoding="utf-8"),
            )
            self.assertFalse((repository.mount_path / "local").exists())
            self.assertFalse((repository.mount_path / ".ouisync").exists())

        self.assertEqual(
            result, {"read_token": "private-read-token", "info_hash": "a1b2c3"}
        )
        self.assertEqual(repository.access_mode, "read")
        self.assertTrue(repository.sync_enabled)
        self.assertFalse(getattr(repository, "closed", False))
        self.assertIn(("stale.txt", False), repository.removed)
        self.assertIn(("nested/old.txt", False), repository.removed)
        self.assertIn(("nested", True), repository.removed)

    async def test_shares_local_folder_without_ouisync_and_excludes_local_tree(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            game = Path(temporary) / "blobbynew"
            game.mkdir()
            (game / "metadata.json").write_text(
                '{"game_id":"blobbynew","title":{"en":"Blobby"}}',
                encoding="utf-8",
            )
            (game / "blobbynew.rar").write_bytes(b"archive")
            (game / "cover.png").write_bytes(b"cover")
            (game / "local").mkdir()
            (game / "local" / "settings.ini").write_text(
                "client local", encoding="utf-8"
            )

            repository = _Repository()
            session = _Session(repository)
            await publish_lan_game(
                session,
                SimpleNamespace(AccessMode=SimpleNamespace(READ="read")),
                str(game),
            )

            self.assertEqual(
                {path.name for path in repository.mount_path.iterdir()},
                {"metadata.json", "blobbynew.rar", "cover.png"},
            )
            self.assertFalse((repository.mount_path / "local").exists())
            self.assertTrue((game / ".ouisync" / "lan-repository").parent.is_dir())
            self.assertEqual(
                session.create_kwargs["path"],
                str(game / ".ouisync" / "lan-repository"),
            )

    async def test_rejects_symlinks_inside_published_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            game = Path(temporary) / "demo"
            source = game / ".ouisync"
            source.mkdir(parents=True)
            outside = Path(temporary) / "outside.txt"
            outside.write_text("outside", encoding="utf-8")
            (source / "outside.txt").symlink_to(outside)
            with self.assertRaisesRegex(
                ValueError, "ouisync_lan_source_symlink_unsupported"
            ):
                await publish_lan_game(
                    _Session(_Repository()), SimpleNamespace(), str(game)
                )

    @skipUnless(
        platform.system() in {"Linux", "Windows"},
        "Ouisync CLI is bundled for Linux and Windows",
    )
    @unittest.skipIf(
        os.environ.get("LLNG_TEST_WINE") == "1",
        "Wine cannot install the Windows Ouisync VFS driver",
    )
    def test_bundled_service_seeds_repository_and_issues_read_token(self) -> None:
        root = Path(__file__).resolve().parents[2]
        manifest = json.loads(
            (root / "tools" / "manifest.json").read_text(encoding="utf-8")
        )
        platform_tag = (
            "windows-amd64" if platform.system() == "Windows" else "linux-x64"
        )
        binary = next(
            item["path"]
            for item in manifest["tools"]
            if item["name"] == "ouisync" and item["platform"] == platform_tag
        )
        with tempfile.TemporaryDirectory(prefix="llng-ouisync-lan-") as temporary:
            base = Path(temporary)
            provider = OuisyncSyncProvider(
                binary_path=str(root / binary),
                config_dir=str(base / "config"),
                log_path=str(base / "logs" / "ouisync.log"),
                repo_root=str(root),
                startup_timeout_seconds=15.0,
            )
            self.assertTrue(provider.start().running)
            try:
                library = base / "library"
                game = library / "demo"
                source = game / ".ouisync"
                source.mkdir(parents=True)
                (source / "metadata.json").write_text(
                    '{"game_id":"demo","title":{"en":"Demo","de":"Demo"}}',
                    encoding="utf-8",
                )
                (source / "demo.tar.gz").write_bytes(b"archive")
                (game / "local").mkdir()
                (game / "local" / "settings.ini").write_text(
                    "client settings", encoding="utf-8"
                )

                repository_path = game / ".ouisync" / "lan-repository"
                capability = provider.publish_lan_game(str(game), str(repository_path))
                session_api = provider._session_api
                info_hash = provider._submit(
                    provider._session.get_share_token_info_hash(
                        token=capability["read_token"]
                    )
                )
                access_mode = provider._submit(
                    provider._session.get_share_token_access_mode(
                        token=capability["read_token"]
                    )
                )
                self.assertEqual(str(info_hash).lower(), capability["info_hash"])
                self.assertEqual(access_mode, session_api.AccessMode.READ)
                seeded = provider._submit(
                    provider._session.open_repository(path=str(repository_path))
                )
                try:
                    entries = provider._submit(seeded.read_directory(path="/"))
                    self.assertEqual(
                        {entry.name for entry in entries},
                        {"metadata.json", "demo.tar.gz"},
                    )
                    self.assertTrue(provider._submit(seeded.is_sync_enabled()))
                    provider.reconcile_lan_shared_games([])
                    self.assertFalse(provider._submit(seeded.is_sync_enabled()))
                    provider.reconcile_lan_shared_games([str(repository_path)])
                    self.assertTrue(provider._submit(seeded.is_sync_enabled()))
                finally:
                    provider._submit(seeded.close())
            finally:
                provider.stop()

    @skipUnless(
        platform.system() == "Linux"
        and Path("/dev/fuse").exists()
        and os.access("/dev/fuse", os.R_OK | os.W_OK),
        "Linux FUSE device is unavailable",
    )
    def test_bundled_cli_mounts_readonly_share_and_removes_only_repository(
        self,
    ) -> None:
        root = Path(__file__).resolve().parents[2]
        manifest = json.loads(
            (root / "tools" / "manifest.json").read_text(encoding="utf-8")
        )
        binary = next(
            item["path"]
            for item in manifest["tools"]
            if item["name"] == "ouisync" and item["platform"] == "linux-x64"
        )

        with tempfile.TemporaryDirectory(prefix="llng-ouisync-mount-e2e-") as temporary:
            base = Path(temporary)
            provider = OuisyncSyncProvider(
                binary_path=str(root / binary),
                config_dir=str(base / "config"),
                log_path=str(base / "logs" / "ouisync.log"),
                repo_root=str(root),
                startup_timeout_seconds=15.0,
            )
            self.assertTrue(provider.start().running)
            try:
                library = base / "library"
                game = library / "demo"
                source = game / ".ouisync"
                source.mkdir(parents=True)
                (source / "metadata.json").write_text(
                    '{"game_id":"demo","title":{"en":"Demo","de":"Demo"}}',
                    encoding="utf-8",
                )
                archive_payload = b"archive read through temporary FUSE mount"
                (source / "demo.tar.gz").write_bytes(archive_payload)
                repository_path = (
                    base / "external-storage" / "demo" / ".ouisync" / "lan-repository"
                )

                def publish(folder: str) -> dict[str, str]:
                    return provider.publish_lan_game(folder, str(repository_path))

                publish_shared_games(
                    library,
                    [{"id": "demo", "path": str(game)}],
                    ouisync_publisher=publish,
                )
                local_index = json.loads(
                    (library / "locallansync" / ".ouisync" / "index.json").read_text(
                        encoding="utf-8"
                    )
                )
                capability = local_index["games"][0]["llng"]["distribution"]
                tampered_access = SimpleNamespace(
                    game_id="demo",
                    read_token=capability["read_token"],
                    expected_info_hash="wrong-repository-hash",
                    repository_namespace="lan",
                    peer_addrs=(),
                )
                with self.assertRaisesRegex(ValueError, "info_hash_mismatch"):
                    provider.run_with_game_repository_mounted(
                        tampered_access,
                        str(repository_path),
                        lambda mounted: mounted.name,
                    )
                access = SimpleNamespace(
                    game_id="demo",
                    read_token=capability["read_token"],
                    expected_info_hash=capability["info_hash"],
                    repository_namespace="lan",
                    peer_addrs=(),
                )

                read_payload = provider.run_with_game_repository_mounted(
                    access,
                    str(repository_path),
                    lambda mounted: (mounted / "demo.tar.gz").read_bytes(),
                )
                self.assertEqual(read_payload, archive_payload)

                installed_marker = game / "local" / "installed-marker.txt"
                installed_marker.parent.mkdir(parents=True)
                installed_marker.write_text("keep", encoding="utf-8")
                removed, message = provider.delete_game_repository(str(repository_path))
                self.assertTrue(removed, message)
                self.assertTrue(installed_marker.is_file())
                self.assertFalse(Path(f"{repository_path}.ouisyncdb").exists())
            finally:
                provider.stop()


if __name__ == "__main__":
    unittest.main()
