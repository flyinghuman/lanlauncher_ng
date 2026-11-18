"""Supervise Ouisync CLI and control its authenticated local session API."""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import logging
import os
import re
import subprocess
import tempfile
import threading
import time
from dataclasses import replace
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Callable

from src.core.catalog.game_index import OuisyncRepositoryAccess
from src.core.sync.ouisync_session import load_session_api
from src.core.sync.ouisync_repository import (
    ensure_repository_synced,
    run_with_repository_mount,
)
from src.core.sync.ouisync_materializer import materialize_repository
from src.core.sync.ouisync_lan import publish_lan_game, source_signature
from src.core.sync.provider import SyncMetrics, SyncStatus

DEFAULT_OUISYNC_CACHE_SERVER = "server-ca.ouisync.net"
# Mirror status lives on a remote cache server. Keep inventory polls offline-safe
# by bounding each lookup and caching results instead of querying on every poll.
CACHE_SERVER_LOOKUP_TIMEOUT_SECONDS = 2.0
CACHE_SERVER_STATUS_TTL_SECONDS = 300.0
CACHE_SERVER_FAILURE_TTL_SECONDS = 60.0
MAX_PEERS_IN_INVENTORY = 200
_PEER_ADDRESS_RE = re.compile(r"^(quic|tcp)/(\[[0-9A-Fa-f:.]+\]|[0-9.]+):([0-9]{1,5})$")


def normalize_peer_address(value: object) -> str:
    """Return a canonical Ouisync peer address (``quic/<ip>:<port>``) or raise.

    Ouisync accepts only literal IP socket addresses, not host names. A bare
    ``<ip>:<port>`` defaults to QUIC, which is the transport LLNG binds.
    """
    text = str(value or "").strip()
    if text and "/" not in text:
        text = f"quic/{text}"
    match = _PEER_ADDRESS_RE.fullmatch(text)
    if match is None:
        raise ValueError("ouisync_peer_address_invalid")
    protocol, host, port_text = match.groups()
    try:
        address = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        raise ValueError("ouisync_peer_address_invalid") from None
    port = int(port_text)
    if (
        not 1 <= port <= 65535
        or address.is_unspecified
        or address.is_multicast
        or (address.version == 4) != (not host.startswith("["))
    ):
        raise ValueError("ouisync_peer_address_invalid")
    rendered = f"[{address}]" if address.version == 6 else str(address)
    return f"{protocol}/{rendered}:{port}"


def _peer_payload(peer: Any, user_provided: set[str]) -> dict[str, Any]:
    addr = str(getattr(peer, "addr", "") or "")
    protocol, _, address = addr.partition("/")
    source = getattr(peer, "source", None)
    state_name = type(getattr(peer, "state", None)).__name__
    stats = getattr(peer, "stats", None)

    def stat(name: str) -> int:
        return max(0, int(getattr(stats, name, 0) or 0))

    return {
        "addr": addr,
        "protocol": protocol if address else "",
        "address": address or addr,
        "source": str(getattr(source, "name", source or "")).lower(),
        "state": state_name.rsplit("_", 1)[-1].lower() if "_" in state_name else "",
        "user_provided": addr in user_provided,
        "bytes_tx": stat("bytes_tx"),
        "bytes_rx": stat("bytes_rx"),
        "throughput_tx": stat("throughput_tx"),
        "throughput_rx": stat("throughput_rx"),
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class OuisyncSyncProvider:
    """Run the Ouisync CLI outside LLNG and keep one async session connection."""

    def __init__(
        self,
        *,
        binary_path: str,
        config_dir: str,
        log_path: str,
        repo_root: str = ".",
        startup_timeout_seconds: float = 15.0,
        request_timeout_seconds: float = 5.0,
        poll_interval_seconds: float = 0.1,
        process_factory: Callable[..., subprocess.Popen] = subprocess.Popen,
    ) -> None:
        self._repo_root = Path(repo_root).expanduser().resolve(strict=False)
        self._binary_path = self._resolve_path(binary_path)
        self._config_dir = self._resolve_path(config_dir)
        self._log_path = self._resolve_path(log_path)
        self._startup_timeout_seconds = max(1.0, float(startup_timeout_seconds))
        self._request_timeout_seconds = max(0.1, float(request_timeout_seconds))
        self._poll_interval_seconds = max(0.01, float(poll_interval_seconds))
        self._process_factory = process_factory
        self._process: subprocess.Popen | None = None
        self._process_log: Any = None
        self._session: Any = None
        self._session_api: Any = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_thread: threading.Thread | None = None
        self._lock = threading.RLock()
        self._store_dirs_lock = threading.RLock()
        self._store_dirs: set[Path] = set()
        self._desired_running = False
        self._last_error = ""
        self._materialization_lock = threading.RLock()
        self._materializations: dict[str, dict[str, Any]] = {}
        self._repository_mount_lock = threading.Lock()
        self._manual_mount_roots: dict[str, str | None] = {}
        self._cache_server_status: dict[str, tuple[bool | None, float]] = {}
        self._token_info_hashes: dict[str, str] = {}
        # info_hash -> (present, total) block counts at which the current snapshot was
        # verified readable despite Ouisync's stalled block accounting.
        self._verified_progress: dict[str, tuple[int, int]] = {}
        self._lan_publish_lock = threading.RLock()
        self._lan_publish_cache: dict[str, tuple[str, dict[str, str]]] = {}
        self._network_peer_addrs: tuple[str, ...] = ()

    def _resolved_binary_path(self) -> Path:
        return self._binary_path

    def _resolve_path(self, value: str) -> Path:
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = self._repo_root / path
        return path.resolve(strict=False)

    def _start_event_loop(self) -> None:
        loop = asyncio.new_event_loop()
        ready = threading.Event()

        def run_loop() -> None:
            asyncio.set_event_loop(loop)
            ready.set()
            loop.run_forever()
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(
                    asyncio.gather(*pending, return_exceptions=True)
                )
            loop.close()

        thread = threading.Thread(
            target=run_loop,
            name="llng-ouisync-session",
            daemon=True,
        )
        thread.start()
        if not ready.wait(timeout=2.0):
            loop.call_soon_threadsafe(loop.stop)
            thread.join(timeout=2.0)
            raise RuntimeError("ouisync_session_loop_start_failed")
        self._loop = loop
        self._loop_thread = thread

    def _submit(self, coroutine: Any, *, timeout: float | None = None) -> Any:
        loop = self._loop
        if loop is None or loop.is_closed():
            coroutine.close()
            raise RuntimeError("ouisync_session_unavailable")
        future = asyncio.run_coroutine_threadsafe(coroutine, loop)
        try:
            effective_timeout = (
                self._request_timeout_seconds if timeout is None else timeout
            )
            return future.result(timeout=effective_timeout)
        except TimeoutError:
            future.cancel()
            raise

    def _stop_event_loop(self) -> None:
        loop = self._loop
        thread = self._loop_thread
        self._loop = None
        self._loop_thread = None
        if loop is not None and not loop.is_closed():
            loop.call_soon_threadsafe(loop.stop)
        if thread is not None and thread.is_alive():
            thread.join(timeout=3.0)

    def _endpoint_is_ready(self) -> bool:
        endpoint = self._config_dir / "local_endpoint.conf"
        try:
            payload = json.loads(endpoint.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return False
        return (
            isinstance(payload, dict)
            and isinstance(payload.get("port"), int)
            and payload["port"] > 0
            and isinstance(payload.get("auth_key"), str)
            and len(payload["auth_key"]) >= 32
        )

    def _start_process(self) -> None:
        binary_path = self._resolved_binary_path()
        if not binary_path.is_file():
            raise FileNotFoundError("ouisync_binary_missing")
        if os.name != "nt" and not os.access(binary_path, os.X_OK):
            raise PermissionError("ouisync_binary_not_executable")

        self._config_dir.mkdir(parents=True, exist_ok=True)
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        self._process_log = self._log_path.open("a", encoding="utf-8", errors="replace")
        command = [
            str(binary_path),
            "--config-dir",
            str(self._config_dir.resolve()),
            "start",
        ]
        try:
            self._process = self._process_factory(
                command,
                cwd=str(self._repo_root.resolve()),
                stdin=subprocess.DEVNULL,
                stdout=self._process_log,
                stderr=subprocess.STDOUT,
                shell=False,
                creationflags=(
                    getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
                ),
            )
        except Exception:
            self._close_process_log()
            raise

    def _close_process_log(self) -> None:
        handle = self._process_log
        self._process_log = None
        if handle is not None:
            try:
                handle.close()
            except OSError:
                pass

    def _terminate_process(self) -> None:
        process = self._process
        self._process = None
        if process is not None and process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                process.kill()
                try:
                    process.wait(timeout=3.0)
                except subprocess.TimeoutExpired:
                    logging.getLogger(__name__).warning(
                        "ouisync_process_shutdown_timeout"
                    )
            except OSError as exc:
                logging.getLogger(__name__).warning(
                    "ouisync_process_shutdown_failed error=%s", exc
                )
        self._close_process_log()

    def start(self) -> SyncStatus:
        with self._lock:
            self._desired_running = True
            current = self.status()
            if current.running:
                return current
            self._close_session()
            self._terminate_process()
            self._stop_event_loop()
            self._session_api = None
            self._last_error = ""
            try:
                self._start_event_loop()
                self._session_api = load_session_api()
                self._start_process()
                deadline = time.monotonic() + self._startup_timeout_seconds
                last_error = "ouisync_endpoint_not_ready"
                while time.monotonic() < deadline:
                    process = self._process
                    if process is None or process.poll() is not None:
                        returncode = process.returncode if process is not None else None
                        last_error = f"ouisync_process_exited:{returncode}"
                        break
                    if self._endpoint_is_ready():
                        try:
                            self._session = self._submit(
                                self._session_api.connect(self._config_dir),
                                timeout=min(2.0, self._request_timeout_seconds),
                            )
                            self._initialize_store_dirs()
                            self._submit(
                                self._session.bind_network(addrs=["quic/0.0.0.0:0"]),
                                timeout=self._request_timeout_seconds,
                            )
                            self._submit(
                                self._session.set_local_discovery_enabled(enabled=True),
                                timeout=self._request_timeout_seconds,
                            )
                            self._last_error = ""
                            return self.status()
                        except (
                            Exception
                        ) as exc:  # endpoint file may precede socket readiness
                            last_error = (
                                f"ouisync_session_connect_failed:{type(exc).__name__}"
                            )
                    time.sleep(self._poll_interval_seconds)
                self._last_error = last_error
                self._terminate_process()
                self._stop_event_loop()
                self._session_api = None
                return SyncStatus(
                    provider="ouisync",
                    running=False,
                    state="failed",
                    last_error=self._last_error,
                )
            except Exception as exc:  # noqa: BLE001
                self._last_error = self._error_key(exc)
                logging.getLogger(__name__).warning(
                    "ouisync_start_failed error=%s", self._last_error
                )
                self._close_session()
                self._terminate_process()
                self._stop_event_loop()
                self._session_api = None
                return SyncStatus(
                    provider="ouisync",
                    running=False,
                    state="failed",
                    last_error=self._last_error,
                )

    def _error_key(self, error: Exception) -> str:
        text = str(error or "").strip()
        if text.startswith("ouisync_"):
            return text.split(":", 1)[0]
        if isinstance(error, FileNotFoundError):
            return "ouisync_binary_missing"
        if isinstance(error, PermissionError):
            return "ouisync_binary_not_executable"
        return f"ouisync_error:{type(error).__name__}"

    def _close_session(self) -> None:
        session = self._session
        session_api = self._session_api
        self._session = None
        if session is not None and session_api is not None and self._loop is not None:
            try:
                self._submit(
                    session_api.close(session),
                    timeout=min(2.0, self._request_timeout_seconds),
                )
            except Exception as exc:  # noqa: BLE001
                logging.getLogger(__name__).debug(
                    "ouisync_session_close_failed error=%s", type(exc).__name__
                )

    def stop(self) -> SyncStatus:
        with self._lock:
            self._desired_running = False
            shutdown_deadline = time.monotonic() + 2.0
            with self._materialization_lock:
                jobs = list(self._materializations.values())
            for job in jobs:
                job["cancelled"].set()
            for job in jobs:
                thread = job.get("thread")
                if isinstance(thread, threading.Thread) and thread.is_alive():
                    thread.join(timeout=max(0.0, shutdown_deadline - time.monotonic()))

            mount_lock_acquired = self._repository_mount_lock.acquire(
                timeout=max(0.0, shutdown_deadline - time.monotonic())
            )
            if not mount_lock_acquired:
                logging.getLogger(__name__).warning(
                    "ouisync_mount_shutdown_forced"
                )
            try:
                if mount_lock_acquired:
                    self._close_session()
                # On Windows terminate() forcefully ends the supervised child. Do
                # this even when an install/mount operation still owns the lock.
                self._terminate_process()
                self._stop_event_loop()
                self._session_api = None
                self._last_error = ""
            finally:
                if mount_lock_acquired:
                    self._repository_mount_lock.release()
            return SyncStatus(provider="ouisync", running=False, state="stopped")

    def start_game_materialization(
        self,
        access: Any,
        game_directory: str,
        repository_path: str | None = None,
    ) -> tuple[bool, str]:
        """Start syncing one signed Ouisync repository without materializing its files."""
        game_id = str(getattr(access, "game_id", "") or "").strip()
        if not game_id or not str(getattr(access, "read_token", "") or ""):
            return False, "ouisync_repository_token_missing"
        if self.status().state != "running" or self._session is None:
            return False, "ouisync_session_unavailable"
        if isinstance(access, OuisyncRepositoryAccess) and not access.peer_addrs:
            with self._lock:
                peer_addrs = self._network_peer_addrs
            if peer_addrs:
                access = replace(access, peer_addrs=peer_addrs)
        target_repository = (
            Path(repository_path)
            if repository_path
            else self._repository_path(game_directory)
        )
        try:
            self._register_store_dir(target_repository.parent)
        except Exception as exc:  # noqa: BLE001
            return False, self._error_key(exc)
        with self._materialization_lock:
            existing = self._materializations.get(game_id)
            if existing and existing["thread"].is_alive():
                return True, "ouisync_repository_syncing"
            cancelled = threading.Event()
            state: dict[str, Any] = {
                "phase": "queued",
                "completed": 0,
                "total": 0,
                "error": "",
                "cancelled": cancelled,
            }
            self._materializations[game_id] = state

            def report(phase: str, completed: int, total: int) -> None:
                with self._materialization_lock:
                    state.update(
                        phase=phase,
                        completed=max(0, int(completed)),
                        total=max(0, int(total)),
                    )

            def run() -> None:
                try:
                    state["phase"] = "syncing"

                    async def sync() -> None:
                        repository = await ensure_repository_synced(
                            session=self._session,
                            access=access,
                            repository_path=target_repository,
                            cancelled=cancelled,
                            progress=report,
                        )
                        await self._remember_verified_progress(repository)

                    self._submit(sync(), timeout=24 * 60 * 60)
                except (Exception, asyncio.CancelledError) as exc:  # noqa: BLE001 - stable provider state
                    state["phase"] = "failed"
                    if isinstance(exc, asyncio.CancelledError) or cancelled.is_set():
                        state["phase"] = "cancelled"
                    else:
                        state["error"] = (
                            str(exc)
                            if str(exc).startswith("ouisync_")
                            else "ouisync_repository_sync_failed"
                        )
                        logging.getLogger(__name__).warning(
                            "ouisync_repository_sync_failed game_id=%s error=%s",
                            game_id,
                            type(exc).__name__,
                        )
                else:
                    state["phase"] = "complete"
                finally:
                    if cancelled.is_set() and state["phase"] != "complete":
                        state["phase"] = "cancelled"

            thread = threading.Thread(
                target=run,
                name=f"llng-ouisync-materialize-{game_id}",
                daemon=True,
            )
            state["thread"] = thread
            thread.start()
        return True, "ouisync_repository_syncing"

    def start_repository_materialization(
        self,
        access: OuisyncRepositoryAccess,
        folder_path: str,
        *,
        materialized_directory: str,
        marker_paths: tuple[str, ...] = (
            "update/index.json",
            "update/update-manifest.json",
            "update/trusted-publishers.json",
        ),
    ) -> tuple[bool, str]:
        """Copy a completed repository snapshot to ordinary files when its marker changes."""
        game_id = str(getattr(access, "game_id", "") or "").strip()
        if not game_id or not str(getattr(access, "read_token", "") or ""):
            return False, "ouisync_repository_token_missing"
        if self.status().state != "running" or self._session is None:
            return False, "ouisync_session_unavailable"
        repository_path = self._repository_path(folder_path)
        destination = Path(materialized_directory).expanduser().resolve(strict=False)
        try:
            self._register_store_dir(repository_path.parent)
        except Exception as exc:  # noqa: BLE001
            return False, self._error_key(exc)

        with self._materialization_lock:
            existing = self._materializations.get(game_id)
            if existing and existing["thread"].is_alive():
                return True, "ouisync_repository_syncing"
            cancelled = threading.Event()
            state: dict[str, Any] = {
                "phase": "queued",
                "completed": 0,
                "total": 0,
                "error": "",
                "cancelled": cancelled,
            }
            self._materializations[game_id] = state

            def report(phase: str, completed: int, total: int) -> None:
                with self._materialization_lock:
                    state.update(
                        phase=phase,
                        completed=max(0, int(completed)),
                        total=max(0, int(total)),
                    )

            def run() -> None:
                try:
                    state["phase"] = "syncing"

                    async def reconcile() -> bool:
                        repository = await ensure_repository_synced(
                            session=self._session,
                            access=access,
                            repository_path=repository_path,
                            cancelled=cancelled,
                            progress=report,
                        )
                        await self._remember_verified_progress(repository)
                        if cancelled.is_set():
                            raise asyncio.CancelledError
                        normalized_markers = tuple(
                            str(marker or "").replace("\\", "/")
                            for marker in marker_paths
                        )
                        if not normalized_markers or any(
                            not marker
                            or marker.startswith("/")
                            or any(part in {"", ".", ".."} for part in marker.split("/"))
                            for marker in normalized_markers
                        ):
                            raise ValueError("ouisync_repository_entry_unsafe")
                        destination.mkdir(parents=True, exist_ok=True)
                        with tempfile.TemporaryDirectory(
                            prefix=".llng-ng-provider-check-", dir=str(destination)
                        ) as temporary:
                            repository_path_name = await repository.get_path()
                            staged_markers: dict[str, Path] = {}
                            local_markers: dict[str, Path] = {}
                            for marker in normalized_markers:
                                if not await repository.file_exists(path=f"/{marker}"):
                                    if marker == "update/index.json":
                                        raise ValueError(
                                            "ouisync_repository_marker_missing"
                                        )
                                    continue
                                marker_parts = marker.split("/")
                                marker_directory = Path(temporary).joinpath(
                                    *marker_parts[:-1]
                                )
                                marker_directory.mkdir(parents=True, exist_ok=True)
                                await self._session.copy(
                                    src_repo=repository_path_name,
                                    src_path=f"/{marker}",
                                    dst_repo=None,
                                    dst_path=str(marker_directory),
                                )
                                staged_marker = marker_directory / marker_parts[-1]
                                if not staged_marker.is_file():
                                    raise ValueError(
                                        "ouisync_repository_marker_missing"
                                    )
                                staged_markers[marker] = staged_marker
                                local_markers[marker] = destination.joinpath(
                                    *marker_parts
                                )
                            if "update/index.json" not in staged_markers:
                                raise ValueError("ouisync_repository_marker_missing")
                            try:
                                materialized_names = json.loads(
                                    (destination / ".llng-materialized.json").read_text(
                                        encoding="utf-8"
                                    )
                                )
                            except (OSError, UnicodeError, json.JSONDecodeError):
                                materialized_names = None
                            repository_names = sorted(
                                str(entry.name)
                                for entry in await repository.read_directory(path="/")
                            )
                            markers_unchanged = all(
                                local.is_file()
                                and not local.is_symlink()
                                and local.parent.resolve(strict=False).is_relative_to(
                                    destination
                                )
                                and _sha256_file(staged_markers[marker])
                                == _sha256_file(local)
                                for marker, local in local_markers.items()
                            )
                            markers_unchanged = markers_unchanged and all(
                                not destination.joinpath(*marker.split("/")).exists()
                                for marker in normalized_markers
                                if marker not in staged_markers
                            )
                            if (
                                markers_unchanged
                                and isinstance(materialized_names, list)
                                and all(isinstance(name, str) for name in materialized_names)
                                and sorted(materialized_names) == repository_names
                            ):
                                report("complete", 1, 1)
                                logging.getLogger(__name__).debug(
                                    "ouisync_repository_materialization_current game_id=%s",
                                    game_id,
                                )
                                return False

                        report("materializing", 0, 0)
                        await materialize_repository(
                            session=self._session,
                            access=access,
                            game_directory=destination,
                            materialized_directory=destination,
                            repository_path=repository_path,
                            cancelled=cancelled,
                            progress=report,
                        )
                        return True

                    copied = self._submit(
                        reconcile(), timeout=24 * 60 * 60
                    )
                except (Exception, asyncio.CancelledError) as exc:  # noqa: BLE001
                    state["phase"] = "failed"
                    if isinstance(exc, asyncio.CancelledError) or cancelled.is_set():
                        state["phase"] = "cancelled"
                    else:
                        state["error"] = (
                            str(exc)
                            if str(exc).startswith("ouisync_")
                            else "ouisync_repository_materialization_failed"
                        )
                        logging.getLogger(__name__).warning(
                            "ouisync_repository_materialization_failed game_id=%s error=%s",
                            game_id,
                            type(exc).__name__,
                        )
                else:
                    state["phase"] = "complete"
                    if copied:
                        logging.getLogger(__name__).info(
                            "ouisync_repository_materialized game_id=%s path=%s",
                            game_id,
                            destination,
                        )
                finally:
                    if cancelled.is_set() and state["phase"] != "complete":
                        state["phase"] = "cancelled"

            thread = threading.Thread(
                target=run,
                name=f"llng-ouisync-materialize-{game_id}",
                daemon=True,
            )
            state["thread"] = thread
            thread.start()
        return True, "ouisync_repository_syncing"

    def run_with_game_repository_mounted(
        self,
        access: Any,
        repository_path: str,
        action: Callable[[Path], Any],
        *,
        cancelled: threading.Event | None = None,
        progress: Callable[[str, int, int], None] | None = None,
    ) -> Any:
        """Mount one selected repository for an operation, then always unmount it."""
        if self.status().state != "running" or self._session is None:
            raise RuntimeError("ouisync_session_unavailable")
        if isinstance(access, OuisyncRepositoryAccess) and not access.peer_addrs:
            with self._lock:
                peer_addrs = self._network_peer_addrs
            if peer_addrs:
                access = replace(access, peer_addrs=peer_addrs)
        config_dir = self._config_dir
        mount_root = config_dir / "mounts"
        with self._repository_mount_lock:
            return self._submit(
                run_with_repository_mount(
                    session=self._session,
                    access=access,
                    repository_path=Path(repository_path),
                    mount_root=mount_root,
                    action=action,
                    cancelled=cancelled,
                    progress=progress,
                ),
                timeout=24 * 60 * 60,
            )

    def delete_game_repository(self, repository_path: str) -> tuple[bool, str]:
        """Delete only the selected local replica and its Ouisync database files."""
        if self.status().state != "running" or self._session is None:
            return False, "ouisync_session_unavailable"
        for job in list(self._materializations.values()):
            job["cancelled"].set()
            thread = job.get("thread")
            if isinstance(thread, threading.Thread) and thread.is_alive():
                thread.join(timeout=10.0)
                if thread.is_alive():
                    return False, "ouisync_repository_busy"
        path = Path(repository_path).expanduser().resolve(strict=False)
        try:

            async def delete() -> bool:
                repository = await self._find_repository(path=path)
                if repository is None:
                    return False
                name = await repository.get_short_name()
                await self._session.delete_repository_by_name(name=name)
                return True

            with self._repository_mount_lock:
                deleted = self._submit(delete())
            if not deleted:
                for candidate in (path, Path(f"{path}.ouisyncdb")):
                    candidate.unlink(missing_ok=True)
                    for suffix in ("-wal", "-shm"):
                        Path(f"{candidate}{suffix}").unlink(missing_ok=True)
            return True, "ouisync_repository_removed"
        except Exception as exc:  # noqa: BLE001 - keep filesystem failures localized
            return False, self._error_key(exc)

    def game_materialization_status(self, game_id: str) -> dict[str, Any]:
        with self._materialization_lock:
            state = self._materializations.get(str(game_id or "").strip())
            if state is None:
                return {"phase": "idle", "completed": 0, "total": 0, "error": ""}
            total = int(state.get("total", 0) or 0)
            completed = int(state.get("completed", 0) or 0)
            percent = (
                100
                if state.get("phase") == "complete"
                else (min(99, int(completed * 100 / total)) if total else 0)
            )
            return {
                "phase": str(state.get("phase", "idle")),
                "completed": completed,
                "total": total,
                "progress_percent": percent,
                "error": str(state.get("error", "")),
            }

    def cancel_game_materialization(self, game_id: str) -> bool:
        with self._materialization_lock:
            state = self._materializations.get(str(game_id or "").strip())
            if state is None:
                return False
            state["cancelled"].set()
            return True

    def status(self) -> SyncStatus:
        with self._lock:
            process = self._process
            if process is not None and process.poll() is not None:
                if self._desired_running:
                    self._last_error = f"ouisync_process_exited:{process.returncode}"
                    return SyncStatus(
                        provider="ouisync",
                        running=False,
                        state="failed",
                        last_error=self._last_error,
                    )
                return SyncStatus(provider="ouisync", running=False, state="stopped")
            if process is not None and self._session is not None:
                return SyncStatus(
                    provider="ouisync",
                    running=True,
                    state="running",
                    pid=process.pid,
                )
            state = (
                "starting"
                if self._desired_running and process is not None
                else "stopped"
            )
            return SyncStatus(
                provider="ouisync",
                running=False,
                state=state,
                pid=process.pid if process is not None else None,
                last_error=self._last_error,
            )

    def _call_session(self, method: str, *args: Any, **kwargs: Any) -> Any:
        session = self._session
        if session is None:
            raise RuntimeError("ouisync_session_unavailable")
        function = getattr(session, method)
        return self._submit(function(*args, **kwargs))

    def _initialize_store_dirs(self) -> None:
        """Adopt the store dirs Ouisync loaded at startup and add LLNG's own.

        Ouisync closes every repository whose directory drops out of the store
        list (``session_set_store_dirs``). Replacing the persisted list would
        therefore close library repositories the CLI just reopened, such as LAN
        seeds and installed games, until some LLNG flow touched them again.
        """
        session = self._session
        if session is None:
            raise RuntimeError("ouisync_session_unavailable")
        store_dir = self._config_dir / "repositories"
        store_dir.mkdir(parents=True, exist_ok=True)
        get_store_dirs = getattr(session, "get_store_dirs", None)
        existing = (
            self._submit(get_store_dirs(), timeout=self._request_timeout_seconds)
            if callable(get_store_dirs)
            else []
        )
        with self._store_dirs_lock:
            self._store_dirs = {
                Path(str(path)).expanduser().resolve(strict=False)
                for path in existing or []
                if str(path).strip()
            } | {store_dir.resolve(strict=False)}
            self._set_store_dirs()
        # A new session has no repositories opened by earlier publications.
        with self._lan_publish_lock:
            self._lan_publish_cache.clear()

    def _set_store_dirs(self) -> None:
        session = self._session
        if session is None:
            raise RuntimeError("ouisync_session_unavailable")
        with self._store_dirs_lock:
            paths = sorted(str(path) for path in self._store_dirs)
            self._submit(
                session.set_store_dirs(paths=paths),
                timeout=self._request_timeout_seconds,
            )

    def _register_store_dir(self, path: Path) -> None:
        store_dir = path.expanduser().resolve(strict=False)
        store_dir.mkdir(parents=True, exist_ok=True)
        with self._store_dirs_lock:
            if store_dir in self._store_dirs:
                return
            self._store_dirs.add(store_dir)
            try:
                self._set_store_dirs()
            except Exception:
                self._store_dirs.discard(store_dir)
                raise

    def store_directories(self) -> list[str]:
        with self._store_dirs_lock:
            return sorted(str(path) for path in self._store_dirs)

    def network_listener_addrs(self) -> list[str]:
        """Return bound Ouisync listener addresses for authenticated LAN pairing."""
        values = self._call_session("get_local_listener_addrs")
        if not isinstance(values, list):
            return []
        return [value for value in values if isinstance(value, str)][:4]

    def add_network_peers(self, addrs: list[str]) -> None:
        """Add listener addresses supplied by a paired LAN peer."""
        safe = tuple(
            dict.fromkeys(
                value
                for value in addrs
                if isinstance(value, str)
                and value
                and not any(char.isspace() for char in value)
            )
        )[:64]
        with self._lock:
            self._network_peer_addrs = safe
        if safe:
            if self._session is not None:
                self._call_session("add_user_provided_peers", addrs=list(safe))

    def metrics(self) -> SyncMetrics:
        try:
            stats = self._call_session("get_network_stats")
        except Exception:
            return SyncMetrics(download_bps=0, upload_bps=0)
        return SyncMetrics(
            download_bps=max(0, int(getattr(stats, "throughput_rx", 0) or 0)),
            upload_bps=max(0, int(getattr(stats, "throughput_tx", 0) or 0)),
        )

    def _repository_path(self, folder_path: str) -> Path:
        root = Path(folder_path).expanduser().resolve(strict=False)
        if Path(f"{root}.ouisyncdb").exists():
            return root
        if root.name == "repository.ouisync" or root.suffix == ".ouisync":
            return root.with_suffix("")
        content = root / ".ouisync"
        global_path = content / "repository"
        if global_path.exists() or Path(f"{global_path}.ouisyncdb").exists():
            return global_path
        private_path = content / "lan-repository"
        if private_path.exists() or Path(f"{private_path}.ouisyncdb").exists():
            return private_path
        return global_path

    async def _find_repository(
        self, path: Path | None = None, info_hash: str = ""
    ) -> Any:
        repositories = await self._session.list_repositories()
        for repository in repositories.values():
            if path is not None:
                repo_path = await repository.get_path()
                resolved_repo_path = Path(repo_path).resolve(strict=False)
                if resolved_repo_path in {path, Path(f"{path}.ouisyncdb")}:
                    return repository
            if info_hash:
                repo_hash = await repository.get_info_hash()
                if str(repo_hash).lower() == info_hash.lower():
                    return repository
        if path is not None and Path(f"{path}.ouisyncdb").is_file():
            return await self._session.open_repository(path=str(path))
        return None

    def ensure_folder_synced(self, folder_path: str, secret: str) -> tuple[bool, str]:
        token = str(secret or "").strip()
        if not token:
            return False, "ouisync_repository_token_missing"
        repository_path = self._repository_path(folder_path)
        try:
            self._register_store_dir(repository_path.parent)

            async def ensure() -> None:
                repository = await self._find_repository(path=repository_path)
                if repository is None:
                    repository = await self._session.create_repository(
                        path=str(repository_path),
                        token=token,
                        sync_enabled=True,
                        dht_enabled=True,
                        pex_enabled=True,
                    )
                else:
                    await repository.set_sync_enabled(enabled=True)

            self._submit(ensure())
            return True, "ouisync_repository_enabled"
        except Exception as exc:  # noqa: BLE001
            logging.getLogger(__name__).warning(
                "ouisync_repository_enable_failed error=%s", self._error_key(exc)
            )
            return False, self._error_key(exc)

    def remove_folder_sync(self, folder_path: str) -> tuple[bool, str]:
        repository_path = self._repository_path(folder_path)
        try:

            async def disable() -> bool:
                repository = await self._find_repository(path=repository_path)
                if repository is None:
                    return False
                await repository.set_sync_enabled(enabled=False)
                await repository.close()
                return True

            found = self._submit(disable())
            return (
                (True, "ouisync_repository_paused")
                if found
                else (False, "ouisync_repository_not_found")
            )
        except Exception as exc:  # noqa: BLE001
            return False, self._error_key(exc)

    def remove_folder_sync_by_secret(self, secret: str) -> tuple[bool, str]:
        token = str(secret or "").strip()
        if not token:
            return False, "ouisync_repository_token_missing"
        try:

            async def disable() -> bool:
                info_hash = await self._session.get_share_token_info_hash(token=token)
                repository = await self._find_repository(info_hash=info_hash)
                if repository is None:
                    return False
                await repository.set_sync_enabled(enabled=False)
                await repository.close()
                return True

            found = self._submit(disable())
            return (
                (True, "ouisync_repository_paused")
                if found
                else (False, "ouisync_repository_not_found")
            )
        except Exception as exc:  # noqa: BLE001
            return False, self._error_key(exc)

    def publish_lan_game(
        self, folder_path: str, repository_path: str | None = None
    ) -> dict[str, str]:
        """Seed a selected private LAN game and mint its read-only share token."""
        if self.status().state != "running" or self._session is None:
            raise RuntimeError("ouisync_session_unavailable")
        try:
            cache_key = str(Path(folder_path).expanduser().resolve(strict=True))
            if repository_path:
                cache_key = (
                    f"{cache_key}\0{Path(repository_path).resolve(strict=False)}"
                )
            signature = source_signature(folder_path)
            # Register the seed's directory so Ouisync reopens it after a restart.
            self._register_store_dir(
                Path(repository_path).parent
                if repository_path
                else Path(folder_path) / ".ouisync"
            )
            with self._lan_publish_lock:
                cached = self._lan_publish_cache.get(cache_key)
                if cached is not None and cached[0] == signature:
                    return dict(cached[1])
                with self._repository_mount_lock:
                    capability = self._submit(
                        publish_lan_game(
                            self._session,
                            self._session_api,
                            folder_path,
                            repository_path=repository_path,
                            mount_root=str(self._config_dir / "mounts"),
                        )
                    )
                self._lan_publish_cache[cache_key] = (signature, dict(capability))
            return capability
        except Exception as exc:  # noqa: BLE001 - callers map this to a stable API key
            self._last_error = self._error_key(exc)
            raise RuntimeError(self._last_error) from exc

    def reconcile_lan_shared_games(self, folder_paths: list[str]) -> None:
        """Keep active seeds for published folders and pause repositories that were unshared."""
        if self.status().state != "running" or self._session is None:
            raise RuntimeError("ouisync_session_unavailable")
        desired = {
            str(Path(path).expanduser().resolve(strict=False)) for path in folder_paths
        }

        async def reconcile() -> None:
            for repository in (await self._session.list_repositories()).values():
                path = Path(await repository.get_path()).resolve(strict=False)
                if path.parent.name != ".ouisync" or path.name not in {
                    "lan-repository",
                    "lan-repository.ouisyncdb",
                }:
                    continue
                base_path = (
                    path.with_suffix("") if path.suffix == ".ouisyncdb" else path
                )
                should_sync = str(base_path) in desired
                if await repository.is_sync_enabled() != should_sync:
                    await repository.set_sync_enabled(enabled=should_sync)

        self._submit(reconcile())

    def folder_sync_status(self, folder_path: str) -> dict[str, int | bool | str]:
        repository_path = self._repository_path(folder_path)
        try:

            async def get_status() -> dict[str, int | bool | str]:
                repository = await self._find_repository(path=repository_path)
                if repository is None:
                    return {
                        "active": False,
                        "progress_percent": 0,
                        "repository_present": False,
                    }
                enabled = await repository.is_sync_enabled()
                progress = await repository.get_sync_progress()
                total = max(0, int(progress.total or 0))
                value = max(0, int(progress.value or 0))
                # 0/0 means no snapshot index has arrived yet, not "complete".
                percent = min(100, int(value * 100 / total)) if total else 0
                return {
                    "active": bool(enabled),
                    "progress_percent": percent,
                    "repository_present": True,
                }

            return self._submit(get_status())
        except Exception:
            return {"active": False, "progress_percent": 0, "repository_present": False}

    def list_managed_folders(self) -> dict[str, Any]:
        try:

            async def inventory() -> list[dict[str, Any]]:
                result = []
                repositories = await self._session.list_repositories()
                for repository in repositories.values():
                    path = await repository.get_path()
                    name = await repository.get_short_name()
                    progress = await repository.get_sync_progress()
                    enabled = await repository.is_sync_enabled()
                    total = max(0, int(progress.total or 0))
                    value = max(0, int(progress.value or 0))
                    percent = min(100, int(value * 100 / total)) if total else 0
                    result.append(
                        {
                            "folder_id": await repository.get_info_hash(),
                            "label": name,
                            "path": path,
                            "shared": bool(enabled),
                            "active": bool(enabled),
                            "progress_percent": percent,
                        }
                    )
                return result

            folders = self._submit(inventory())
            return {"root_path": str(self._config_dir), "folders": folders}
        except Exception:
            return {"root_path": str(self._config_dir), "folders": []}

    async def _remember_verified_progress(self, repository: Any) -> None:
        """Record block counts of a snapshot accepted by read verification."""
        try:
            info_hash = str(await repository.get_info_hash()).lower()
            sync_progress = await repository.get_sync_progress()
        except Exception:  # noqa: BLE001 - display hint only
            return
        value = max(0, int(sync_progress.value or 0))
        total = max(0, int(sync_progress.total or 0))
        if total and value < total:
            self._verified_progress[info_hash] = (value, total)
        else:
            self._verified_progress.pop(info_hash, None)

    async def _cached_mirror_status(self, info_hash: str, repository: Any) -> bool | None:
        """Return cached cache-server mirror state; None when the server is unreachable."""
        now = time.monotonic()
        cached = self._cache_server_status.get(info_hash)
        if cached is not None and cached[1] > now:
            return cached[0]
        try:
            value: bool | None = bool(
                await asyncio.wait_for(
                    repository.mirror_exists(host=DEFAULT_OUISYNC_CACHE_SERVER),
                    timeout=CACHE_SERVER_LOOKUP_TIMEOUT_SECONDS,
                )
            )
            ttl = CACHE_SERVER_STATUS_TTL_SECONDS
        except (Exception, asyncio.TimeoutError):  # noqa: BLE001 - offline LAN must not break inventory
            value = None
            ttl = CACHE_SERVER_FAILURE_TTL_SECONDS
        self._cache_server_status[info_hash] = (value, now + ttl)
        return value

    def repository_inventory(
        self, repository_hash: str = "", directory_path: str = "/"
    ) -> dict[str, Any]:
        """Return Ouisync repository inventory and one directory listing."""
        requested_hash = str(repository_hash or "").strip().lower()
        normalized_path = str(directory_path or "/").replace("\\", "/")
        path_parts = [part for part in normalized_path.split("/") if part]
        if (
            not normalized_path.startswith("/")
            or any(part in {".", ".."} for part in path_parts)
            or "\x00" in normalized_path
        ):
            return {
                "available": True,
                "error": "ouisync_repository_path_unsafe",
                "repositories": [],
                "network": {},
            }
        normalized_path = "/" + "/".join(path_parts)
        if self.status().state != "running" or self._session is None:
            return {
                "available": False,
                "error": "ouisync_session_unavailable",
                "repositories": [],
                "network": {},
            }

        try:

            async def inventory() -> dict[str, Any]:
                repositories = []
                all_repositories = await self._session.list_repositories()
                get_peers = getattr(self._session, "get_peers", None)
                peers = await get_peers() if callable(get_peers) else []
                for repository in all_repositories.values():
                    info_hash = str(await repository.get_info_hash()).lower()
                    selected_repository = bool(
                        requested_hash and info_hash == requested_hash
                    )
                    sync_progress = await repository.get_sync_progress()
                    stats = await repository.get_stats()
                    enabled = await repository.is_sync_enabled()
                    access_mode = await repository.get_access_mode()
                    local_path = str(await repository.get_path())
                    mount_point = await repository.get_mount_point()
                    dht_enabled = None
                    pex_enabled = None
                    if enabled:
                        dht_enabled = bool(await repository.is_dht_enabled())
                        pex_enabled = bool(await repository.is_pex_enabled())
                    cache_servers_enabled = None
                    if int(access_mode) == 2:
                        cache_servers_enabled = await self._cached_mirror_status(
                            info_hash, repository
                        )
                    label = await repository.get_short_name()
                    entries = []
                    directory_error = ""
                    if selected_repository:
                        try:
                            directory_entries = await repository.read_directory(
                                path=normalized_path
                            )
                            for entry in directory_entries[:2000]:
                                name = str(entry.name)
                                entry_path = (
                                    f"/{name}"
                                    if normalized_path == "/"
                                    else f"{normalized_path.rstrip('/')}/{name}"
                                )
                                entries.append(
                                    {
                                        "name": name,
                                        "path": entry_path,
                                        "type": "directory"
                                        if int(entry.entry_type) == 2
                                        else "file",
                                    }
                                )
                        except Exception as exc:  # noqa: BLE001
                            directory_error = self._error_key(exc)
                    repositories.append(
                        {
                            "info_hash": info_hash,
                            "label": str(label),
                            "sync_enabled": bool(enabled),
                            "local_path": local_path,
                            "mount_point": str(mount_point or ""),
                            "access_mode": str(getattr(access_mode, "name", access_mode)).lower(),
                            "settings": {
                                "dht_enabled": dht_enabled,
                                "peer_exchange_enabled": pex_enabled,
                                "cache_servers_enabled": cache_servers_enabled,
                                "cache_servers_writable": int(access_mode) == 2,
                                "available": bool(enabled),
                            },
                            "content_verified": self._verified_progress.get(info_hash)
                            == (
                                max(0, int(sync_progress.value or 0)),
                                max(0, int(sync_progress.total or 0)),
                            ),
                            "local_block_count": max(0, int(sync_progress.value or 0)),
                            "repository_block_count": max(0, int(sync_progress.total or 0)),
                            "peer_count": len(peers),
                            "connected_peer_count": sum(
                                1
                                for peer in peers
                                if type(getattr(peer, "state", None)).__name__.endswith("_Active")
                            ),
                            "bytes_tx": max(0, int(stats.bytes_tx or 0)),
                            "bytes_rx": max(0, int(stats.bytes_rx or 0)),
                            "throughput_tx": max(0, int(stats.throughput_tx or 0)),
                            "throughput_rx": max(0, int(stats.throughput_rx or 0)),
                            "directory_path": normalized_path
                            if selected_repository
                            else "",
                            "entries": entries,
                            "directory_error": directory_error,
                        }
                    )
                network = await self._session.get_network_stats()
                get_user_peers = getattr(self._session, "get_user_provided_peers", None)
                user_provided = (
                    {str(item) for item in await get_user_peers()}
                    if callable(get_user_peers)
                    else set()
                )
                get_listeners = getattr(self._session, "get_local_listener_addrs", None)
                listener_addrs = (
                    [str(item) for item in await get_listeners()][:4]
                    if callable(get_listeners)
                    else []
                )
                return {
                    "available": True,
                    "error": "",
                    "repositories": repositories,
                    # Ouisync 0.10.x exposes peers only per session, not per repository.
                    "peers": [
                        _peer_payload(peer, user_provided)
                        for peer in peers[:MAX_PEERS_IN_INVENTORY]
                    ],
                    "listener_addrs": listener_addrs,
                    "peer_count": len(peers),
                    "connected_peer_count": sum(
                        1
                        for peer in peers
                        if type(getattr(peer, "state", None)).__name__.endswith("_Active")
                    ),
                    "network": {
                        "bytes_tx": max(0, int(network.bytes_tx or 0)),
                        "bytes_rx": max(0, int(network.bytes_rx or 0)),
                        "throughput_tx": max(0, int(network.throughput_tx or 0)),
                        "throughput_rx": max(0, int(network.throughput_rx or 0)),
                    },
                }

            result = self._submit(
                inventory(), timeout=max(10.0, self._request_timeout_seconds)
            )
            if requested_hash and not any(
                item["info_hash"] == requested_hash for item in result["repositories"]
            ):
                result["error"] = "ouisync_repository_not_found"
            return result
        except Exception as exc:  # noqa: BLE001
            return {
                "available": False,
                "error": self._error_key(exc),
                "repositories": [],
                "network": {},
            }

    def update_user_provided_peer(self, action: str, address: str) -> dict[str, Any]:
        """Add or remove one manually provided peer; Ouisync persists the list itself."""
        if action not in {"add", "remove"}:
            return {"ok": False, "message": "ouisync_peer_action_invalid"}
        try:
            normalized = normalize_peer_address(address)
        except ValueError as exc:
            return {"ok": False, "message": str(exc)}
        if self.status().state != "running" or self._session is None:
            return {"ok": False, "message": "ouisync_session_unavailable"}
        method = (
            "add_user_provided_peers" if action == "add" else "remove_user_provided_peers"
        )
        try:
            self._call_session(method, addrs=[normalized])
        except Exception as exc:  # noqa: BLE001 - stable API error key
            return {"ok": False, "message": self._error_key(exc)}
        logging.getLogger(__name__).info(
            "ouisync_user_peer_updated action=%s address=%s", action, normalized
        )
        return {
            "ok": True,
            "message": "ouisync_peer_added" if action == "add" else "ouisync_peer_removed",
            "address": normalized,
        }

    def update_repository_settings(
        self, repository_hash: str, settings: dict[str, Any]
    ) -> dict[str, Any]:
        """Apply supported discovery and cache-server settings to one repository."""
        requested_hash = str(repository_hash or "").strip().lower()
        allowed = {
            "dht_enabled",
            "peer_exchange_enabled",
            "cache_servers_enabled",
        }
        if (
            not requested_hash
            or not isinstance(settings, dict)
            or not settings
            or set(settings) - allowed
            or any(type(value) is not bool for value in settings.values())
        ):
            return {"ok": False, "message": "ouisync_repository_settings_invalid"}
        if self.status().state != "running" or self._session is None:
            return {"ok": False, "message": "ouisync_session_unavailable"}

        async def update() -> dict[str, Any]:
            repositories = await self._session.list_repositories()
            repository = None
            for candidate in repositories.values():
                if str(await candidate.get_info_hash()).lower() == requested_hash:
                    repository = candidate
                    break
            if repository is None:
                return {"ok": False, "message": "ouisync_repository_not_found"}
            if not await repository.is_sync_enabled():
                return {"ok": False, "message": "ouisync_repository_sync_disabled"}
            access_mode = await repository.get_access_mode()
            if "cache_servers_enabled" in settings and int(access_mode) != 2:
                return {
                    "ok": False,
                    "message": "ouisync_cache_servers_write_required",
                }
            if "dht_enabled" in settings:
                await repository.set_dht_enabled(enabled=settings["dht_enabled"])
            if "peer_exchange_enabled" in settings:
                await repository.set_pex_enabled(
                    enabled=settings["peer_exchange_enabled"]
                )
            if "cache_servers_enabled" in settings:
                host = DEFAULT_OUISYNC_CACHE_SERVER
                exists = await repository.mirror_exists(host=host)
                if settings["cache_servers_enabled"] and not exists:
                    await repository.create_mirror(host=host)
                elif not settings["cache_servers_enabled"] and exists:
                    await repository.delete_mirror(host=host)
                self._cache_server_status.pop(requested_hash, None)
            return {
                "ok": True,
                "message": "ouisync_repository_settings_updated",
                "info_hash": requested_hash,
                "settings": {
                    "dht_enabled": bool(await repository.is_dht_enabled()),
                    "peer_exchange_enabled": bool(await repository.is_pex_enabled()),
                    "cache_servers_enabled": bool(
                        await repository.mirror_exists(
                            host=DEFAULT_OUISYNC_CACHE_SERVER
                        )
                    ),
                    "cache_servers_writable": int(access_mode) == 2,
                    "available": True,
                },
            }

        try:
            return self._submit(
                update(), timeout=max(10.0, self._request_timeout_seconds)
            )
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "message": self._error_key(exc)}

    def copy_repository_entry_to_disk(
        self, repository_hash: str, entry_path: str, game_directory: str,
        destination_directory: str = ".",
    ) -> dict[str, Any]:
        """Copy a repository entry into a safe destination under its game folder."""
        requested_hash = str(repository_hash or "").strip().lower()
        source = str(entry_path or "")
        source_path = PurePosixPath(source)
        source_windows = PureWindowsPath(source)
        destination_value = str(destination_directory or ".").replace("\\", "/")
        target = PurePosixPath(destination_value)
        target_parts = [part for part in target.parts if part not in {".", "/"}]
        if (
            not requested_hash
            or not source.startswith("/")
            or "\\" in source
            or "\x00" in source
            or source_windows.drive
            or any(part in {".", ".."} or ":" in part for part in source_path.parts)
            or target.is_absolute()
            or "\x00" in destination_value
            or any(part == ".." or ":" in part for part in target_parts)
            or (
                target_parts
                and target_parts[0].casefold() in {".ouisync", "ouisyncmount"}
            )
        ):
            return {"ok": False, "message": "ouisync_repository_entry_unsafe"}
        if self.status().state != "running" or self._session is None:
            return {"ok": False, "message": "ouisync_session_unavailable"}
        game_root = Path(game_directory).expanduser().resolve(strict=False)
        target_directory = game_root.joinpath(*target_parts)
        try:
            resolved_target = target_directory.resolve(strict=False)
            if not resolved_target.is_relative_to(game_root):
                return {"ok": False, "message": "ouisync_repository_entry_unsafe"}
            resolved_target.mkdir(parents=True, exist_ok=True)
            destination = resolved_target.resolve(strict=True)
            if not destination.is_relative_to(game_root):
                return {"ok": False, "message": "ouisync_repository_entry_unsafe"}

            async def copy_entry() -> dict[str, Any]:
                for repository in (await self._session.list_repositories()).values():
                    if str(await repository.get_info_hash()).lower() != requested_hash:
                        continue
                    await self._session.copy(
                        src_repo=await repository.get_path(),
                        src_path=source,
                        dst_repo=None,
                        dst_path=str(destination),
                    )
                    return {
                        "ok": True,
                        "message": "ouisync_repository_entry_copied",
                        "destination": str(destination / source_path.name),
                    }
                return {"ok": False, "message": "ouisync_repository_not_found"}

            with self._repository_mount_lock:
                return self._submit(copy_entry(), timeout=10 * 60)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "message": self._error_key(exc)}

    def mount_readonly_repository(
        self, repository_hash: str, game_directory: str
    ) -> dict[str, Any]:
        """Mount one read-only repository beneath <game>/ouisyncmount."""
        requested_hash = str(repository_hash or "").strip().lower()
        if not requested_hash:
            return {"ok": False, "message": "ouisync_repository_not_found"}
        if self.status().state != "running" or self._session is None:
            return {"ok": False, "message": "ouisync_session_unavailable"}
        game_root = Path(game_directory).expanduser().resolve(strict=False)
        mount_root = game_root / "ouisyncmount"
        try:
            mount_root.mkdir(parents=True, exist_ok=True)
            mount_root = mount_root.resolve(strict=True)
            if not mount_root.is_relative_to(game_root):
                return {"ok": False, "message": "ouisync_repository_entry_unsafe"}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "message": self._error_key(exc)}

        async def mount() -> dict[str, Any]:
            repositories = await self._session.list_repositories()
            selected = None
            for repo in repositories.values():
                if str(await repo.get_info_hash()).lower() == requested_hash:
                    selected = repo
                    break
            if selected is None:
                return {"ok": False, "message": "ouisync_repository_not_found"}
            access_mode = await selected.get_access_mode()
            if int(access_mode) != 1:
                return {"ok": False, "message": "ouisync_repository_read_only_required"}
            current_mount = await selected.get_mount_point()
            if current_mount and Path(current_mount).resolve(strict=False).is_relative_to(mount_root):
                return {"ok": True, "message": "ouisync_repository_mounted", "mount_point": str(current_mount)}
            for repo in repositories.values():
                if repo is not selected and await repo.get_mount_point():
                    return {"ok": False, "message": "ouisync_mount_root_busy"}
            previous_root = await self._session.get_mount_root()
            try:
                if current_mount:
                    await selected.unmount()
                await self._session.set_mount_root(path=str(mount_root))
                mounted_path = Path(await selected.mount()).resolve(strict=False)
                if not mounted_path.is_relative_to(mount_root):
                    await selected.unmount()
                    raise ValueError("ouisync_mount_path_unsafe")
                self._manual_mount_roots[requested_hash] = str(previous_root) if previous_root else None
                return {
                    "ok": True,
                    "message": "ouisync_repository_mounted",
                    "mount_point": str(mounted_path),
                }
            except Exception:
                await self._session.set_mount_root(path=previous_root)
                raise

        try:
            with self._repository_mount_lock:
                return self._submit(mount(), timeout=30)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "message": self._error_key(exc)}

    def unmount_repository(self, repository_hash: str) -> dict[str, Any]:
        requested_hash = str(repository_hash or "").strip().lower()
        if self.status().state != "running" or self._session is None:
            return {"ok": False, "message": "ouisync_session_unavailable"}

        async def unmount() -> dict[str, Any]:
            for repo in (await self._session.list_repositories()).values():
                if str(await repo.get_info_hash()).lower() != requested_hash:
                    continue
                if not await repo.get_mount_point():
                    return {"ok": True, "message": "ouisync_repository_not_mounted"}
                await repo.unmount()
                has_previous_root = requested_hash in self._manual_mount_roots
                previous_root = self._manual_mount_roots.pop(requested_hash, None)
                if has_previous_root:
                    await self._session.set_mount_root(path=previous_root)
                else:
                    await self._session.set_mount_root(
                        path=str(self._config_dir / "mounts")
                    )
                return {"ok": True, "message": "ouisync_repository_unmounted"}
            return {"ok": False, "message": "ouisync_repository_not_found"}

        try:
            with self._repository_mount_lock:
                return self._submit(unmount(), timeout=20)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "message": self._error_key(exc)}

    def force_unmount_repository(self, repository_hash: str) -> dict[str, Any]:
        """Restart Ouisync to release a stuck VFS mount with open file handles."""
        requested_hash = str(repository_hash or "").strip().lower()
        if not requested_hash or self.status().state != "running":
            return {"ok": False, "message": "ouisync_session_unavailable"}
        # A restart cancels every running repository sync, so refuse instead of
        # silently aborting unrelated game installs.
        with self._materialization_lock:
            busy = any(
                isinstance(job.get("thread"), threading.Thread)
                and job["thread"].is_alive()
                for job in self._materializations.values()
            )
        if busy:
            return {"ok": False, "message": "ouisync_force_unmount_busy"}
        previous_root = self._manual_mount_roots.get(requested_hash)
        try:
            async def clear_automount() -> None:
                for repo in (await self._session.list_repositories()).values():
                    if str(await repo.get_info_hash()).lower() == requested_hash:
                        try:
                            await repo.unmount()
                        except Exception:
                            pass
                        return

            self._submit(clear_automount(), timeout=3)
        except Exception:
            pass
        self.stop()
        status = self.start()
        if not status.running:
            # Keep the saved root so a later unmount can still restore it.
            return {"ok": False, "message": status.last_error or "ouisync_force_unmount_failed"}
        result = self.unmount_repository(requested_hash)
        if result.get("ok") and requested_hash in self._manual_mount_roots:
            # The repository came back unmounted, so unmount_repository returned
            # before restoring the session mount root; restore it explicitly.
            self._manual_mount_roots.pop(requested_hash, None)
            try:
                self._submit(self._session.set_mount_root(path=previous_root), timeout=10)
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "message": self._error_key(exc)}
        if result.get("ok"):
            return {"ok": True, "message": "ouisync_force_unmount_restarted"}
        return {"ok": False, "message": result.get("message", "ouisync_force_unmount_failed")}

    def share_token_info_hashes(self, tokens: list[str]) -> dict[str, str]:
        """Map share tokens to info hashes; hashes are deterministic, so cache them."""
        values = [str(token or "").strip() for token in tokens]
        missing = [
            value for value in dict.fromkeys(values)
            if value and value not in self._token_info_hashes
        ]
        if missing and self.status().state == "running" and self._session is not None:

            async def resolve() -> dict[str, str]:
                resolved: dict[str, str] = {}
                for value in missing:
                    try:
                        resolved[value] = str(
                            await self._session.get_share_token_info_hash(token=value)
                        ).lower()
                    except Exception:  # noqa: BLE001 - skip malformed tokens
                        continue
                return resolved

            try:
                self._token_info_hashes.update(
                    self._submit(resolve(), timeout=self._request_timeout_seconds)
                )
            except Exception:  # noqa: BLE001 - labels are best effort
                pass
        return {
            value: self._token_info_hashes[value]
            for value in values
            if value in self._token_info_hashes
        }

    def repository_token_status(self, token: str) -> dict[str, Any]:
        """Compare a trusted share token to repositories currently opened locally."""
        value = str(token or "").strip()
        if not value or self.status().state != "running" or self._session is None:
            return {"available": False, "attached": False, "info_hash": ""}

        async def inspect() -> dict[str, Any]:
            expected_hash = str(
                await self._session.get_share_token_info_hash(token=value)
            ).lower()
            repositories = await self._session.list_repositories()
            actual_hashes = {
                str(await repository.get_info_hash()).lower()
                for repository in repositories.values()
            }
            return {
                "available": True,
                "attached": expected_hash in actual_hashes,
                "info_hash": expected_hash,
            }

        try:
            return self._submit(inspect(), timeout=self._request_timeout_seconds)
        except Exception as exc:  # noqa: BLE001
            return {
                "available": False,
                "attached": False,
                "info_hash": "",
                "error": self._error_key(exc),
            }

    def set_folder_shared(self, folder_path: str, shared: bool) -> tuple[bool, str]:
        repository_path = self._repository_path(folder_path)
        try:

            async def set_enabled() -> bool:
                repository = await self._find_repository(path=repository_path)
                if repository is None:
                    return False
                await repository.set_sync_enabled(enabled=bool(shared))
                return True

            found = self._submit(set_enabled())
            if not found:
                return False, "ouisync_repository_not_found"
            return (
                True,
                "ouisync_repository_enabled" if shared else "ouisync_repository_paused",
            )
        except Exception as exc:  # noqa: BLE001
            return False, self._error_key(exc)

    def debug_logs(self, limit: int = 200) -> list[dict[str, str]]:
        try:
            lines = self._log_path.read_text(
                encoding="utf-8", errors="replace"
            ).splitlines()
        except OSError:
            return []
        return [
            {"provider": "ouisync", "msg": line}
            for line in lines[-max(0, int(limit)) :]
        ]

    def set_peer_device_ids(self, device_ids: list[str]) -> None:
        # Ouisync discovers peers through its repository tokens and network protocol.
        _ = device_ids

    def web_ui_url(self) -> str:
        return ""
