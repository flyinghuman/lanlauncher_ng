"""Validate and atomically publish the small LAN game-index snapshot.

This module defines the on-disk exchange format; it does not enroll devices or
modify the local catalog. Those operations must only consume validated snapshots.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

_ID = re.compile(r"^[A-Za-z0-9_-][A-Za-z0-9._-]{0,127}$")
_INFO_HASH = re.compile(r"^[^\s\x00]{1,256}$")
_MAX_INDEX_BYTES = 16 * 1024 * 1024


class InvalidLanSnapshot(ValueError):
    """The snapshot is incomplete or violates the LAN exchange contract."""


def _identifier(value: Any) -> bool:
    return isinstance(value, str) and bool(_ID.fullmatch(value))


def _local_image(value: Any) -> bool:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        return False
    path = PurePosixPath(value)
    return (
        not path.is_absolute()
        and all(part not in {".", ".."} for part in value.split("/"))
        and ":" not in value
        and path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
    )


def validate_snapshot(value: Any) -> dict[str, Any]:
    """Validate a complete snapshot without discarding extension fields."""
    if (
        not isinstance(value, dict)
        or type(value.get("schema_version")) is not int
        or value.get("schema_version") != 1
    ):
        raise InvalidLanSnapshot("lan_index_schema_invalid")
    if "generated_at_utc" in value and (not isinstance(value["generated_at_utc"], str) or not value["generated_at_utc"]):
        raise InvalidLanSnapshot("lan_index_timestamp_invalid")
    source = value.get("source")
    if not isinstance(source, dict) or not _identifier(source.get("id")):
        raise InvalidLanSnapshot("lan_index_source_invalid")
    if not _identifier(source.get("folder_id")):
        raise InvalidLanSnapshot("lan_index_folder_invalid")
    games = value.get("games")
    if not isinstance(games, list):
        raise InvalidLanSnapshot("lan_index_games_invalid")
    seen: set[str] = set()
    for game in games:
        if not isinstance(game, dict) or not _identifier(game.get("game_id")):
            raise InvalidLanSnapshot("lan_index_game_id_invalid")
        game_id = game["game_id"].casefold()
        if game_id in seen:
            raise InvalidLanSnapshot("lan_index_duplicate_game")
        seen.add(game_id)
        title = game.get("title")
        if isinstance(title, dict):
            title_valid = any(
                isinstance(title.get(k), str) and title[k].strip() for k in ("en", "de")
            )
        else:
            title_valid = isinstance(title, str) and bool(title.strip())
        llng = game.get("llng")
        distribution = llng.get("distribution") if isinstance(llng, dict) else None
        oui_token = distribution.get("read_token") if isinstance(distribution, dict) else None
        oui_hash = distribution.get("info_hash") if isinstance(distribution, dict) else None
        oui_valid = (
            isinstance(llng, dict)
            and llng.get("schema_version") == 1
            and isinstance(distribution, dict)
            and distribution.get("provider") == "ouisync"
            and isinstance(oui_token, str)
            and bool(oui_token)
            and oui_token == oui_token.strip()
            and len(oui_token) <= 8192
            and not any(char.isspace() or ord(char) < 32 for char in oui_token)
            and isinstance(oui_hash, str)
            and bool(_INFO_HASH.fullmatch(oui_hash))
        )
        if not title_valid or not oui_valid:
            raise InvalidLanSnapshot("lan_index_game_invalid")
        media = game.get("media", {})
        if not isinstance(media, dict):
            raise InvalidLanSnapshot("lan_index_media_invalid")
        for key in ("image", "image_url"):
            if (
                key in media
                and media[key] not in (None, "")
                and not _local_image(media[key])
            ):
                raise InvalidLanSnapshot("lan_index_image_invalid")
    return value


def read_snapshot(path: Path) -> dict[str, Any]:
    """Read a bounded complete snapshot; failures must not clear old state."""
    try:
        with path.open("rb") as stream:
            raw = stream.read(_MAX_INDEX_BYTES + 1)
        if len(raw) > _MAX_INDEX_BYTES:
            raise InvalidLanSnapshot("lan_index_too_large")
        return validate_snapshot(json.loads(raw.decode("utf-8")))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise InvalidLanSnapshot("lan_index_json_invalid") from exc


def publish_snapshot(path: Path, snapshot: dict[str, Any]) -> None:
    """Replace the index only after serialization and validation succeed."""
    validate_snapshot(snapshot)
    try:
        raw = (
            json.dumps(snapshot, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise InvalidLanSnapshot("lan_index_json_invalid") from exc
    if len(raw) > _MAX_INDEX_BYTES:
        raise InvalidLanSnapshot("lan_index_too_large")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_name = ""
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=".index-", suffix=".tmp", delete=False
        ) as stream:
            temp_name = stream.name
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    finally:
        if temp_name:
            Path(temp_name).unlink(missing_ok=True)
