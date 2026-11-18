"""Publish selected private LAN game sources through Ouisync repositories."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any


_REPOSITORY_NAME = "lan-repository"
_PUBLISH_MANIFEST = ".llng-published.json"
_EXCLUDED_OUISYNC_ROOT_NAMES = {
    "repository",
    _REPOSITORY_NAME,
    ".llng-materialized.json",
    _PUBLISH_MANIFEST,
}


def _excluded_ouisync_name(name: str, *, at_root: bool, game_id: str) -> bool:
    if not at_root:
        return name.startswith(".llng-ouisync-stage-")
    repository_db = f"{game_id}.ouisyncdb" if game_id else ""
    return (
        name in _EXCLUDED_OUISYNC_ROOT_NAMES
        or name == game_id
        or name.startswith(("repository.ouisyncdb", f"{_REPOSITORY_NAME}.ouisyncdb"))
        or bool(repository_db and name.startswith(repository_db))
        or name.startswith(".llng-ouisync-stage-")
    )


def _source_entries(root: Path) -> dict[str, tuple[Path, bool, bool]]:
    """Map repository-relative entries to source paths, excluding local installs."""
    entries: dict[str, tuple[Path, bool, bool]] = {}
    game_id = root.name
    ouisync_root = root / ".ouisync"

    def visit(
        directory: Path,
        destination_prefix: PurePosixPath = PurePosixPath(),
        *,
        from_ouisync: bool = False,
        at_ouisync_root: bool = False,
    ) -> None:
        for child in sorted(directory.iterdir(), key=lambda item: item.name.casefold()):
            if not from_ouisync and not destination_prefix.parts:
                if child.name in {"local", ".ouisync", ".llng-materialized.json"}:
                    continue
                if child.name == _PUBLISH_MANIFEST or child.name.startswith(
                    ".llng-ouisync-stage-"
                ):
                    continue
            if from_ouisync and _excluded_ouisync_name(
                child.name, at_root=at_ouisync_root, game_id=game_id
            ):
                continue
            if child.is_symlink():
                raise ValueError("ouisync_lan_source_symlink_unsupported")
            source_relative = child.relative_to(root)
            relative = destination_prefix / child.name
            if child.is_dir():
                if relative.as_posix() in entries:
                    existing = entries[relative.as_posix()]
                    if not existing[1]:
                        raise ValueError("ouisync_lan_source_path_collision")
                    if from_ouisync and not existing[2]:
                        entries[relative.as_posix()] = (child, True, True)
                else:
                    entries[relative.as_posix()] = (child, True, from_ouisync)
                visit(
                    child,
                    relative,
                    from_ouisync=from_ouisync,
                    at_ouisync_root=False,
                )
            elif child.is_file():
                key = relative.as_posix()
                existing = entries.get(key)
                if existing is not None:
                    if existing[1]:
                        raise ValueError("ouisync_lan_source_path_collision")
                    if not from_ouisync or existing[2]:
                        continue
                entries[key] = (root / source_relative, False, from_ouisync)
            else:
                raise ValueError("ouisync_lan_source_entry_unsupported")

    visit(root)
    if ouisync_root.is_dir() and not ouisync_root.is_symlink():
        visit(ouisync_root, from_ouisync=True, at_ouisync_root=True)
    return entries


def _source_manifest_path(source: Path) -> Path:
    return source / _PUBLISH_MANIFEST


def _read_source_manifest(source: Path) -> dict[str, dict[str, int]]:
    try:
        raw = json.loads(_source_manifest_path(source).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    files = raw.get("files") if isinstance(raw, dict) else None
    if not isinstance(files, dict):
        return {}
    result: dict[str, dict[str, int]] = {}
    for name, facts in files.items():
        if (
            isinstance(name, str)
            and isinstance(facts, dict)
            and type(facts.get("size")) is int
            and type(facts.get("mtime_ns")) is int
        ):
            result[name] = {"size": facts["size"], "mtime_ns": facts["mtime_ns"]}
    return result


def _write_source_manifest(source: Path, files: dict[str, dict[str, int]]) -> None:
    target = _source_manifest_path(source)
    temp_name = ""
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=source,
            prefix=".llng-published-",
            delete=False,
        ) as stream:
            temp_name = stream.name
            json.dump(
                {"schema_version": 1, "files": files},
                stream,
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            )
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, target)
    finally:
        if temp_name:
            Path(temp_name).unlink(missing_ok=True)


def _validate_source(
    folder_path: str, repository_path: str | Path | None = None
) -> tuple[Path, Path]:
    game = Path(folder_path).expanduser().resolve(strict=True)
    if not game.is_dir():
        raise ValueError("ouisync_lan_source_invalid")
    ouisync_root = game / ".ouisync"
    if ouisync_root.is_symlink() or (
        ouisync_root.exists() and not ouisync_root.is_dir()
    ):
        raise ValueError("ouisync_lan_source_invalid")
    resolved_repository = (
        Path(repository_path).expanduser().resolve(strict=False)
        if repository_path is not None
        else ouisync_root / _REPOSITORY_NAME
    )
    return game, resolved_repository


def source_signature(folder_path: str) -> str:
    """Fingerprint source names and file stat data without reading large game archives."""
    source, _ = _validate_source(folder_path)
    entries = _source_entries(source)
    facts = []
    for relative, (source_path, is_directory, _from_ouisync) in sorted(entries.items()):
        if is_directory:
            facts.append((relative, "directory"))
            continue
        stat = source_path.stat(follow_symlinks=False)
        facts.append((relative, stat.st_size, stat.st_mtime_ns))
    return hashlib.sha256(
        json.dumps(facts, ensure_ascii=True, separators=(",", ":")).encode("ascii")
    ).hexdigest()


async def _repository_entries(repository: Any, path: str = "/") -> dict[str, bool]:
    result: dict[str, bool] = {}
    for entry in await repository.read_directory(path=path):
        relative = f"{path.rstrip('/')}/{entry.name}"
        is_directory = int(entry.entry_type) == 2
        result[relative.lstrip("/")] = is_directory
        if is_directory:
            result.update(await _repository_entries(repository, relative))
    return result


async def publish_lan_game(
    session: Any,
    api: Any,
    folder_path: str,
    *,
    repository_path: str | Path | None = None,
    mount_root: str | Path | None = None,
) -> dict[str, str]:
    """Copy shareable game files through a temporary writable mount and issue a read token."""
    source, repository_path = _validate_source(folder_path, repository_path)
    desired = _source_entries(source)
    previous_manifest = _read_source_manifest(source)
    desired_files: dict[str, dict[str, int]] = {}
    for name, (source_path, is_directory, _from_ouisync) in desired.items():
        if is_directory:
            continue
        stat = source_path.stat(follow_symlinks=False)
        desired_files[name] = {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns}
    repository_path.parent.mkdir(parents=True, exist_ok=True)
    database_path = Path(f"{repository_path}.ouisyncdb")
    if repository_path.exists() or database_path.exists():
        repository = await session.open_repository(path=str(repository_path))
    else:
        repository = await session.create_repository(
            path=str(repository_path),
            sync_enabled=True,
            dht_enabled=False,
            pex_enabled=True,
        )

    current = await _repository_entries(repository)
    stale = {
        name
        for name, is_directory in current.items()
        if name not in desired or desired[name][1] != is_directory
    }
    for name in sorted(stale, key=lambda item: (item.count("/"), item), reverse=True):
        if current[name]:
            await repository.remove_directory(path=f"/{name}", recursive=True)
        else:
            await repository.remove_file(path=f"/{name}")

    changed_files = []
    for name, facts in desired_files.items():
        exists = name in current and not current[name]
        if exists and previous_manifest.get(name) == facts:
            continue
        if exists:
            await repository.remove_file(path=f"/{name}")
        changed_files.append(name)

    for name, (_source_path, is_directory, _from_ouisync) in sorted(
        desired.items(), key=lambda item: (item[0].count("/"), item[0])
    ):
        if is_directory and current.get(name) is not True:
            await repository.create_directory(path=f"/{name}")

    mount_parent = (
        Path(mount_root).expanduser().resolve(strict=False)
        if mount_root is not None
        else source.parent / ".llng-ouisync-mounts"
    )
    mount_parent.mkdir(parents=True, exist_ok=True)
    await session.set_mount_root(path=str(mount_parent))
    mounted = Path(await repository.mount()).resolve(strict=False)
    if not mounted.is_relative_to(mount_parent):
        await repository.unmount()
        raise ValueError("ouisync_mount_path_unsafe")
    try:
        for name in changed_files:
            origin = desired[name][0]
            target = mounted.joinpath(*PurePosixPath(name).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(f".{target.name}.llng-copy")
            shutil.copyfile(origin, temporary)
            os.replace(temporary, target)
    finally:
        await repository.unmount()
    _write_source_manifest(source, desired_files)
    if await repository.is_dht_enabled():
        await repository.set_dht_enabled(enabled=False)
    if not await repository.is_pex_enabled():
        await repository.set_pex_enabled(enabled=True)
    if not await repository.is_sync_enabled():
        await repository.set_sync_enabled(enabled=True)
    token = await repository.share(access_mode=api.AccessMode.READ)
    info_hash = str(await repository.get_info_hash()).lower()
    return {"read_token": token, "info_hash": info_hash}
