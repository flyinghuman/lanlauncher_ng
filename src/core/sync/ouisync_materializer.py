"""Materialize a trusted Ouisync game repository into ordinary local files."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import threading
import uuid
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Callable

from src.core.sync.ouisync_repository import (
    nudge_repository,
    wait_until_repository_complete,
)

_MANIFEST_NAME = ".llng-materialized.json"
_REPOSITORY_DIRECTORY = ".ouisync"


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
        or path.parts[0] in {_MANIFEST_NAME, _REPOSITORY_DIRECTORY, "repository.ouisyncdb"}
        or path.parts[0].startswith(".llng-ouisync-stage-")
    ):
        raise ValueError("ouisync_repository_entry_unsafe")
    return path.as_posix()


def _target_under(root: Path, relative: str) -> Path:
    root = root.resolve(strict=False)
    target = root.joinpath(*PurePosixPath(relative).parts)
    if not target.parent.resolve(strict=False).is_relative_to(root):
        raise ValueError("ouisync_repository_entry_unsafe")
    return target


async def materialize_repository(
    *,
    session: Any,
    access: Any,
    game_directory: Path,
    materialized_directory: Path | None = None,
    repository_path: Path | None = None,
    cancelled: threading.Event | None = None,
    progress: Callable[[str, int, int], None] | None = None,
) -> None:
    """Sync and copy a signed repository, publishing files only after full success."""
    game_directory = Path(game_directory)
    content_directory = Path(materialized_directory or game_directory / _REPOSITORY_DIRECTORY)
    repository_namespace = str(getattr(access, "repository_namespace", "repository"))
    if repository_namespace not in {"repository", "lan-repository"}:
        raise ValueError("ouisync_repository_namespace_invalid")
    repository_path = Path(repository_path or game_directory / _REPOSITORY_DIRECTORY / repository_namespace)
    content_directory.mkdir(parents=True, exist_ok=True)
    repository_path.parent.mkdir(parents=True, exist_ok=True)
    repository = None
    if repository_path.exists() or Path(f"{repository_path}.ouisyncdb").exists():
        repository = await session.open_repository(path=str(repository_path))
    else:
        repository = await session.create_repository(
            path=str(repository_path),
            token=access.read_token,
            sync_enabled=True,
            dht_enabled=repository_namespace == "repository",
            pex_enabled=True,
        )

    actual_hash = str(await repository.get_info_hash()).lower()
    expected_hash = str(access.expected_info_hash or "").lower()
    if not expected_hash or actual_hash != expected_hash:
        await repository.set_sync_enabled(enabled=False)
        raise ValueError("ouisync_repository_info_hash_mismatch")
    if not await repository.is_sync_enabled():
        await repository.set_sync_enabled(enabled=True)
    peer_addrs = getattr(access, "peer_addrs", ())
    if isinstance(peer_addrs, (list, tuple)) and peer_addrs:
        await session.add_user_provided_peers(addrs=list(peer_addrs))
    repository_name = await repository.get_path()

    stage = game_directory / f".llng-ouisync-stage-{uuid.uuid4().hex}"
    stage.mkdir(parents=True)
    names: list[str] = []
    try:
        logger = logging.getLogger(__name__)

        async def nudge(attempt: int) -> None:
            await nudge_repository(
                session,
                repository,
                peer_addrs=tuple(peer_addrs) if isinstance(peer_addrs, (list, tuple)) else (),
                relink=attempt >= 1,
                logger=logger,
            )

        entries, _sync_progress = await wait_until_repository_complete(
            repository,
            cancelled=cancelled,
            progress=progress,
            phase="downloading",
            logger=logger,
            nudge=nudge,
        )

        total = len(entries)
        for index, entry in enumerate(entries, start=1):
            if cancelled is not None and cancelled.is_set():
                raise asyncio.CancelledError
            name = _safe_entry_name(entry.name)
            await session.copy(
                src_repo=repository_name,
                src_path=f"/{name}",
                dst_repo=None,
                dst_path=str(stage),
            )
            names.append(name)
            if progress is not None:
                progress("copying", index, total)

        if cancelled is not None and cancelled.is_set():
            raise asyncio.CancelledError

        manifest_path = content_directory / _MANIFEST_NAME
        try:
            previous = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            previous = []
        if not isinstance(previous, list):
            previous = []
        safe_previous = []
        for item in previous:
            try:
                safe_previous.append(_safe_entry_name(item))
            except (TypeError, ValueError):
                continue

        for stale in set(safe_previous) - set(names):
            target = _target_under(content_directory, stale)
            if target.is_dir() and not target.is_symlink():
                shutil.rmtree(target)
            else:
                target.unlink(missing_ok=True)

        for name in names:
            staged = stage.joinpath(*PurePosixPath(name).parts)
            target = _target_under(content_directory, name)
            target.parent.mkdir(parents=True, exist_ok=True)
            if staged.is_dir() and not staged.is_symlink():
                if target.exists():
                    if target.is_dir() and not target.is_symlink():
                        shutil.rmtree(target)
                    else:
                        target.unlink()
                os.replace(staged, target)
            else:
                os.replace(staged, target)

        temporary_manifest = manifest_path.with_name(f"{manifest_path.name}.tmp")
        temporary_manifest.write_text(
            json.dumps(names, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        os.replace(temporary_manifest, manifest_path)

        for relative in access.editable_files:
            safe_relative = _safe_entry_name(relative)
            source = _target_under(content_directory, safe_relative)
            target = _target_under(game_directory, safe_relative)
            if not source.is_file() or source.is_symlink():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            temp_target = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
            shutil.copy2(source, temp_target)
            os.replace(temp_target, target)
        if progress is not None:
            progress("complete", total, total)
    finally:
        shutil.rmtree(stage, ignore_errors=True)
