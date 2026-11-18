from __future__ import annotations

import asyncio
import json
import tempfile
import threading
import unittest
import unittest.mock
from pathlib import Path
from types import SimpleNamespace

from src.core.sync.ouisync_repository import (
    copy_repository_assets,
    ensure_repository_synced,
    game_repository_path,
    remove_repository_assets,
    run_with_repository_mount,
)


class _Repository:
    def __init__(self) -> None:
        self.sync_enabled = True
        self.unmounted = False
        self.access_mode = 1
        self.dht_enabled = True

    async def get_access_mode(self) -> int:
        return self.access_mode

    async def is_dht_enabled(self) -> bool:
        return self.dht_enabled

    async def set_dht_enabled(self, *, enabled: bool) -> None:
        self.dht_enabled = enabled

    async def get_info_hash(self) -> str:
        return "expected"

    async def is_sync_enabled(self) -> bool:
        return self.sync_enabled

    async def set_sync_enabled(self, *, enabled: bool) -> None:
        self.sync_enabled = enabled

    async def get_sync_progress(self):
        return SimpleNamespace(value=1, total=1)

    async def read_directory(self, *, path: str):
        return [SimpleNamespace(name="demo.tar.gz")]

    async def mount(self) -> str:
        return self.mount_path

    async def unmount(self) -> None:
        self.unmounted = True


class _Session:
    def __init__(self, mount_root: Path) -> None:
        self.repository = _Repository()
        self.repository.mount_path = str(mount_root / "demo")
        self.repository.unmounted = False

    async def list_repositories(self):
        return {}

    async def create_repository(self, **kwargs):
        self.created = kwargs
        return self.repository

    async def set_mount_root(self, *, path: str) -> None:
        Path(path).mkdir(parents=True, exist_ok=True)
        Path(self.repository.mount_path).mkdir(parents=True, exist_ok=True)


class OuisyncRepositoryTests(unittest.TestCase):
    def test_per_game_path_uses_separate_optional_storage_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            library = Path(temporary) / "games"
            storage = Path(temporary) / "bulk-disk"
            self.assertEqual(
                game_repository_path(library, "demo"),
                library / "demo" / ".ouisync" / "demo",
            )
            self.assertEqual(
                game_repository_path(library, "demo", storage),
                storage / "demo" / ".ouisync" / "demo",
            )
            with self.assertRaisesRegex(ValueError, "unsafe"):
                game_repository_path(library, "../other")

    def test_per_game_path_rejects_case_only_repository_collisions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            storage = Path(temporary) / "storage"
            (storage / "Demo").mkdir(parents=True)
            with self.assertRaisesRegex(ValueError, "path_collision"):
                game_repository_path(storage, "demo")

    def test_repository_is_unmounted_after_action_and_hash_is_checked(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            session = _Session(root / "mounts")
            result = asyncio.run(
                run_with_repository_mount(
                    session=session,
                    access=SimpleNamespace(
                        read_token="private", expected_info_hash="expected"
                    ),
                    repository_path=root / "storage" / "demo",
                    mount_root=root / "mounts",
                    action=lambda mounted: mounted.name,
                )
            )
            self.assertEqual(result, "demo")
            self.assertTrue(session.repository.unmounted)
            self.assertEqual(session.created["token"], "private")

    def test_repository_hash_mismatch_disables_sync_and_prevents_mount(self) -> None:
        class TamperedRepository(_Repository):
            async def get_info_hash(self) -> str:
                return "tampered"

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            session = _Session(root / "mounts")
            session.repository = TamperedRepository()
            session.repository.mount_path = str(root / "mounts" / "demo")
            session.repository.unmounted = False

            with self.assertRaisesRegex(ValueError, "info_hash_mismatch"):
                asyncio.run(
                    run_with_repository_mount(
                        session=session,
                        access=SimpleNamespace(
                            read_token="private", expected_info_hash="expected"
                        ),
                        repository_path=root / "storage" / "demo",
                        mount_root=root / "mounts",
                        action=lambda mounted: mounted.name,
                    )
                )

            self.assertFalse(session.repository.sync_enabled)
            self.assertFalse(session.repository.unmounted)

    def test_hash_mismatch_never_pauses_this_devices_writable_seed(self) -> None:
        class OwnSeed(_Repository):
            async def get_info_hash(self) -> str:
                return "own-lan-seed"

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            session = _Session(root / "mounts")
            session.repository = OwnSeed()
            session.repository.access_mode = 2
            with self.assertRaisesRegex(ValueError, "info_hash_mismatch"):
                asyncio.run(
                    ensure_repository_synced(
                        session=session,
                        access=SimpleNamespace(
                            read_token="other", expected_info_hash="expected"
                        ),
                        repository_path=root / "storage" / "demo",
                    )
                )
            self.assertTrue(session.repository.sync_enabled)

    def test_private_lan_repository_disables_dht_on_existing_replica(self) -> None:
        for namespace, expected_dht in (("lan-repository", False), ("repository", True)):
            with self.subTest(namespace=namespace), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                session = _Session(root / "mounts")
                asyncio.run(
                    ensure_repository_synced(
                        session=session,
                        access=SimpleNamespace(
                            read_token="private",
                            expected_info_hash="expected",
                            repository_namespace=namespace,
                        ),
                        repository_path=root / "storage" / "demo",
                    )
                )
                self.assertEqual(session.repository.dht_enabled, expected_dht)
                self.assertEqual(session.created["dht_enabled"], expected_dht)

    def test_mount_is_unmounted_when_install_action_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            session = _Session(root / "mounts")

            def fail(_mounted: Path) -> None:
                raise OSError("install failed")

            with self.assertRaisesRegex(OSError, "install failed"):
                asyncio.run(
                    run_with_repository_mount(
                        session=session,
                        access=SimpleNamespace(
                            read_token="private", expected_info_hash="expected"
                        ),
                        repository_path=root / "storage" / "demo",
                        mount_root=root / "mounts",
                        action=fail,
                    )
                )
            self.assertTrue(session.repository.unmounted)

    def test_mount_stays_open_until_cancelled_worker_stops_reading(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            session = _Session(root / "mounts")
            entered = threading.Event()
            release = threading.Event()

            def wait_for_cancel(_mounted: Path) -> None:
                entered.set()
                release.wait(timeout=2)

            async def scenario() -> None:
                task = asyncio.create_task(
                    run_with_repository_mount(
                        session=session,
                        access=SimpleNamespace(
                            read_token="private", expected_info_hash="expected"
                        ),
                        repository_path=root / "storage" / "demo",
                        mount_root=root / "mounts",
                        action=wait_for_cancel,
                    )
                )
                self.assertTrue(await asyncio.to_thread(entered.wait, 1))
                task.cancel()
                await asyncio.sleep(0.01)
                self.assertFalse(session.repository.unmounted)
                release.set()
                with self.assertRaises(asyncio.CancelledError):
                    await task

            asyncio.run(scenario())
            self.assertTrue(session.repository.unmounted)

    def test_assets_keep_archive_in_repository_and_can_be_removed_safely(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "mounted"
            source.mkdir()
            (source / "metadata.json").write_text(
                json.dumps(
                    {
                        "distribution": {
                            "archive": {"file": "demo.tar.gz", "format": "tar.gz"}
                        },
                        "media": {"image_url": "cover.png"},
                        "game_start": {"file": "game_start.sh"},
                    }
                ),
                encoding="utf-8",
            )
            (source / "demo.tar.gz").write_bytes(b"archive")
            (source / "game_start.sh").write_text("#!/bin/sh\n", encoding="utf-8")
            (source / "cover.png").write_bytes(b"image")
            (source / "unneeded-large-payload.bin").write_bytes(b"unused")
            game = root / "library" / "demo"

            copied = copy_repository_assets(source, game, game_id="demo")
            self.assertNotIn("demo.tar.gz", copied)
            self.assertFalse((game / ".ouisync" / "demo.tar.gz").exists())
            self.assertTrue((game / ".ouisync" / "metadata.json").is_file())
            self.assertTrue((game / ".ouisync" / "cover.png").is_file())
            self.assertFalse(
                (game / ".ouisync" / "unneeded-large-payload.bin").exists()
            )
            self.assertTrue((game / "game_start.sh").is_file())
            (game / "local").mkdir()
            (game / "local" / "settings.ini").write_text("keep", encoding="utf-8")

            remove_repository_assets(game)
            self.assertFalse((game / ".ouisync" / "metadata.json").exists())
            self.assertTrue((game / "game_start.sh").is_file())
            self.assertTrue((game / "local" / "settings.ini").is_file())


if __name__ == "__main__":
    unittest.main()


class _StalledFile:
    def __init__(self, content: bytes, fail: bool) -> None:
        self.content = content
        self.fail = fail
        self.closed = False

    async def get_length(self) -> int:
        return len(self.content)

    async def read(self, *, offset: int, size: int) -> bytes:
        if self.fail:
            raise RuntimeError("BlockNotFound")
        return self.content[offset : offset + size]

    async def close(self) -> None:
        self.closed = True


class _StalledRepository:
    """Repository whose block counter stays below its total (Ouisync 0.10.x)."""

    def __init__(self, *, readable: bool, complete_after_polls: int | None = None) -> None:
        self.readable = readable
        self.complete_after_polls = complete_after_polls
        self.polls = 0
        self.opened: list[str] = []
        self.files: list[_StalledFile] = []

    async def get_sync_progress(self):
        self.polls += 1
        if self.complete_after_polls is not None and self.polls >= self.complete_after_polls:
            return SimpleNamespace(value=100, total=100)
        return SimpleNamespace(value=98, total=100)

    async def read_directory(self, *, path: str):
        if path == "/":
            return [
                SimpleNamespace(name="update", entry_type=2),
                SimpleNamespace(name="index.json", entry_type=1),
            ]
        if path == "/update":
            return [SimpleNamespace(name="package.zip", entry_type=1)]
        return []

    async def open_file(self, *, path: str):
        self.opened.append(path)
        file = _StalledFile(b"x" * 2500, fail=not self.readable)
        self.files.append(file)
        return file


class WaitUntilRepositoryCompleteTests(unittest.TestCase):
    def test_stalled_progress_completes_when_every_file_is_readable(self) -> None:
        from src.core.sync import ouisync_repository as module

        repository = _StalledRepository(readable=True)
        with unittest.mock.patch.object(module, "VERIFY_READ_CHUNK_BYTES", 1000):
            with self.assertLogs("test.ouisync", level="INFO") as logs:
                entries, progress = asyncio.run(
                    module.wait_until_repository_complete(
                        repository,
                        stall_seconds=0.05,
                        poll_seconds=0.01,
                        logger=__import__("logging").getLogger("test.ouisync"),
                    )
                )
        self.assertEqual([entry.name for entry in entries], ["update", "index.json"])
        self.assertEqual((progress.value, progress.total), (98, 100))
        self.assertEqual(sorted(repository.opened), ["/index.json", "/update/package.zip"])
        self.assertTrue(all(file.closed for file in repository.files))
        self.assertIn("ouisync_progress_stalled_content_verified", logs.output[0])

    def test_genuinely_missing_blocks_keep_waiting_until_progress_completes(self) -> None:
        from src.core.sync import ouisync_repository as module

        repository = _StalledRepository(readable=False, complete_after_polls=40)
        _entries, progress = asyncio.run(
            module.wait_until_repository_complete(
                repository, stall_seconds=0.02, poll_seconds=0.005
            )
        )
        self.assertEqual((progress.value, progress.total), (100, 100))
        self.assertTrue(repository.opened)
        self.assertTrue(all(file.closed for file in repository.files))

    def test_empty_repository_is_nudged_with_escalation_until_blocks_arrive(self) -> None:
        from src.core.sync import ouisync_repository as module

        class EmptyRepository:
            def __init__(self):
                self.polls = 0

            async def get_sync_progress(self):
                self.polls += 1
                # 0/0 like a fresh replica whose index has not arrived yet.
                return SimpleNamespace(value=0, total=0) if self.polls < 60 else SimpleNamespace(value=1, total=1)

            async def read_directory(self, *, path):
                return [] if self.polls < 60 else [SimpleNamespace(name="demo.tar.gz")]

        attempts: list[int] = []

        async def nudge(attempt: int) -> None:
            attempts.append(attempt)

        repository = EmptyRepository()
        asyncio.run(
            module.wait_until_repository_complete(
                repository, poll_seconds=0.005, nudge=nudge, nudge_seconds=0.03
            )
        )
        # First attempt after 30 ms, then 60 ms, 120 ms ...; attempts count up.
        self.assertGreaterEqual(len(attempts), 2)
        self.assertEqual(attempts, list(range(len(attempts))))

    def test_repository_with_local_blocks_is_never_nudged(self) -> None:
        from src.core.sync import ouisync_repository as module

        repository = _StalledRepository(readable=False, complete_after_polls=30)
        nudged: list[int] = []

        async def nudge(attempt: int) -> None:
            nudged.append(attempt)

        asyncio.run(
            module.wait_until_repository_complete(
                repository,
                stall_seconds=10,
                poll_seconds=0.005,
                nudge=nudge,
                nudge_seconds=0.01,
            )
        )
        self.assertEqual(nudged, [])

    def test_failed_nudge_does_not_end_the_wait(self) -> None:
        from src.core.sync import ouisync_repository as module

        class Repository:
            polls = 0

            async def get_sync_progress(self):
                Repository.polls += 1
                done = Repository.polls >= 20
                return SimpleNamespace(value=int(done), total=int(done))

            async def read_directory(self, *, path):
                return [SimpleNamespace(name="a")] if Repository.polls >= 20 else []

        async def nudge(_attempt: int) -> None:
            raise RuntimeError("network down")

        _entries, progress = asyncio.run(
            module.wait_until_repository_complete(
                Repository(), poll_seconds=0.005, nudge=nudge, nudge_seconds=0.01
            )
        )
        self.assertEqual(progress.value, 1)

    def test_nudge_readds_peers_restarts_dht_and_relinks_on_escalation(self) -> None:
        from src.core.sync import ouisync_repository as module

        calls: list[tuple] = []

        class Session:
            async def get_user_provided_peers(self):
                return ["quic/10.0.0.2:1", "quic/10.0.0.1:1"]

            async def add_user_provided_peers(self, *, addrs):
                calls.append(("peers", tuple(addrs)))

        class Repository:
            def __init__(self, dht):
                self.dht = dht

            async def is_sync_enabled(self):
                return True

            async def is_dht_enabled(self):
                return self.dht

            async def set_dht_enabled(self, *, enabled):
                calls.append(("dht", enabled))

            async def set_sync_enabled(self, *, enabled):
                calls.append(("sync", enabled))

            async def get_path(self):
                return "/repo"

        soft = asyncio.run(
            module.nudge_repository(
                Session(), Repository(dht=True), peer_addrs=("quic/10.0.0.1:1",)
            )
        )
        self.assertEqual(soft, ["peers_readded", "dht_lookup_restarted"])
        self.assertEqual(
            calls,
            [
                ("peers", ("quic/10.0.0.1:1", "quic/10.0.0.2:1")),
                ("dht", False),
                ("dht", True),
            ],
        )
        calls.clear()
        # Private LAN repositories keep DHT off; escalation re-links the repository.
        strong = asyncio.run(
            module.nudge_repository(Session(), Repository(dht=False), relink=True)
        )
        self.assertEqual(strong, ["peers_readded", "sync_relinked"])
        self.assertEqual(calls[1:], [("sync", False), ("sync", True)])

    def test_wait_honors_cancellation(self) -> None:
        from src.core.sync import ouisync_repository as module

        cancelled = threading.Event()
        cancelled.set()
        with self.assertRaises(asyncio.CancelledError):
            asyncio.run(
                module.wait_until_repository_complete(
                    _StalledRepository(readable=True), cancelled=cancelled
                )
            )
