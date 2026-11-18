from __future__ import annotations

import asyncio
import os
import platform
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from src.core.catalog.game_index import OuisyncRepositoryAccess
import src.core.sync.ouisync_provider as ouisync_provider_module
from src.core.sync.ouisync_provider import OuisyncSyncProvider
from src.core.sync.provider import SyncMetrics, SyncStatus


class OuisyncProviderTests(unittest.TestCase):
    def _provider(self, root: Path, **overrides) -> OuisyncSyncProvider:
        values = {
            "binary_path": str(root / "missing-ouisync"),
            "config_dir": str(root / "config"),
            "log_path": str(root / "logs" / "ouisync.log"),
            "repo_root": str(root),
            "startup_timeout_seconds": 1.0,
            "poll_interval_seconds": 0.01,
        }
        values.update(overrides)
        return OuisyncSyncProvider(**values)

    def test_folder_sync_status_reports_zero_blocks_as_not_started(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            provider = self._provider(Path(temporary))
            provider._submit = lambda coroutine, timeout=None: asyncio.run(coroutine)  # type: ignore[method-assign]
            counts = {"value": 0, "total": 0}

            class _Repository:
                async def is_sync_enabled(self) -> bool:
                    return True

                async def get_sync_progress(self) -> SimpleNamespace:
                    return SimpleNamespace(**counts)

            async def find_repository(*, path: Path) -> _Repository:
                return _Repository()

            provider._find_repository = find_repository  # type: ignore[method-assign]
            game_folder = str(Path(temporary) / "demo")

            self.assertEqual(provider.folder_sync_status(game_folder)["progress_percent"], 0)
            counts.update(value=3, total=4)
            self.assertEqual(provider.folder_sync_status(game_folder)["progress_percent"], 75)
            counts.update(value=4, total=4)
            self.assertEqual(provider.folder_sync_status(game_folder)["progress_percent"], 100)

    def test_normalize_peer_address_accepts_ip_socket_addresses_only(self) -> None:
        normalize = ouisync_provider_module.normalize_peer_address
        self.assertEqual(normalize(" 192.168.1.20:20209 "), "quic/192.168.1.20:20209")
        self.assertEqual(normalize("tcp/10.0.0.5:1"), "tcp/10.0.0.5:1")
        self.assertEqual(normalize("quic/[fe80::1]:65535"), "quic/[fe80::1]:65535")
        for value in (
            "",
            "example.org:20209",
            "192.168.1.20",
            "192.168.1.20:0",
            "192.168.1.20:65536",
            "0.0.0.0:20209",
            "224.0.0.1:20209",
            "udp/192.168.1.20:20209",
            "fe80::1:20209",
            "quic/[192.168.1.20]:20209",
            "quic/192.168.1.20:20209 extra",
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize(value)

    def test_manual_nudge_relinks_only_the_selected_repository(self) -> None:
        class Repository:
            def __init__(self, info_hash):
                self.info_hash = info_hash
                self.sync_calls = []

            async def get_info_hash(self):
                return self.info_hash

            async def is_sync_enabled(self):
                return True

            async def is_dht_enabled(self):
                return False

            async def set_sync_enabled(self, *, enabled):
                self.sync_calls.append(enabled)

            async def get_path(self):
                return f"/{self.info_hash}"

        class Session:
            def __init__(self, repositories):
                self.repositories = repositories
                self.added = []

            async def list_repositories(self):
                return {repo.info_hash: repo for repo in self.repositories}

            async def get_user_provided_peers(self):
                return []

            async def add_user_provided_peers(self, *, addrs):
                self.added.append(list(addrs))

        with tempfile.TemporaryDirectory() as temporary:
            provider = self._provider(Path(temporary))
            selected, other = Repository("abc"), Repository("def")
            provider._session = Session([selected, other])
            provider._network_peer_addrs = ("quic/10.0.0.1:1",)
            provider.status = Mock(return_value=SyncStatus("ouisync", True, "running"))  # type: ignore[method-assign]
            provider._submit = lambda coroutine, **_kwargs: asyncio.run(coroutine)  # type: ignore[method-assign]

            result = provider.nudge_repository_sync("ABC")
            missing = provider.nudge_repository_sync("zzz")

            self.assertEqual(result["actions"], ["peers_readded", "sync_relinked"])
            self.assertEqual(selected.sync_calls, [False, True])
            self.assertEqual(other.sync_calls, [])
            self.assertEqual(provider._session.added, [["quic/10.0.0.1:1"]])
            self.assertEqual(missing["message"], "ouisync_repository_not_found")

    def test_user_provided_peer_add_and_remove_use_canonical_address(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            provider = self._provider(Path(temporary))
            provider._session = object()  # noqa: SLF001
            provider.status = Mock(return_value=SyncStatus("ouisync", True, "running"))  # type: ignore[method-assign]
            provider._call_session = Mock()  # type: ignore[method-assign]

            added = provider.update_user_provided_peer("add", "192.168.1.20:20209")
            removed = provider.update_user_provided_peer("remove", "quic/192.168.1.20:20209")
            invalid = provider.update_user_provided_peer("add", "host.lan:20209")
            unknown = provider.update_user_provided_peer("connect", "192.168.1.20:20209")

            self.assertEqual(added["message"], "ouisync_peer_added")
            self.assertEqual(removed["message"], "ouisync_peer_removed")
            self.assertEqual(invalid, {"ok": False, "message": "ouisync_peer_address_invalid"})
            self.assertEqual(unknown, {"ok": False, "message": "ouisync_peer_action_invalid"})
            self.assertEqual(
                provider._call_session.call_args_list,
                [
                    unittest.mock.call(
                        "add_user_provided_peers", addrs=["quic/192.168.1.20:20209"]
                    ),
                    unittest.mock.call(
                        "remove_user_provided_peers", addrs=["quic/192.168.1.20:20209"]
                    ),
                ],
            )

    def test_peer_payload_reports_address_source_state_and_traffic(self) -> None:
        class PeerState_Active:  # noqa: N801 - mirrors the generated Ouisync class name
            pass

        peer = SimpleNamespace(
            addr="quic/192.168.1.20:20209",
            source=SimpleNamespace(name="USER_PROVIDED"),
            state=PeerState_Active(),
            stats=SimpleNamespace(
                bytes_tx=10, bytes_rx=20, throughput_tx=3, throughput_rx=4
            ),
        )
        self.assertEqual(
            ouisync_provider_module._peer_payload(peer, {"quic/192.168.1.20:20209"}),
            {
                "addr": "quic/192.168.1.20:20209",
                "protocol": "quic",
                "address": "192.168.1.20:20209",
                "source": "user_provided",
                "state": "active",
                "user_provided": True,
                "bytes_tx": 10,
                "bytes_rx": 20,
                "throughput_tx": 3,
                "throughput_rx": 4,
            },
        )

    def test_missing_binary_returns_failure_and_can_be_stopped(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            provider = self._provider(Path(temporary))

            status = provider.start()

            self.assertFalse(status.running)
            self.assertEqual(status.state, "failed")
            self.assertEqual(status.last_error, "ouisync_binary_missing")
            self.assertEqual(provider.stop().state, "stopped")

    def test_ng_provider_materializes_when_update_manifest_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "ng_provider"
            root.mkdir()
            local_index = root / "update" / "index.json"
            local_index.parent.mkdir()
            local_index.write_text("same index", encoding="utf-8")
            (root / "update" / "update-manifest.json").write_text(
                "old manifest", encoding="utf-8"
            )
            (root / ".llng-materialized.json").write_text(
                '["update"]', encoding="utf-8"
            )
            provider = self._provider(Path(temporary))
            provider._session = object()  # noqa: SLF001
            provider.status = Mock(return_value=SyncStatus("ouisync", True, "running"))  # type: ignore[method-assign]
            provider._submit = lambda coroutine, timeout=None: asyncio.run(coroutine)  # type: ignore[method-assign]
            provider._register_store_dir = Mock()  # type: ignore[method-assign]

            class _Repository:
                async def get_path(self):
                    return str(root / ".ouisync" / "repository")

                async def read_directory(self, *, path):
                    return [type("Entry", (), {"name": "update"})()]

                async def file_exists(self, *, path):
                    return path != "/update/trusted-publishers.json"

            class _Session:
                async def copy(self, *, src_repo, src_path, dst_repo, dst_path):
                    self.src = (src_repo, src_path, dst_repo)
                    staged = Path(dst_path) / src_path.split("/")[-1]
                    staged.parent.mkdir(parents=True, exist_ok=True)
                    content = (
                        "new manifest"
                        if src_path.endswith("update-manifest.json")
                        else "same index"
                    )
                    staged.write_text(content, encoding="utf-8")

            provider._session = _Session()  # noqa: SLF001

            async def ensure(**_kwargs):
                return _Repository()

            with (
                patch.object(ouisync_provider_module, "ensure_repository_synced", ensure),
                patch.object(
                    ouisync_provider_module,
                    "materialize_repository",
                    new=AsyncMock(),
                ) as copy,
            ):
                ok, detail = provider.start_repository_materialization(
                    OuisyncRepositoryAccess(
                        game_id="ng_provider",
                        read_token="secret",
                        expected_info_hash="hash",
                    ),
                    str(root),
                    materialized_directory=str(root),
                )
                self.assertTrue(ok)
                self.assertEqual(detail, "ouisync_repository_syncing")
                state = provider._materializations["ng_provider"]  # noqa: SLF001
                state["thread"].join(timeout=3)

            self.assertFalse(state["thread"].is_alive())
            self.assertEqual(state["phase"], "complete")
            copy.assert_awaited_once()
            self.assertEqual(copy.await_args.kwargs["materialized_directory"], root)
            self.assertEqual(
                copy.await_args.kwargs["repository_path"],
                root / ".ouisync" / "repository",
            )

    def test_ng_provider_skips_copy_when_synced_index_is_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "ng_provider"
            index = root / "update" / "index.json"
            index.parent.mkdir(parents=True)
            index.write_text("same index", encoding="utf-8")
            (root / "update" / "update-manifest.json").write_text(
                "same manifest", encoding="utf-8"
            )
            (root / ".llng-materialized.json").write_text(
                '["update"]', encoding="utf-8"
            )
            provider = self._provider(Path(temporary))
            provider._session = object()  # noqa: SLF001
            provider.status = Mock(return_value=SyncStatus("ouisync", True, "running"))  # type: ignore[method-assign]
            provider._submit = lambda coroutine, timeout=None: asyncio.run(coroutine)  # type: ignore[method-assign]
            provider._register_store_dir = Mock()  # type: ignore[method-assign]

            class _Repository:
                async def get_path(self):
                    return str(root / ".ouisync" / "repository")

                async def read_directory(self, *, path):
                    return [type("Entry", (), {"name": "update"})()]

                async def file_exists(self, *, path):
                    return path != "/update/trusted-publishers.json"

            class _Session:
                async def copy(self, *, src_repo, src_path, dst_repo, dst_path):
                    staged = Path(dst_path) / (
                        "update-manifest.json"
                        if src_path.endswith("update-manifest.json")
                        else "index.json"
                    )
                    staged.parent.mkdir(parents=True, exist_ok=True)
                    staged.write_text(
                        "same manifest"
                        if src_path.endswith("update-manifest.json")
                        else "same index",
                        encoding="utf-8",
                    )

            provider._session = _Session()  # noqa: SLF001

            async def ensure(**_kwargs):
                return _Repository()

            with (
                patch.object(ouisync_provider_module, "ensure_repository_synced", ensure),
                patch.object(
                    ouisync_provider_module,
                    "materialize_repository",
                    new=AsyncMock(),
                ) as copy,
            ):
                provider.start_repository_materialization(
                    OuisyncRepositoryAccess(
                        game_id="ng_provider",
                        read_token="secret",
                        expected_info_hash="hash",
                    ),
                    str(root),
                    materialized_directory=str(root),
                )
                state = provider._materializations["ng_provider"]  # noqa: SLF001
                state["thread"].join(timeout=3)

            self.assertEqual(state["phase"], "complete", state)
            copy.assert_not_awaited()

    def test_start_failure_if_process_exits_before_endpoint_readiness(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            binary = root / "ouisync"
            binary.write_bytes(b"stub")
            binary.chmod(0o755)
            process = Mock()
            process.poll.return_value = 17
            process.returncode = 17
            process.pid = 123
            process_factory = Mock(return_value=process)
            provider = self._provider(
                root, binary_path=str(binary), process_factory=process_factory
            )

            status = provider.start()

            self.assertFalse(status.running)
            self.assertEqual(status.last_error, "ouisync_process_exited:17")
            process_factory.assert_called_once()
            self.assertFalse(process_factory.call_args.kwargs["shell"])
            self.assertEqual(provider.stop().state, "stopped")

    def test_windows_process_start_uses_no_console_flag(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            binary = root / "ouisync.exe"
            binary.write_bytes(b"stub")
            process_factory = Mock()
            provider = self._provider(
                root, binary_path=str(binary), process_factory=process_factory
            )
            with (
                patch.object(ouisync_provider_module.os, "name", "nt"),
                patch.object(subprocess, "CREATE_NO_WINDOW", 0x08000000, create=True),
            ):
                provider._start_process()
                self.assertEqual(
                    process_factory.call_args.kwargs["creationflags"], 0x08000000
                )
                self.assertFalse(process_factory.call_args.kwargs["shell"])
                provider._terminate_process()

    def test_stop_forces_process_shutdown_when_mount_lock_is_busy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            provider = self._provider(Path(temporary))
            process = Mock()
            process.poll.return_value = None
            process.wait.return_value = 0
            provider._process = process
            self.assertTrue(provider._repository_mount_lock.acquire())
            try:
                with self.assertLogs(
                    "src.core.sync.ouisync_provider", level="WARNING"
                ) as logs:
                    status = provider.stop()
            finally:
                provider._repository_mount_lock.release()

            self.assertEqual(status.state, "stopped")
            self.assertIn(
                "ouisync_mount_shutdown_forced",
                "\n".join(logs.output),
            )
            process.terminate.assert_called_once()
            process.wait.assert_called_once_with(timeout=5.0)

    def test_missing_session_reports_zero_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            provider = self._provider(Path(temporary))

            self.assertEqual(
                provider.metrics(), SyncMetrics(download_bps=0, upload_bps=0)
            )

    def test_repository_inventory_returns_progress_entries_and_transfer_stats(
        self,
    ) -> None:
        class Repository:
            async def get_info_hash(self):
                return "abc123"

            async def get_sync_progress(self):
                return type("Progress", (), {"value": 75, "total": 100})()

            async def get_stats(self):
                return type(
                    "Stats",
                    (),
                    {
                        "bytes_tx": 1,
                        "bytes_rx": 2,
                        "throughput_tx": 3,
                        "throughput_rx": 4,
                    },
                )()

            async def is_sync_enabled(self):
                return True

            async def get_access_mode(self):
                return 2

            async def get_mount_point(self):
                return None

            async def is_dht_enabled(self):
                return True

            async def is_pex_enabled(self):
                return False

            async def mirror_exists(self, *, host):
                self.mirror_host = host
                return True

            async def get_path(self):
                return "/data/demo.ouisyncdb"

            async def get_short_name(self):
                return "Demo"

            async def read_directory(self, *, path):
                self.directory_path = path
                return [type("Entry", (), {"name": "assets", "entry_type": 2})()]

        class Session:
            def __init__(self, repository):
                self.repository = repository

            async def list_repositories(self):
                return {"/data/demo": self.repository}

            async def get_peers(self):
                return []

            async def get_user_provided_peers(self):
                return []

            async def get_local_listener_addrs(self):
                return ["quic/0.0.0.0:20209"]

            async def get_network_stats(self):
                return type(
                    "Stats",
                    (),
                    {
                        "bytes_tx": 5,
                        "bytes_rx": 6,
                        "throughput_tx": 7,
                        "throughput_rx": 8,
                    },
                )()

        with tempfile.TemporaryDirectory() as temporary:
            provider = self._provider(Path(temporary))
            repository = Repository()
            provider._session = Session(repository)
            provider.status = Mock(return_value=SyncStatus("ouisync", True, "running"))
            provider._submit = lambda coroutine, **_kwargs: asyncio.run(coroutine)
            self.assertFalse(
                provider.repository_inventory("abc123", "/assets")["repositories"][0][
                    "content_verified"
                ]
            )
            asyncio.run(provider._remember_verified_progress(repository))
            result = provider.repository_inventory("abc123", "/assets")
            self.assertTrue(result["repositories"][0]["content_verified"])
            self.assertTrue(result["available"])
            self.assertEqual(result["repositories"][0]["local_block_count"], 75)
            self.assertEqual(result["repositories"][0]["repository_block_count"], 100)
            self.assertEqual(result["repositories"][0]["peer_count"], 0)
            self.assertEqual(result["repositories"][0]["throughput_rx"], 4)
            self.assertEqual(
                result["repositories"][0]["settings"],
                {
                    "dht_enabled": True,
                    "peer_exchange_enabled": False,
                    "cache_servers_enabled": True,
                    "cache_servers_writable": True,
                    "available": True,
                },
            )
            self.assertEqual(repository.mirror_host, "server-ca.ouisync.net")
            self.assertEqual(result["repositories"][0]["local_path"], "/data/demo.ouisyncdb")
            self.assertEqual(
                result["repositories"][0]["entries"],
                [{"name": "assets", "path": "/assets/assets", "type": "directory"}],
            )
            self.assertEqual(repository.directory_path, "/assets")
            self.assertEqual(result["peers"], [])
            self.assertEqual(result["listener_addrs"], ["quic/0.0.0.0:20209"])
            self.assertEqual(result["network"]["throughput_tx"], 7)

    def test_update_repository_settings_applies_supported_controls(self) -> None:
        class Repository:
            dht = False
            pex = False
            mirror = False

            async def get_info_hash(self):
                return "abc123"

            async def is_sync_enabled(self):
                return True

            async def get_access_mode(self):
                return 2

            async def set_dht_enabled(self, *, enabled):
                self.dht = enabled

            async def set_pex_enabled(self, *, enabled):
                self.pex = enabled

            async def is_dht_enabled(self):
                return self.dht

            async def is_pex_enabled(self):
                return self.pex

            async def mirror_exists(self, *, host):
                return self.mirror

            async def create_mirror(self, *, host):
                self.mirror = True

            async def delete_mirror(self, *, host):
                self.mirror = False

        class Session:
            def __init__(self, repo):
                self.repo = repo

            async def list_repositories(self):
                return {"/repo": self.repo}

        with tempfile.TemporaryDirectory() as temporary:
            provider = self._provider(Path(temporary))
            repository = Repository()
            provider._session = Session(repository)
            provider.status = Mock(return_value=SyncStatus("ouisync", True, "running"))
            provider._submit = lambda coroutine, **_kwargs: asyncio.run(coroutine)
            result = provider.update_repository_settings(
                "ABC123",
                {
                    "dht_enabled": True,
                    "peer_exchange_enabled": True,
                    "cache_servers_enabled": True,
                },
            )
            self.assertTrue(result["ok"])
            self.assertTrue(result["settings"]["dht_enabled"])
            self.assertTrue(result["settings"]["peer_exchange_enabled"])
            self.assertTrue(result["settings"]["cache_servers_enabled"])

    def test_update_repository_settings_rejects_cache_for_read_only_repo(self) -> None:
        class Repository:
            async def get_info_hash(self):
                return "abc123"

            async def is_sync_enabled(self):
                return True

            async def get_access_mode(self):
                return 1

        class Session:
            async def list_repositories(self):
                return {"/repo": Repository()}

        with tempfile.TemporaryDirectory() as temporary:
            provider = self._provider(Path(temporary))
            provider._session = Session()
            provider.status = Mock(return_value=SyncStatus("ouisync", True, "running"))
            provider._submit = lambda coroutine, **_kwargs: asyncio.run(coroutine)
            result = provider.update_repository_settings(
                "abc123", {"cache_servers_enabled": True}
            )
            self.assertFalse(result["ok"])
            self.assertEqual(result["message"], "ouisync_cache_servers_write_required")

    def test_copy_repository_entry_to_disk_uses_safe_game_folder(self) -> None:
        class Repository:
            async def get_info_hash(self):
                return "abc123"

            async def get_path(self):
                return "/data/demo.ouisyncdb"

        class Session:
            def __init__(self):
                self.copy_args = None

            async def list_repositories(self):
                return {"/repo": Repository()}

            async def copy(self, **kwargs):
                self.copy_args = kwargs

        with tempfile.TemporaryDirectory() as temporary:
            provider = self._provider(Path(temporary))
            session = Session()
            provider._session = session
            provider.status = Mock(return_value=SyncStatus("ouisync", True, "running"))
            provider._submit = lambda coroutine, **_kwargs: asyncio.run(coroutine)
            result = provider.copy_repository_entry_to_disk(
                "abc123", "/assets", str(Path(temporary) / "demo")
            )
            self.assertTrue(result["ok"])
            self.assertEqual(session.copy_args["src_repo"], "/data/demo.ouisyncdb")
            self.assertEqual(session.copy_args["src_path"], "/assets")
            self.assertEqual(session.copy_args["dst_path"], str(Path(temporary) / "demo"))

    def test_copy_repository_entry_rejects_traversal_and_reserved_destination(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            provider = self._provider(Path(temporary))
            unsafe_source = provider.copy_repository_entry_to_disk(
                "abc123", "/../outside", temporary
            )
            reserved_target = provider.copy_repository_entry_to_disk(
                "abc123", "/file", temporary, ".ouisync"
            )
            self.assertEqual(unsafe_source["message"], "ouisync_repository_entry_unsafe")
            self.assertEqual(reserved_target["message"], "ouisync_repository_entry_unsafe")

    def test_mount_readonly_repository_uses_game_folder_and_restores_mount_root(self) -> None:
        class Repository:
            mount_point = None

            async def get_info_hash(self):
                return "abc123"

            async def get_access_mode(self):
                return 1

            async def get_mount_point(self):
                return self.mount_point

            async def mount(self):
                self.mount_point = str(session.mount_root / "Demo")
                return self.mount_point

            async def unmount(self):
                self.mount_point = None

        class Session:
            def __init__(self):
                self.mount_root = Path("/old/mounts")

            async def list_repositories(self):
                return {"/repo": repository}

            async def get_mount_root(self):
                return str(self.mount_root)

            async def set_mount_root(self, *, path):
                self.mount_root = Path(path) if path else None

        with tempfile.TemporaryDirectory() as temporary:
            provider = self._provider(Path(temporary))
            session = Session()
            repository = Repository()
            provider._session = session
            provider.status = Mock(return_value=SyncStatus("ouisync", True, "running"))
            provider._submit = lambda coroutine, **_kwargs: asyncio.run(coroutine)
            mounted = provider.mount_readonly_repository(
                "abc123", str(Path(temporary) / "game")
            )
            self.assertTrue(mounted["ok"])
            self.assertTrue(
                Path(mounted["mount_point"]).is_relative_to(
                    Path(temporary) / "game" / "ouisyncmount"
                )
            )
            unmounted = provider.unmount_repository("abc123")
            self.assertTrue(unmounted["ok"])
            self.assertEqual(session.mount_root, Path("/old/mounts"))

    def test_cached_mirror_status_is_bounded_and_cached_when_offline(self) -> None:
        class Repository:
            calls = 0

            async def mirror_exists(self, *, host):
                self.calls += 1
                raise ConnectionError("offline")

        with tempfile.TemporaryDirectory() as temporary:
            provider = self._provider(Path(temporary))
            repository = Repository()

            async def lookup_twice():
                first = await provider._cached_mirror_status("abc", repository)
                second = await provider._cached_mirror_status("abc", repository)
                return first, second

            self.assertEqual(asyncio.run(lookup_twice()), (None, None))
            self.assertEqual(repository.calls, 1)

    def test_cached_mirror_status_times_out_slow_cache_server(self) -> None:
        class Repository:
            async def mirror_exists(self, *, host):
                await asyncio.sleep(5)
                return True

        with tempfile.TemporaryDirectory() as temporary:
            provider = self._provider(Path(temporary))
            with patch.object(
                ouisync_provider_module, "CACHE_SERVER_LOOKUP_TIMEOUT_SECONDS", 0.01
            ):
                result = asyncio.run(provider._cached_mirror_status("abc", Repository()))
            self.assertIsNone(result)

    def test_force_unmount_refuses_while_repository_sync_is_running(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            provider = self._provider(Path(temporary))
            provider.status = Mock(return_value=SyncStatus("ouisync", True, "running"))
            release = threading.Event()
            worker = threading.Thread(target=release.wait)
            worker.start()
            try:
                provider._materializations["game"] = {
                    "thread": worker,
                    "cancelled": threading.Event(),
                }
                provider.stop = Mock()
                result = provider.force_unmount_repository("abc123")
            finally:
                release.set()
                worker.join()
            self.assertEqual(result, {"ok": False, "message": "ouisync_force_unmount_busy"})
            provider.stop.assert_not_called()

    def test_force_unmount_restores_mount_root_when_restart_left_repo_unmounted(self) -> None:
        class Repository:
            async def get_info_hash(self):
                return "abc123"

            async def get_mount_point(self):
                return None

            async def unmount(self):
                return None

        class Session:
            mount_root = "/games/demo/ouisyncmount"

            async def list_repositories(self):
                return {"/repo": Repository()}

            async def set_mount_root(self, *, path):
                self.mount_root = path

        with tempfile.TemporaryDirectory() as temporary:
            provider = self._provider(Path(temporary))
            session = Session()
            provider._session = session
            provider.status = Mock(return_value=SyncStatus("ouisync", True, "running"))
            provider._submit = lambda coroutine, **_kwargs: asyncio.run(coroutine)
            provider.stop = Mock()
            provider.start = Mock(return_value=SyncStatus("ouisync", True, "running"))
            provider._manual_mount_roots["abc123"] = "/old/mounts"
            result = provider.force_unmount_repository("abc123")
            self.assertTrue(result["ok"])
            self.assertEqual(session.mount_root, "/old/mounts")
            self.assertNotIn("abc123", provider._manual_mount_roots)

    def test_share_token_info_hashes_caches_resolved_tokens(self) -> None:
        class Session:
            calls = 0

            async def get_share_token_info_hash(self, *, token):
                self.calls += 1
                if token == "BAD":
                    raise ValueError("malformed")
                return f"HASH-{token}"

        with tempfile.TemporaryDirectory() as temporary:
            provider = self._provider(Path(temporary))
            session = Session()
            provider._session = session
            provider.status = Mock(return_value=SyncStatus("ouisync", True, "running"))
            provider._submit = lambda coroutine, **_kwargs: asyncio.run(coroutine)
            first = provider.share_token_info_hashes(["A", "B", "BAD", "A"])
            second = provider.share_token_info_hashes(["A", "B"])
            self.assertEqual(first, {"A": "hash-a", "B": "hash-b"})
            self.assertEqual(second, first)
            self.assertEqual(session.calls, 3)

    def test_repository_inventory_rejects_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            provider = self._provider(Path(temporary))
            result = provider.repository_inventory("abc123", "/../outside")
            self.assertTrue(result["available"])
            self.assertEqual(result["error"], "ouisync_repository_path_unsafe")

    def test_seed_repository_parent_is_registered_before_creation(self) -> None:
        class Repository:
            async def set_sync_enabled(self, *, enabled):
                self.enabled = enabled

        class Session:
            def __init__(self):
                self.directories = []
                self.repository = Repository()

            async def set_store_dirs(self, *, paths):
                self.directories = list(paths)

            async def list_repositories(self):
                return {}

            async def create_repository(self, **_kwargs):
                return self.repository

        with tempfile.TemporaryDirectory() as temporary:
            provider = self._provider(Path(temporary))
            session = Session()
            provider._session = session
            provider._store_dirs = {Path(temporary, "config", "repositories")}
            provider.status = Mock(return_value=SyncStatus("ouisync", True, "running"))
            provider._submit = lambda coroutine, **_kwargs: asyncio.run(coroutine)
            folder = Path(temporary) / "library" / "ng_provider"

            result = provider.ensure_folder_synced(str(folder), "TOKEN")

            self.assertEqual(result, (True, "ouisync_repository_enabled"))
            self.assertIn(str(folder / ".ouisync"), session.directories)
            self.assertTrue((folder / ".ouisync").is_dir())

    def test_startup_keeps_loaded_store_dirs_and_resets_publish_cache(self) -> None:
        class Session:
            def __init__(self, existing):
                self.existing = existing
                self.directories = None

            async def get_store_dirs(self):
                return list(self.existing)

            async def set_store_dirs(self, *, paths):
                self.directories = list(paths)

        with tempfile.TemporaryDirectory() as temporary:
            provider = self._provider(Path(temporary))
            lan_seed = Path(temporary, "library", "locallansync", ".ouisync")
            game = Path(temporary, "library", "0ad", ".ouisync")
            # Replacing the list would make Ouisync close these repositories.
            session = Session([str(lan_seed), str(game)])
            provider._session = session
            provider._submit = lambda coroutine, **_kwargs: asyncio.run(coroutine)
            provider._lan_publish_cache["stale"] = ("sig", {"token": "x"})

            provider._initialize_store_dirs()

            self.assertEqual(
                sorted(session.directories),
                sorted(
                    str(path.resolve())
                    for path in (lan_seed, game, Path(temporary, "config", "repositories"))
                ),
            )
            self.assertEqual(provider._lan_publish_cache, {})

    def test_lan_publication_registers_seed_directory(self) -> None:
        class Session:
            def __init__(self):
                self.directories = []

            async def set_store_dirs(self, *, paths):
                self.directories = list(paths)

        async def fake_publish(*_args, **_kwargs):
            return {"read_token": "TOKEN", "info_hash": "abc"}

        with tempfile.TemporaryDirectory() as temporary:
            provider = self._provider(Path(temporary))
            session = Session()
            provider._session = session
            provider._session_api = object()
            provider._store_dirs = {Path(temporary, "config", "repositories")}
            provider.status = Mock(return_value=SyncStatus("ouisync", True, "running"))
            provider._submit = lambda coroutine, **_kwargs: asyncio.run(coroutine)
            folder = Path(temporary) / "library" / "locallansync"
            folder.mkdir(parents=True)
            repository = folder / ".ouisync" / "lan-repository"

            with patch.object(ouisync_provider_module, "publish_lan_game", fake_publish):
                provider.publish_lan_game(str(folder), str(repository))

            self.assertIn(str(repository.parent.resolve()), session.directories)

    def test_request_timeout_cancels_pending_async_operation(self) -> None:
        async def wait_until_cancelled() -> None:
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                cancelled.set()
                raise

        with tempfile.TemporaryDirectory() as temporary:
            provider = self._provider(Path(temporary), request_timeout_seconds=0.05)
            cancelled = threading.Event()
            provider._start_event_loop()
            try:
                with self.assertRaises(TimeoutError):
                    provider._submit(wait_until_cancelled())
                self.assertTrue(cancelled.wait(timeout=1.0))
                self.assertEqual(
                    provider._submit(asyncio.sleep(0, result="ready")), "ready"
                )
            finally:
                provider._stop_event_loop()

    @unittest.skipUnless(
        platform.system() in {"Linux", "Windows"},
        "Ouisync CLI is bundled for Linux and Windows",
    )
    @unittest.skipIf(
        os.environ.get("LLNG_TEST_WINE") == "1",
        "Wine cannot install the Windows Ouisync VFS driver",
    )
    def test_supervises_bundled_cli_and_authenticates_session(self) -> None:
        root = Path(__file__).resolve().parents[2]
        import json

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

        with tempfile.TemporaryDirectory(prefix="llng-ouisync-provider-") as temporary:
            base = Path(temporary)
            provider = OuisyncSyncProvider(
                binary_path=str(root / binary),
                config_dir=str(base / "config"),
                log_path=str(base / "logs" / "ouisync.log"),
                repo_root=str(root),
                startup_timeout_seconds=15.0,
            )

            try:
                status = provider.start()
                self.assertTrue(status.running, status.last_error)
                self.assertEqual(status.provider, "ouisync")
                self.assertEqual(status.state, "running")
                self.assertIsNotNone(status.pid)
                endpoint = json.loads(
                    (base / "config" / "local_endpoint.conf").read_text(
                        encoding="utf-8"
                    )
                )
                self.assertGreater(endpoint["port"], 0)
                self.assertTrue(endpoint["auth_key"])
                self.assertEqual(provider.list_managed_folders()["folders"], [])

                publisher_provider = OuisyncSyncProvider(
                    binary_path=str(root / binary),
                    config_dir=str(base / "publisher-config"),
                    log_path=str(base / "logs" / "publisher.log"),
                    repo_root=str(root),
                    startup_timeout_seconds=15.0,
                )
                try:
                    publisher_status = publisher_provider.start()
                    self.assertTrue(
                        publisher_status.running, publisher_status.last_error
                    )
                    publisher_api = publisher_provider._session_api
                    publisher = publisher_provider._call_session(
                        "create_repository", path=str(base / "publisher.ouisync")
                    )
                    read_token = publisher_provider._submit(
                        publisher.share(access_mode=publisher_api.AccessMode.READ)
                    )
                    game_folder = base / "library" / "example-game"
                    self.assertEqual(
                        provider.ensure_folder_synced(str(game_folder), read_token),
                        (True, "ouisync_repository_enabled"),
                    )
                    self.assertEqual(
                        provider.folder_sync_status(str(game_folder)),
                        {
                            "active": True,
                            # An empty publisher snapshot has no leaf blocks: 0/0.
                            "progress_percent": 0,
                            "repository_present": True,
                        },
                    )
                    repository_hash = publisher_provider._submit(
                        publisher.get_info_hash()
                    )
                    repository_inventory = provider.repository_inventory(
                        repository_hash, "/"
                    )
                    self.assertTrue(repository_inventory["available"])
                    self.assertTrue(
                        any(
                            item["info_hash"] == repository_hash
                            for item in repository_inventory["repositories"]
                        )
                    )
                    inventory = provider.list_managed_folders()["folders"]
                    self.assertTrue(
                        any(
                            Path(item["path"])
                            == game_folder / ".ouisync" / "repository.ouisyncdb"
                            for item in inventory
                        )
                    )
                    self.assertEqual(
                        provider.remove_folder_sync(str(game_folder)),
                        (True, "ouisync_repository_paused"),
                    )
                finally:
                    publisher_provider.stop()
                self.assertEqual(provider.stop().state, "stopped")
                self.assertEqual(provider.status().state, "stopped")
            finally:
                provider.stop()


if __name__ == "__main__":
    unittest.main()
