"""Helpers for LANPage launcher.ini integration."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

DEFAULT_LAUNCHER_INI_URL = "http://launcher.lan/launcher.ini"
DEFAULT_STATS_URL = "http://launcher.lan/stats.php"

_BLOCK_HEADER_PATTERN = re.compile(r"^\s*([A-Za-z0-9_]+)\b.*\{\s*$")


@dataclass(frozen=True)
class LauncherSiteSnapshot:
    """Current launcher-site state consumed by backend and frontend."""

    source_url: str
    reachable: bool
    last_success_at: float
    last_error: str
    lan_title: str
    lan_url: str
    stats_url: str
    discord_url: str
    ts3_server: str
    links: list[dict[str, str]]
    disable_games: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_url": self.source_url,
            "reachable": self.reachable,
            "last_success_at": self.last_success_at,
            "last_error": self.last_error,
            "lan_title": self.lan_title,
            "lan_url": self.lan_url,
            "stats_url": self.stats_url,
            "discord_url": self.discord_url,
            "ts3_server": self.ts3_server,
            "links": self.links,
            "disable_games": self.disable_games,
        }

    @staticmethod
    def from_dict(payload: dict[str, Any]) -> "LauncherSiteSnapshot":
        source_url = str(payload.get("source_url", "") or "").strip()
        links_raw = payload.get("links", [])
        links: list[dict[str, str]] = []
        if isinstance(links_raw, list):
            for item in links_raw:
                if not isinstance(item, dict):
                    continue
                label = str(item.get("label", "") or "").strip()
                url = str(item.get("url", "") or "").strip()
                key = str(item.get("key", "") or "").strip()
                if not url:
                    continue
                links.append({"key": key, "label": label or key or url, "url": url})
        disable_raw = payload.get("disable_games", [])
        disable_games: list[str] = []
        if isinstance(disable_raw, list):
            disable_games = normalize_disable_games(
                ",".join(str(item or "") for item in disable_raw)
            )
        return LauncherSiteSnapshot(
            source_url=source_url or DEFAULT_LAUNCHER_INI_URL,
            reachable=bool(payload.get("reachable", False)),
            last_success_at=float(payload.get("last_success_at", 0.0) or 0.0),
            last_error=str(payload.get("last_error", "") or ""),
            lan_title=str(payload.get("lan_title", "") or "").strip(),
            lan_url=str(payload.get("lan_url", "") or "").strip(),
            stats_url=str(payload.get("stats_url", "") or "").strip(),
            discord_url=str(payload.get("discord_url", "") or "").strip(),
            ts3_server=str(payload.get("ts3_server", "") or "").strip(),
            links=links,
            disable_games=disable_games,
        )


def default_snapshot(
    source_url: str = DEFAULT_LAUNCHER_INI_URL,
) -> LauncherSiteSnapshot:
    """Build default state used on fresh startup without reachable LANPage."""
    return LauncherSiteSnapshot(
        source_url=source_url,
        reachable=False,
        last_success_at=0.0,
        last_error="",
        lan_title="",
        lan_url="",
        stats_url=DEFAULT_STATS_URL,
        discord_url="",
        ts3_server="",
        links=[],
        disable_games=[],
    )


def parse_launcher_ini(raw: str) -> dict[str, str]:
    """Parse LANPage launcher.ini block syntax into key/value pairs."""
    values: dict[str, str] = {}
    lines = str(raw or "").splitlines()
    active_key = ""
    buffer: list[str] = []
    for line in lines:
        if active_key:
            if line.strip() == "}":
                values[active_key] = "\n".join(buffer).strip()
                active_key = ""
                buffer = []
                continue
            buffer.append(line.rstrip())
            continue
        match = _BLOCK_HEADER_PATTERN.match(line)
        if not match:
            continue
        active_key = str(match.group(1) or "").strip().lower()
        buffer = []
    return values


def normalize_disable_games(raw: str) -> list[str]:
    """Normalize disable_games values into unique, lowercase game ids."""
    source = str(raw or "")
    parts = re.split(r"[\s,;]+", source)
    cleaned: list[str] = []
    seen: set[str] = set()
    for part in parts:
        game_id = str(part or "").strip().lower()
        if not game_id or game_id in seen:
            continue
        seen.add(game_id)
        cleaned.append(game_id)
    return cleaned


def _parse_custom_link(raw: str, default_label: str) -> tuple[str, str]:
    text = str(raw or "").strip()
    if not text:
        return "", ""
    if "|" not in text:
        return default_label, text
    label, url = text.split("|", 1)
    clean_label = str(label or "").strip() or default_label
    clean_url = str(url or "").strip()
    return clean_label, clean_url


def _append_link(
    links: list[dict[str, str]],
    seen_urls: set[str],
    key: str,
    label: str,
    url: str,
) -> None:
    clean_url = str(url or "").strip()
    if not clean_url:
        return
    normalized_key = str(key or "").strip()
    if clean_url in seen_urls:
        return
    seen_urls.add(clean_url)
    links.append(
        {
            "key": normalized_key,
            "label": str(label or normalized_key or clean_url).strip(),
            "url": clean_url,
        }
    )


def build_snapshot_from_ini(
    launcher_ini_text: str, source_url: str, fetched_at: float
) -> LauncherSiteSnapshot:
    """Convert launcher.ini text into a structured snapshot."""
    values = parse_launcher_ini(launcher_ini_text)
    lan_title = str(values.get("lan_title", "") or "").strip()
    lan_url = str(values.get("lan_url", "") or "").strip()
    stats_url = str(values.get("stats_url", "") or "").strip()
    discord_url = str(values.get("discord_url", "") or "").strip()
    ts3_server = str(values.get("ts3_server", "") or "").strip()
    disable_games = normalize_disable_games(values.get("disable_games", ""))

    links: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    if lan_url:
        _append_link(
            links,
            seen_urls,
            "lan_url",
            lan_title or "LAN Page",
            lan_url,
        )
    for idx in range(1, 6):
        key = f"link_{idx}"
        label, url = _parse_custom_link(values.get(key, ""), f"Link {idx}")
        _append_link(links, seen_urls, key, label, url)
    _append_link(links, seen_urls, "discord_url", "Discord", discord_url)
    _append_link(links, seen_urls, "ts3_server", "TeamSpeak", ts3_server)

    return LauncherSiteSnapshot(
        source_url=str(source_url or "").strip() or DEFAULT_LAUNCHER_INI_URL,
        reachable=True,
        last_success_at=float(fetched_at or 0.0),
        last_error="",
        lan_title=lan_title,
        lan_url=lan_url,
        stats_url=stats_url or DEFAULT_STATS_URL,
        discord_url=discord_url,
        ts3_server=ts3_server,
        links=links,
        disable_games=disable_games,
    )


def derive_launcher_ini_url(
    configured_url: str,
    lan_url: str,
    fallback_url: str = DEFAULT_LAUNCHER_INI_URL,
) -> str:
    """Resolve preferred launcher.ini URL from config and current LAN URL."""
    configured = str(configured_url or "").strip()
    if configured:
        return configured
    lan = str(lan_url or "").strip()
    if lan:
        return urljoin(lan if lan.endswith("/") else f"{lan}/", "launcher.ini")
    return fallback_url


def derive_stats_url(snapshot: LauncherSiteSnapshot) -> str:
    """Resolve stats endpoint URL from snapshot with fallback defaults."""
    if snapshot.stats_url.strip():
        return snapshot.stats_url.strip()
    if snapshot.lan_url.strip():
        return urljoin(
            snapshot.lan_url
            if snapshot.lan_url.endswith("/")
            else f"{snapshot.lan_url}/",
            "stats.php",
        )
    return DEFAULT_STATS_URL
