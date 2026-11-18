"""Publish the server's explicitly shared game metadata as a LAN index."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from collections.abc import Callable
from urllib.parse import urlparse

from src.core.catalog.lan_snapshot import (
    InvalidLanSnapshot,
    publish_snapshot,
    read_snapshot,
)

_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
_MAX_IMAGE_BYTES = 10 * 1024 * 1024
_MAX_METADATA_BYTES = 1024 * 1024


def _metadata_file(folder: Path) -> Path | None:
    for path in (
        folder / ".ouisync" / "metadata.json",
        folder / "metadata.json",
        folder / "metadata" / f"{folder.name}.json",
    ):
        if path.is_file():
            resolved = path.resolve(strict=True)
            try:
                resolved.relative_to(folder.resolve(strict=True))
            except ValueError as exc:
                raise ValueError("lan_metadata_invalid") from exc
            return resolved
    return None


def read_game_folder_metadata(folder: Path) -> tuple[Path | None, dict]:
    path = _metadata_file(folder)
    if path is None:
        return None, {}
    with path.open("rb") as stream:
        raw = stream.read(_MAX_METADATA_BYTES + 1)
    if len(raw) > _MAX_METADATA_BYTES:
        raise ValueError("lan_metadata_too_large")
    try:
        metadata = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("lan_metadata_invalid") from exc
    if not isinstance(metadata, dict) or (
        metadata.get("game_id") and metadata["game_id"] != folder.name
    ):
        raise ValueError("lan_metadata_invalid")
    return path, metadata


def _cover_path(folder: Path, metadata_file: Path, metadata: dict) -> Path | None:
    media = metadata.get("media") if isinstance(metadata.get("media"), dict) else {}
    value = media.get("image_url") or media.get("image") or metadata.get("image")
    candidates: list[Path] = []
    if isinstance(value, str) and value and not urlparse(value).scheme:
        candidates.append(metadata_file.parent / value)
    for base in (metadata_file.parent, folder, folder / ".ouisync", folder / "metadata"):
        candidates.extend(base / f"cover{ext}" for ext in sorted(_IMAGE_EXTENSIONS))
    root = folder.resolve(strict=True)
    for candidate in candidates:
        try:
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(root)
            if resolved.is_file() and resolved.suffix.lower() in _IMAGE_EXTENSIONS:
                return resolved
        except (OSError, ValueError):
            continue
    return None


def _copy_cover(source: Path, index_dir: Path, game_id: str) -> str:
    with source.open("rb") as stream:
        data = stream.read(_MAX_IMAGE_BYTES + 1)
    if len(data) > _MAX_IMAGE_BYTES:
        raise ValueError("lan_cover_too_large")
    digest = hashlib.sha256(data).hexdigest()[:20]
    relative = f"images/{game_id}-{digest}{source.suffix.lower()}"
    target = index_dir / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.parent.resolve(strict=True).parent != index_dir.resolve(strict=True):
        raise ValueError("lan_cover_path_invalid")
    if not target.is_file():
        name = ""
        try:
            with tempfile.NamedTemporaryFile(
                dir=target.parent, prefix=".cover-", delete=False
            ) as temp:
                name = temp.name
                temp.write(data)
                temp.flush()
                os.fsync(temp.fileno())
            os.replace(name, target)
        finally:
            if name:
                Path(name).unlink(missing_ok=True)
    return relative


def publish_shared_games(
    library: Path,
    folders: list[dict[str, str]],
    *,
    ouisync_publisher: Callable[[str], dict[str, str]] | None = None,
) -> bool:
    """Publish a snapshot; metadata errors leave the previous index intact."""
    if ouisync_publisher is None:
        raise ValueError("ouisync_lan_publisher_unavailable")
    root = library.resolve(strict=True)
    index_dir = root / "locallansync"
    if ouisync_publisher is not None:
        index_dir = index_dir / ".ouisync"
    if index_dir.resolve(strict=False).parent != root:
        if ouisync_publisher is None or index_dir.resolve(strict=False).parent.parent != root:
            raise ValueError("lan_catalog_path_invalid")
    index_path = index_dir / "index.json"
    try:
        previous = read_snapshot(index_path)
    except FileNotFoundError:
        previous = None
    source_id = previous["source"]["id"] if previous else "lan-" + uuid.uuid4().hex
    old_games = (
        {game["game_id"].casefold(): game for game in previous["games"]}
        if previous
        else {}
    )
    games = []
    for shared in sorted(folders, key=lambda item: item["path"].casefold()):
        folder = Path(shared["path"]).resolve(strict=True)
        if (
            folder.parent != root
            or not folder.is_dir()
            or folder.name == "locallansync"
        ):
            raise ValueError("lan_shared_folder_invalid")
        metadata_file, metadata = read_game_folder_metadata(folder)
        if metadata_file is None:
            # A temporarily unavailable metadata file must not unpublish a shared game.
            old = old_games.get(folder.name.casefold())
            if old:
                games.append(old)
            continue
        cover = _cover_path(folder, metadata_file, metadata)
        item = dict(metadata)
        item["game_id"] = folder.name
        capability = ouisync_publisher(str(folder))
        read_token = capability.get("read_token") if isinstance(capability, dict) else None
        info_hash = capability.get("info_hash") if isinstance(capability, dict) else None
        if not isinstance(read_token, str) or not read_token or not isinstance(info_hash, str) or not info_hash:
            raise ValueError("ouisync_lan_game_capability_invalid")
        item["llng"] = {
            "schema_version": 1,
            "distribution": {
                "provider": "ouisync",
                "read_token": read_token,
                "info_hash": info_hash,
                "editable_files": [],
            },
        }
        # The LAN index must never depend on the public image URL.
        item.pop("image", None)
        media = dict(item.get("media")) if isinstance(item.get("media"), dict) else {}
        media.pop("image", None)
        media.pop("image_url", None)
        if cover is not None:
            media["image_url"] = _copy_cover(cover, index_dir, folder.name)
        if media:
            item["media"] = media
        else:
            item.pop("media", None)
        games.append(item)
    snapshot = dict(previous) if previous else {}
    snapshot.pop("generated_at_utc", None)
    source = dict(previous["source"]) if previous else {}
    source.update({"id": source_id, "folder_id": "locallansync"})
    snapshot.update({"schema_version": 1, "source": source, "games": games})
    previous_content = dict(previous) if previous else None
    if previous_content is not None:
        previous_content.pop("generated_at_utc", None)
    if snapshot == previous_content and isinstance(previous.get("generated_at_utc"), str) and previous["generated_at_utc"]:
        return False
    snapshot["generated_at_utc"] = datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
    try:
        publish_snapshot(index_path, snapshot)
    except InvalidLanSnapshot as exc:
        raise ValueError("lan_metadata_invalid") from exc
    return True
