"""Ouisync game repository setup, temporary mounts, and local file publication."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import tempfile
import threading
import uuid
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Callable


_ASSET_MANIFEST_NAME = ".llng-ouisync-assets.json"

# Ouisync 0.10.x can leave leaf nodes of a new snapshot flagged "missing" although
# their (unchanged) blocks are already stored locally: received leaves are always
# saved as missing, and the block offer is skipped because an older snapshot's leaf
# for the same block id reports it present. Those blocks are never requested again,
# so get_sync_progress() stalls below 100% (and the stale flags keep older
# snapshots alive as "fallback", inflating the total). When progress stops
# changing, verify the current snapshot by reading every file instead: reads use
# the block store directly and fail with BlockNotFound for genuinely absent data.
PROGRESS_STALL_SECONDS = 60.0
VERIFY_RETRY_MAX_SECONDS = 900.0
VERIFY_READ_CHUNK_BYTES = 1024 * 1024
_DIRECTORY_ENTRY_TYPE = 2


async def verify_repository_readable(
    repository: Any, cancelled: threading.Event | None = None
) -> bool:
    """Return True when every file of the current snapshot can be fully read."""
    pending = ["/"]
    try:
        while pending:
            directory = pending.pop()
            for entry in await repository.read_directory(path=directory):
                if cancelled is not None and cancelled.is_set():
                    raise asyncio.CancelledError
                path = f"{directory.rstrip('/')}/{entry.name}"
                if int(entry.entry_type) == _DIRECTORY_ENTRY_TYPE:
                    pending.append(path)
                    continue
                file = await repository.open_file(path=path)
                try:
                    length = int(await file.get_length())
                    offset = 0
                    while offset < length:
                        if cancelled is not None and cancelled.is_set():
                            raise asyncio.CancelledError
                        size = min(VERIFY_READ_CHUNK_BYTES, length - offset)
                        data = await file.read(offset=offset, size=size)
                        if not data:
                            return False
                        offset += len(data)
                finally:
                    await file.close()
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001 - any read failure means "not complete yet"
        return False
    return True


async def wait_until_repository_complete(
    repository: Any,
    *,
    cancelled: threading.Event | None = None,
    progress: Callable[[str, int, int], None] | None = None,
    phase: str = "syncing",
    stall_seconds: float = PROGRESS_STALL_SECONDS,
    poll_seconds: float = 0.5,
    logger: Any = None,
) -> tuple[list[Any], Any]:
    """Wait for a complete snapshot; verify by reading when block progress stalls.

    Returns the root directory entries and the last sync progress.
    """
    loop = asyncio.get_running_loop()
    last_counts: tuple[int, int] | None = None
    last_change = loop.time()
    verify_delay = stall_seconds
    while True:
        if cancelled is not None and cancelled.is_set():
            raise asyncio.CancelledError
        sync_progress = await repository.get_sync_progress()
        synced = max(0, int(sync_progress.value or 0))
        total = max(0, int(sync_progress.total or 0))
        entries = await repository.read_directory(path="/")
        if entries and (total == 0 or synced >= total):
            return entries, sync_progress
        now = loop.time()
        if (synced, total) != last_counts:
            last_counts = (synced, total)
            last_change = now
            verify_delay = stall_seconds
        elif entries and now - last_change >= verify_delay:
            if await verify_repository_readable(repository, cancelled):
                if logger is not None:
                    logger.info(
                        "ouisync_progress_stalled_content_verified synced=%s total=%s",
                        synced,
                        total,
                    )
                return entries, sync_progress
            # Data is genuinely missing; check again later with bounded backoff.
            last_change = loop.time()
            verify_delay = min(VERIFY_RETRY_MAX_SECONDS, verify_delay * 2)
        if progress is not None:
            progress(phase, synced, total)
        await asyncio.sleep(poll_seconds)


def validate_repository_id_not_case_colliding(
    storage_root: str | Path, game_id: str
) -> None:
    """Reject a case-only sibling collision before creating per-game storage."""
    key = str(game_id or "").strip()
    root = Path(storage_root).expanduser().resolve(strict=False)
    if not root.is_dir():
        return
    for child in root.iterdir():
        if child.name.casefold() == key.casefold() and child.name != key:
            raise ValueError("ouisync_repository_path_collision")


def game_repository_path(
    library_path: str | Path,
    game_id: str,
    repository_root: str | Path = "",
) -> Path:
    """Return the stable per-game Ouisync database location."""
    game_key = str(game_id or "").strip()
    if (
        not game_key
        or game_key in {".", ".."}
        or "/" in game_key
        or "\\" in game_key
        or ":" in game_key
    ):
        raise ValueError("ouisync_repository_path_unsafe")
    base = (
        Path(repository_root).expanduser()
        if str(repository_root or "").strip()
        else Path(library_path).expanduser()
    )
    base = base.resolve(strict=False)
    validate_repository_id_not_case_colliding(base, game_key)
    return base / game_key / ".ouisync" / game_key


def _safe_entry_name(value: str) -> str:
    normalized = str(value).replace("\\", "/")
    path = PurePosixPath(normalized)
    windows_path = PureWindowsPath(str(value))
    if (
        not value
        or path.is_absolute()
        or windows_path.is_absolute()
        or bool(windows_path.drive)
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
        or any(":" in part for part in path.parts)
        or any(part.startswith(".llng-") for part in path.parts)
        or any(
            part.endswith(".ouisyncdb")
            or part.endswith(".ouisyncdb-wal")
            or part.endswith(".ouisyncdb-shm")
            for part in path.parts
        )
    ):
        raise ValueError("ouisync_repository_entry_unsafe")
    return path.as_posix()


async def _find_repository(session: Any, repository_path: Path) -> Any | None:
    expected = repository_path.resolve(strict=False)
    database = Path(f"{repository_path}.ouisyncdb").resolve(strict=False)
    for repository in (await session.list_repositories()).values():
        actual = Path(await repository.get_path()).resolve(strict=False)
        if actual in {expected, database}:
            return repository
    if database.is_file():
        return await session.open_repository(path=str(repository_path))
    return None


async def ensure_repository_synced(
    *,
    session: Any,
    access: Any,
    repository_path: Path,
    cancelled: threading.Event | None = None,
    progress: Callable[[str, int, int], None] | None = None,
) -> Any:
    """Open or join a read-only repository and wait until its complete snapshot is local."""
    token = str(getattr(access, "read_token", "") or "").strip()
    if not token:
        raise ValueError("ouisync_repository_token_missing")
    repository_path = Path(repository_path).expanduser().resolve(strict=False)
    repository_path.parent.mkdir(parents=True, exist_ok=True)
    repository = await _find_repository(session, repository_path)
    if repository is None:
        repository = await session.create_repository(
            path=str(repository_path),
            token=token,
            sync_enabled=True,
            dht_enabled=getattr(access, "repository_namespace", "repository")
            == "repository",
            pex_enabled=True,
        )

    expected_hash = str(getattr(access, "expected_info_hash", "") or "").lower()
    actual_hash = str(await repository.get_info_hash()).lower()
    if not expected_hash or actual_hash != expected_hash:
        await repository.set_sync_enabled(enabled=False)
        raise ValueError("ouisync_repository_info_hash_mismatch")
    if not await repository.is_sync_enabled():
        await repository.set_sync_enabled(enabled=True)

    peer_addrs = getattr(access, "peer_addrs", ())
    if isinstance(peer_addrs, (list, tuple)) and peer_addrs:
        await session.add_user_provided_peers(addrs=list(peer_addrs))

    _entries, sync_progress = await wait_until_repository_complete(
        repository,
        cancelled=cancelled,
        progress=progress,
        logger=logging.getLogger(__name__),
    )
    if progress is not None:
        progress(
            "ready",
            max(0, int(sync_progress.value or 0)),
            max(0, int(sync_progress.total or 0)),
        )
    return repository


async def run_with_repository_mount(
    *,
    session: Any,
    access: Any,
    repository_path: Path,
    mount_root: Path,
    action: Callable[[Path], Any],
    cancelled: threading.Event | None = None,
    progress: Callable[[str, int, int], None] | None = None,
) -> Any:
    """Run one operation against a mounted repository and always unmount afterward."""
    repository = await ensure_repository_synced(
        session=session,
        access=access,
        repository_path=repository_path,
        cancelled=cancelled,
        progress=progress,
    )
    mount_root = Path(mount_root).expanduser().resolve(strict=False)
    mount_root.mkdir(parents=True, exist_ok=True)
    await session.set_mount_root(path=str(mount_root))
    mount_path = Path(await repository.mount()).resolve(strict=False)
    if not mount_path.is_relative_to(mount_root):
        await repository.unmount()
        raise ValueError("ouisync_mount_path_unsafe")
    try:
        if cancelled is not None and cancelled.is_set():
            raise asyncio.CancelledError
        action_task = asyncio.create_task(asyncio.to_thread(action, mount_path))
        try:
            return await asyncio.shield(action_task)
        except asyncio.CancelledError:
            # A worker thread cannot be stopped safely while it may still read the mount.
            await action_task
            raise
    finally:
        await repository.unmount()


def _metadata_archive_name(source: Path) -> str:
    metadata = source / "metadata.json"
    try:
        payload = json.loads(metadata.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return ""
    distribution = payload.get("distribution") if isinstance(payload, dict) else None
    archive_data = (
        distribution.get("archive") if isinstance(distribution, dict) else None
    )
    archive = (
        archive_data.get("file") or archive_data.get("path")
        if isinstance(archive_data, dict)
        else ""
    )
    if not isinstance(archive, str) or not archive.strip():
        return ""
    return _safe_entry_name(archive)


def _metadata_launch_names(source: Path) -> set[str]:
    try:
        payload = json.loads((source / "metadata.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return set()
    game_start = payload.get("game_start") if isinstance(payload, dict) else None
    filename = game_start.get("file") if isinstance(game_start, dict) else ""
    if not isinstance(filename, str) or not filename.strip():
        return set()
    try:
        return {_safe_entry_name(filename)}
    except ValueError:
        return set()


def _metadata_media_names(source: Path) -> set[str]:
    try:
        payload = json.loads((source / "metadata.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return set()
    if not isinstance(payload, dict):
        return set()
    media = payload.get("media") if isinstance(payload.get("media"), dict) else {}
    values = (
        payload.get("image")
        or payload.get("image_path")
        or media.get("image")
        or media.get("image_path")
        or media.get("image_url"),
        payload.get("video")
        or payload.get("video_path")
        or media.get("video")
        or media.get("video_path")
        or media.get("video_url"),
    )
    names = set()
    for value in values:
        if not isinstance(value, str) or not value.strip():
            continue
        try:
            names.add(_safe_entry_name(value))
        except ValueError:
            continue
    return names


def copy_repository_assets(
    source_root: Path,
    game_directory: Path,
    *,
    game_id: str,
    editable_files: tuple[str, ...] = (),
) -> list[str]:
    """Copy non-archive payload files needed after the temporary mount closes."""
    source_root = Path(source_root).resolve(strict=True)
    game_directory = Path(game_directory).resolve(strict=False)
    content_directory = game_directory / ".ouisync"
    stage = game_directory / f".llng-ouisync-stage-{uuid.uuid4().hex}"
    try:
        metadata = json.loads(
            (source_root / "metadata.json").read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, json.JSONDecodeError):
        metadata = {}
    metadata_game_id = metadata.get("game_id") if isinstance(metadata, dict) else ""
    if metadata_game_id and str(metadata_game_id).casefold() != str(game_id).casefold():
        raise ValueError("ouisync_repository_game_id_mismatch")
    archive_name = _metadata_archive_name(source_root)
    launch_names = _metadata_launch_names(source_root)
    needed_names = {"metadata.json", *_metadata_media_names(source_root), *launch_names}
    for name in editable_files:
        needed_names.add(_safe_entry_name(name))
    for name in (
        "game_start.cmd",
        "game_start.sh",
        "server_start.cmd",
        "server_start.sh",
    ):
        if (source_root / name).is_file():
            needed_names.add(name)
    copied: list[str] = []
    stage.mkdir(parents=True)
    try:
        for relative in sorted(needed_names):
            safe = _safe_entry_name(relative)
            source = source_root.joinpath(*PurePosixPath(safe).parts)
            parent = source.parent
            while parent.is_relative_to(source_root):
                if parent.is_symlink():
                    raise ValueError("ouisync_repository_entry_unsafe")
                parent = parent.parent
            if safe == archive_name or not source.exists():
                continue
            if source.is_symlink() or not source.is_file():
                raise ValueError("ouisync_repository_entry_unsafe")
            staged = stage.joinpath(*PurePosixPath(safe).parts)
            staged.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, staged)
            copied.append(safe)

        content_directory.mkdir(parents=True, exist_ok=True)
        for relative in copied:
            staged = stage.joinpath(*PurePosixPath(relative).parts)
            target = content_directory.joinpath(*PurePosixPath(relative).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staged, target)

        manifest_path = content_directory / _ASSET_MANIFEST_NAME
        temporary_name = ""
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=content_directory,
                prefix=".llng-ouisync-assets-",
                delete=False,
            ) as stream:
                temporary_name = stream.name
                json.dump(copied, stream, ensure_ascii=False, separators=(",", ":"))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_name, manifest_path)
        finally:
            if temporary_name:
                Path(temporary_name).unlink(missing_ok=True)

        for relative in editable_files:
            safe = _safe_entry_name(relative)
            source = source_root.joinpath(*PurePosixPath(safe).parts)
            if not source.is_file() or source.is_symlink():
                continue
            target = game_directory.joinpath(*PurePosixPath(safe).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
            shutil.copy2(source, temporary)
            os.replace(temporary, target)

        # Legacy launch scripts are required after the repository is unmounted.
        for name in (
            "game_start.cmd",
            "game_start.sh",
            "server_start.cmd",
            "server_start.sh",
        ):
            source = source_root / name
            if source.is_file() and not source.is_symlink():
                launch_names.add(name)
        for relative in launch_names:
            source = source_root.joinpath(*PurePosixPath(relative).parts)
            if not source.is_file() or source.is_symlink():
                continue
            target = game_directory.joinpath(*PurePosixPath(relative).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
            shutil.copy2(source, temporary)
            os.replace(temporary, target)
        return copied
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def remove_repository_assets(game_directory: Path) -> None:
    """Remove only files LLNG copied from the repository, preserving user edits."""
    content = Path(game_directory) / ".ouisync"
    manifest = content / _ASSET_MANIFEST_NAME
    try:
        names = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        names = []
    if not isinstance(names, list):
        names = []
    for name in names:
        try:
            safe = _safe_entry_name(name)
        except (TypeError, ValueError):
            continue
        target = content.joinpath(*PurePosixPath(safe).parts)
        try:
            target.resolve(strict=False).relative_to(content.resolve(strict=False))
        except (OSError, ValueError):
            continue
        if target.is_file() and not target.is_symlink():
            target.unlink(missing_ok=True)
    manifest.unlink(missing_ok=True)
    for directory, _, _ in os.walk(content, topdown=False):
        path = Path(directory)
        if path == content:
            continue
        try:
            path.rmdir()
        except OSError:
            pass
    try:
        content.rmdir()
    except OSError:
        pass
