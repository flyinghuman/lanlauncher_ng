"""Validated, atomic settings snapshots shared through the LAN catalog folder."""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

_MAX_SETTINGS_BYTES = 1024 * 1024
_GAME_ID = re.compile(r"^[A-Za-z0-9_-][A-Za-z0-9._-]{0,127}$")
_ALLOWED_LINK_SCHEMES = {"http", "https", "ts3server"}


class InvalidLanSettings(ValueError):
    """LAN settings are incomplete or violate the exchange contract."""


def validate_settings(value: Any) -> dict[str, Any]:
    if (
        not isinstance(value, dict)
        or type(value.get("schema_version")) is not int
        or value.get("schema_version") != 1
    ):
        raise InvalidLanSettings("lan_settings_schema_invalid")
    timestamp = value.get("generated_at_utc")
    if not isinstance(timestamp, str) or not timestamp.strip():
        raise InvalidLanSettings("lan_settings_timestamp_invalid")
    disabled = value.get("disable_games")
    if not isinstance(disabled, list):
        raise InvalidLanSettings("lan_settings_games_invalid")
    seen_games: set[str] = set()
    for game_id in disabled:
        if not isinstance(game_id, str) or not _GAME_ID.fullmatch(game_id):
            raise InvalidLanSettings("lan_settings_game_id_invalid")
        key = game_id.casefold()
        if key in seen_games:
            raise InvalidLanSettings("lan_settings_duplicate_game")
        seen_games.add(key)
    title = value.get("lan_title", "")
    if not isinstance(title, str) or len(title) > 256:
        raise InvalidLanSettings("lan_settings_title_invalid")
    for field in ("lan_url", "stats_url", "discord_url", "ts3_server"):
        url = value.get(field, "")
        if not isinstance(url, str) or len(url) > 2048:
            raise InvalidLanSettings("lan_settings_url_invalid")
        if not url.strip():
            continue
        parsed = urlsplit(url.strip())
        if parsed.scheme.lower() not in _ALLOWED_LINK_SCHEMES:
            raise InvalidLanSettings("lan_settings_url_invalid")
        if parsed.scheme.lower() in {"http", "https"} and not parsed.netloc:
            raise InvalidLanSettings("lan_settings_url_invalid")
    links = value.get("links")
    if not isinstance(links, list) or len(links) > 32:
        raise InvalidLanSettings("lan_settings_links_invalid")
    seen_urls: set[str] = set()
    for link in links:
        if not isinstance(link, dict):
            raise InvalidLanSettings("lan_settings_link_invalid")
        key, label, url = (link.get(name, "") for name in ("key", "label", "url"))
        if (
            not isinstance(key, str)
            or len(key) > 64
            or not isinstance(label, str)
            or not label.strip()
            or len(label) > 128
            or not isinstance(url, str)
            or not url.strip()
            or len(url) > 2048
        ):
            raise InvalidLanSettings("lan_settings_link_invalid")
        parsed = urlsplit(url.strip())
        if parsed.scheme.lower() not in _ALLOWED_LINK_SCHEMES:
            raise InvalidLanSettings("lan_settings_link_invalid")
        if parsed.scheme.lower() in {"http", "https"} and not parsed.netloc:
            raise InvalidLanSettings("lan_settings_link_invalid")
        normalized_url = url.strip().casefold()
        if normalized_url in seen_urls:
            raise InvalidLanSettings("lan_settings_duplicate_link")
        seen_urls.add(normalized_url)
    return value


def new_settings(
    *, disable_games: list[str] | None = None,
    lan_title: str = "",
    lan_url: str = "",
    stats_url: str = "",
    discord_url: str = "",
    ts3_server: str = "",
    links: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    value = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "lan_title": str(lan_title or "").strip(),
        "lan_url": str(lan_url or "").strip(),
        "stats_url": str(stats_url or "").strip(),
        "discord_url": str(discord_url or "").strip(),
        "ts3_server": str(ts3_server or "").strip(),
        "disable_games": list(disable_games or []),
        "links": list(links or []),
    }
    return validate_settings(value)


def display_links(settings: dict[str, Any]) -> list[dict[str, str]]:
    """Convert editable LANPage fields to the launcher links dropdown format."""
    links: list[dict[str, str]] = []
    seen: set[str] = set()

    def append(key: str, label: str, url: str) -> None:
        clean_url = str(url or "").strip()
        if not clean_url or clean_url.casefold() in seen:
            return
        seen.add(clean_url.casefold())
        links.append({"key": key, "label": label or key or clean_url, "url": clean_url})

    lan_title = str(settings.get("lan_title", "") or "").strip()
    append("lan_url", lan_title or "LAN Page", str(settings.get("lan_url", "")))
    for item in settings.get("links", []):
        if isinstance(item, dict):
            append(str(item.get("key", "")), str(item.get("label", "")), str(item.get("url", "")))
    append("discord_url", "Discord", str(settings.get("discord_url", "")))
    append("ts3_server", "TeamSpeak", str(settings.get("ts3_server", "")))
    return links


def read_settings(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as stream:
            raw = stream.read(_MAX_SETTINGS_BYTES + 1)
        if len(raw) > _MAX_SETTINGS_BYTES:
            raise InvalidLanSettings("lan_settings_too_large")
        return validate_settings(json.loads(raw.decode("utf-8")))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise InvalidLanSettings("lan_settings_json_invalid") from exc


def publish_settings(path: Path, value: dict[str, Any]) -> None:
    validated = validate_settings(value)
    raw = (json.dumps(validated, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    if len(raw) > _MAX_SETTINGS_BYTES:
        raise InvalidLanSettings("lan_settings_too_large")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_name = ""
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=".settings-", suffix=".tmp", delete=False
        ) as stream:
            temp_name = stream.name
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    finally:
        if temp_name:
            Path(temp_name).unlink(missing_ok=True)
