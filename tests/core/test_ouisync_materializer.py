from __future__ import annotations

import asyncio
import tempfile
import threading
import unittest
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

from src.core.sync.ouisync_materializer import materialize_repository


@dataclass
class _Entry:
    name: str


class _Repository:
    def __init__(self, *, info_hash: str = "expected") -> None:
        self.info_hash = info_hash
        self.sync_enabled = True

    async def get_info_hash(self) -> str:
        return self.info_hash

    async def set_sync_enabled(self, *, enabled: bool) -> None:
        self.sync_enabled = enabled

    async def is_sync_enabled(self) -> bool:
        return self.sync_enabled

    async def get_short_name(self) -> str:
        return "demo"

    async def get_path(self) -> str:
        return "/repo/demo"

    async def read_directory(self, *, path: str) -> list[_Entry]:
        assert path == "/"
        return [_Entry("metadata.json"), _Entry("game.tar.gz"), _Entry("bin")]

    async def get_sync_progress(self):
        return SimpleNamespace(value=100, total=100)


class _Session:
    def __init__(self, *, fail_on: str = "", cancel_after_copy=None) -> None:
        self.repository = _Repository()
        self.fail_on = fail_on
        self.cancel_after_copy = cancel_after_copy
        self.created: list[dict] = []

    async def open_repository(self, *, path: str) -> _Repository:
        return self.repository

    async def create_repository(self, **kwargs) -> _Repository:
        self.created.append(kwargs)
        return self.repository

    async def copy(self, *, src_repo, src_path, dst_repo, dst_path) -> None:
        assert src_repo == "/repo/demo"
        assert dst_repo is None
        src_path = src_path.lstrip("/")
        if src_path == self.fail_on:
            raise OSError("copy failed")
        destination = Path(dst_path) / src_path
        if src_path == "bin":
            destination.mkdir()
            (destination / "game_start.sh").write_text("#!/bin/sh\n")
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(src_path)
        if self.cancel_after_copy is not None:
            self.cancel_after_copy.set()


@dataclass
class _Access:
    game_id: str = "demo"
    read_token: str = "secret-token"
    expected_info_hash: str = "expected"
    editable_files: tuple[str, ...] = ("bin/game_start.sh",)


class OuisyncMaterializerTests(unittest.TestCase):
    def test_materializes_repository_content_and_only_declared_editable_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            game = Path(temporary) / "demo"
            session = _Session()
            progress = []
            asyncio.run(
                materialize_repository(
                    session=session,
                    access=_Access(),
                    game_directory=game,
                    progress=lambda *values: progress.append(values),
                )
            )

            self.assertEqual(session.created[0]["token"], "secret-token")
            self.assertEqual(
                (game / ".ouisync" / "metadata.json").read_text(), "metadata.json"
            )
            self.assertTrue((game / ".ouisync" / "game.tar.gz").is_file())
            self.assertFalse((game / "game.tar.gz").exists())
            self.assertTrue((game / ".ouisync" / "bin" / "game_start.sh").is_file())
            self.assertTrue((game / "bin" / "game_start.sh").is_file())
            self.assertFalse((game / "metadata.json").exists())
            self.assertEqual(progress[-1], ("complete", 3, 3))
            self.assertEqual(
                [path.name for path in game.glob(".llng-ouisync-stage-*")], []
            )

    def test_materializes_provider_files_at_library_root_and_keeps_database_hidden(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            game = Path(temporary) / "ng_provider"
            session = _Session()
            repository_path = game / ".ouisync" / "repository"
            asyncio.run(
                materialize_repository(
                    session=session,
                    access=_Access(game_id="ng_provider", editable_files=()),
                    game_directory=game,
                    materialized_directory=game,
                    repository_path=repository_path,
                )
            )

            self.assertEqual(session.created[0]["path"], str(repository_path))
            self.assertTrue((game / "metadata.json").is_file())
            self.assertTrue((game / "game.tar.gz").is_file())
            self.assertTrue((game / ".llng-materialized.json").is_file())
            self.assertFalse((game / ".ouisync" / "metadata.json").exists())

    def test_info_hash_mismatch_disables_repo_without_materializing_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            game = Path(temporary) / "demo"
            session = _Session()
            session.repository.info_hash = "other"
            with self.assertRaisesRegex(ValueError, "info_hash_mismatch"):
                asyncio.run(
                    materialize_repository(
                        session=session, access=_Access(), game_directory=game
                    )
                )
            self.assertFalse(session.repository.sync_enabled)
            self.assertEqual(list((game / ".ouisync").glob(".llng-ouisync-stage-*")), [])
            self.assertFalse((game / ".ouisync" / "metadata.json").exists())

    def test_failed_copy_cleans_staging_and_preserves_previous_materialized_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            game = Path(temporary) / "demo"
            content = game / ".ouisync"
            content.mkdir(parents=True)
            (content / "metadata.json").write_text("old metadata")
            session = _Session(fail_on="game.tar.gz")
            with self.assertRaisesRegex(OSError, "copy failed"):
                asyncio.run(
                    materialize_repository(
                        session=session, access=_Access(), game_directory=game
                    )
                )
            self.assertEqual((content / "metadata.json").read_text(), "old metadata")
            self.assertEqual(list(game.glob(".llng-ouisync-stage-*")), [])

    def test_cancellation_before_copy_cleans_staging_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            game = Path(temporary) / "demo"
            cancelled = threading.Event()
            cancelled.set()
            with self.assertRaises(asyncio.CancelledError):
                asyncio.run(
                    materialize_repository(
                        session=_Session(),
                        access=_Access(),
                        game_directory=game,
                        cancelled=cancelled,
                    )
                )
            self.assertEqual(list(game.glob(".llng-ouisync-stage-*")), [])

    def test_cancellation_after_partial_staging_keeps_previous_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            game = Path(temporary) / "demo"
            content = game / ".ouisync"
            content.mkdir(parents=True)
            (content / "metadata.json").write_text("previous snapshot")
            cancelled = threading.Event()
            session = _Session(cancel_after_copy=cancelled)
            with self.assertRaises(asyncio.CancelledError):
                asyncio.run(
                    materialize_repository(
                        session=session,
                        access=_Access(),
                        game_directory=game,
                        cancelled=cancelled,
                    )
                )
            self.assertEqual((content / "metadata.json").read_text(), "previous snapshot")
            self.assertEqual(list(game.glob(".llng-ouisync-stage-*")), [])

    def test_unsafe_repository_entry_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            game = Path(temporary) / "demo"
            session = _Session()
            session.repository.read_directory = lambda *, path: asyncio.sleep(  # type: ignore[method-assign]
                0, result=[_Entry("../outside")]
            )
            with self.assertRaisesRegex(ValueError, "entry_unsafe"):
                asyncio.run(
                    materialize_repository(
                        session=session, access=_Access(), game_directory=game
                    )
                )
            self.assertFalse(Path(temporary, "outside").exists())
            self.assertEqual(list(game.glob(".llng-ouisync-stage-*")), [])


if __name__ == "__main__":
    unittest.main()
