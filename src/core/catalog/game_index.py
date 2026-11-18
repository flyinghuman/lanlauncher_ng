"""Versioned game index reader for local provider snapshots and legacy sources."""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any
from urllib.parse import urljoin, urlparse
from urllib.request import Request, url2pathname, urlopen

from src.core.catalog.metadata import GameMetadata
from src.core.catalog.publisher_trust import (
    GAME_CATALOG_ROOT_PUBLIC_KEYS,
    PublisherTrustStore,
    accept_monotonic_revision,
    strict_json_loads,
    verify_catalog_signature,
)

_GAME_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_INFO_HASH_RE = re.compile(r"^[^\s\x00]{1,256}$")
_MAX_OUISYNC_TOKEN_LENGTH = 8192
_MAX_EDITABLE_FILES = 4096


def _coerce_string(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _coerce_locale_text(raw: Any) -> tuple[str, str]:
    if isinstance(raw, dict):
        en = _coerce_string(raw.get("en") or raw.get("en_US"))
        de = _coerce_string(raw.get("de") or raw.get("de_DE"))
        if en and not de:
            de = en
        elif de and not en:
            en = de
        return en, de
    text = _coerce_string(raw)
    return text, text


def _coerce_locale_description(raw: Any) -> tuple[str, str, str]:
    en, de = _coerce_locale_text(raw)
    if isinstance(raw, dict):
        fr = _coerce_string(raw.get("fr") or raw.get("fr_FR"))
    else:
        fr = en
    return en, de, fr


def _coerce_float(raw: Any) -> float | None:
    if raw is None:
        return None
    if isinstance(raw, bool):
        return None
    text = _coerce_string(raw)
    if not text:
        return None
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _coerce_optional_int(raw: Any) -> int | None:
    if raw is None:
        return None
    if isinstance(raw, bool):
        return int(raw)
    text = _coerce_string(raw)
    if not text:
        return None
    try:
        return int(text)
    except (TypeError, ValueError):
        return None


def _coerce_optional_bool(raw: Any) -> bool | None:
    if raw is None:
        return None
    if isinstance(raw, bool):
        return raw
    text = _coerce_string(raw).lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return None


def _coerce_link_label(raw: Any) -> dict[str, str] | str:
    if isinstance(raw, dict):
        en = _coerce_string(raw.get("en") or raw.get("en_US"))
        de = _coerce_string(raw.get("de") or raw.get("de_DE"))
        if en and not de:
            de = en
        elif de and not en:
            en = de
        if en or de:
            return {"en": en, "de": de}
        return {}
    return _coerce_string(raw)


def _coerce_links(value: Any, base_url: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []

    links: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        url = _resolve_url(base_url, item.get("url"))
        if not url:
            continue
        entry: dict[str, Any] = {"url": url}
        label = _coerce_link_label(item.get("label"))
        if label:
            entry["label"] = label
        kind = _coerce_string(item.get("kind"))
        if kind:
            entry["kind"] = kind
        links.append(entry)
    return links


def _resolve_url(base_url: str, raw: Any) -> str:
    text = _coerce_string(raw)
    if not text:
        return ""
    parsed = urlparse(text)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return text
    if not base_url:
        return ""
    normalized_base = base_url.rstrip("/")
    if "/" in normalized_base:
        normalized_base = normalized_base.rsplit("/", 1)[0]
    return urljoin(normalized_base.rstrip("/") + "/", text)


def _resolve_media_url(base_url: str, local_base_url: str, raw: Any) -> str:
    text = _coerce_string(raw)
    if not text:
        return ""
    parsed = urlparse(text)
    if parsed.scheme in {"http", "https"}:
        return text
    local_base = urlparse(local_base_url)
    if local_base.scheme == "file":
        if parsed.scheme == "file":
            return url2pathname(parsed.path)
        candidate = Path(text)
        if candidate.is_absolute():
            return str(candidate)
        resolved = urlparse(urljoin(local_base_url, text))
        return url2pathname(resolved.path)
    return _resolve_url(base_url, text)


def _valid_game_id(game_id: str) -> bool:
    return bool(_GAME_ID_RE.match(_coerce_string(game_id)))


def _safe_relative_file_path(raw: Any) -> str:
    value = _coerce_string(raw).replace("\\", "/")
    if not value or "\x00" in value:
        return ""
    posix = PurePosixPath(value)
    windows = PureWindowsPath(value)
    if (
        posix.is_absolute()
        or windows.is_absolute()
        or windows.drive
        or not posix.parts
        or ".." in posix.parts
    ):
        return ""
    return posix.as_posix()


def _parse_llng_distribution(raw: Any) -> tuple[str, str, str, list[str]] | None:
    if raw is None:
        return "", "", "", []
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        return None
    distribution = raw.get("distribution")
    if distribution is None:
        return "", "", "", []
    if not isinstance(distribution, dict):
        return None
    provider = _coerce_string(distribution.get("provider")).lower()
    raw_read_token = distribution.get("read_token")
    if (
        provider != "ouisync"
        or not isinstance(raw_read_token, str)
        or raw_read_token != raw_read_token.strip()
    ):
        return None
    read_token = raw_read_token
    raw_info_hash = distribution.get("info_hash", "")
    if not isinstance(raw_info_hash, str):
        return None
    info_hash = raw_info_hash
    raw_editable_files = distribution.get("editable_files", [])
    if not isinstance(raw_editable_files, list) or len(raw_editable_files) > _MAX_EDITABLE_FILES:
        return None
    editable_files: list[str] = []
    seen: set[str] = set()
    for item in raw_editable_files:
        path = _safe_relative_file_path(item)
        if not path or path.casefold() in seen:
            return None
        seen.add(path.casefold())
        editable_files.append(path)
    if (
        not read_token
        or len(read_token) > _MAX_OUISYNC_TOKEN_LENGTH
        or any(char.isspace() or ord(char) < 32 for char in read_token)
        or (info_hash and not _INFO_HASH_RE.fullmatch(info_hash))
    ):
        return None
    return provider, read_token, info_hash, editable_files


@dataclass(frozen=True)
class _IndexSnapshot:
    loaded_at: float
    source_text: str
    entries: dict[str, GameMetadata]
    source_kind: str = "cache"


@dataclass(frozen=True)
class OuisyncRepositoryAccess:
    """Secret per-game capability, available only from a verified v2 index."""

    game_id: str
    read_token: str = field(repr=False)
    expected_info_hash: str = ""
    editable_files: tuple[str, ...] = ()
    repository_namespace: str = "repository"
    peer_addrs: tuple[str, ...] = ()


class GameIndexStore:
    """Load and cache a public game index from a JSON document.

    A synchronized local index is preferred. Reads are accepted only if the file
    stays stable during the read; otherwise the last valid snapshot remains active.
    """

    def __init__(
        self,
        index_url: str,
        cache_path: str | Path,
        request_timeout_seconds: float = 2.0,
        refresh_seconds: float = 3600.0,
        local_index_path: str | Path | None = None,
        trust_root_public_keys: dict[str, tuple[int, int]] | None = None,
        trust_state_path: str | Path | None = None,
    ):
        self._index_url = _coerce_string(index_url)
        self._cache_path = Path(cache_path).resolve(strict=False)
        self._local_index_path = (
            Path(local_index_path).resolve(strict=False)
            if local_index_path is not None
            else None
        )
        trust_registry_path = (
            self._local_index_path.parent / "trusted-publishers.json"
            if self._local_index_path is not None
            else None
        )
        self._trust_state_path = Path(
            trust_state_path
            or self._cache_path.with_name("publisher-trust-state.json")
        ).resolve(strict=False)
        self._index_revision_state_path = self._cache_path.with_name(
            "signed-index-state.json"
        )
        self._trust_store = PublisherTrustStore(
            root_public_keys=(
                GAME_CATALOG_ROOT_PUBLIC_KEYS
                if trust_root_public_keys is None
                else trust_root_public_keys
            ),
            cache_path=self._cache_path.with_name("trusted-publishers-cache.json"),
            state_path=self._trust_state_path,
            registry_path=trust_registry_path,
        )
        self._local_trust_signature = self._trust_store.current_registry_signature()
        self._publisher_keys: dict[str, dict[str, Any]] | None = None
        self._timeout = max(0.1, float(request_timeout_seconds))
        self._refresh_seconds = max(0.0, float(refresh_seconds))
        self._lock = threading.Lock()
        self._snapshot: _IndexSnapshot | None = None
        self._last_refresh_attempt_at = 0.0
        self._local_source_signature: tuple[str, int, int, int, int] | None = None

    def refresh(self, force: bool = False) -> bool:
        with self._lock:
            now = time.time()
            if not force and self._last_refresh_attempt_at:
                age = now - self._last_refresh_attempt_at
                if age < self._refresh_seconds:
                    return self._snapshot is not None

            self._last_refresh_attempt_at = now
            self._publisher_keys = self._trust_store.load(
                self._local_trust_registry_path()
            )
            current_trust_signature = self._trust_store.registry_signature()
            if current_trust_signature != self._local_trust_signature:
                self._snapshot = None
                self._local_trust_signature = current_trust_signature
            local_payload = None
            local_signature = None
            local_exists = False
            if self._local_index_path is not None:
                try:
                    local_exists = self._local_index_path.exists()
                except OSError:
                    local_exists = True
                if local_exists:
                    local_payload, local_signature = self._read_stable_local_index()

            payload = local_payload
            source_base_url = (
                self._local_index_path.as_uri()
                if payload is not None and self._local_index_path is not None
                else ""
            )
            parsed = self._parse_entries(payload, source_base_url) if payload else None
            source_kind = "local" if parsed is not None and local_payload is not None else ""
            if parsed is None and not local_exists:
                payload = self._read_remote_index()
                source_base_url = self._index_url
                parsed = self._parse_entries(payload, source_base_url) if payload else None
                if parsed is not None:
                    source_kind = "legacy"
            if parsed is None:
                if self._snapshot is not None:
                    return False
                payload = self._read_cache()
                source_base_url = self._cache_path.as_uri()
                parsed = self._parse_entries(payload, source_base_url) if payload else None
                if parsed is not None:
                    source_kind = "cache"
            if parsed is None:
                return False

            entries = parsed
            self._snapshot = _IndexSnapshot(now, payload, entries, source_kind)
            self._local_source_signature = (
                local_signature if source_base_url == self._local_index_uri() else None
            )
            if source_base_url != self._cache_path.as_uri():
                self._write_cache(payload)
            return True

    def managed_game_entries(self) -> list[GameMetadata] | None:
        """Return installable Ouisync metadata only from the validated local index."""
        with self._lock:
            snapshot = self._snapshot
            if snapshot is None or snapshot.source_kind != "local":
                return None
            return [
                metadata
                for metadata in snapshot.entries.values()
                if metadata.lan_supported is not False
                and (
                    metadata.distribution_provider == "ouisync"
                    or metadata.game_provider_type == "ouisync"
                )
            ]

    def managed_game_ids(self) -> set[str] | None:
        """Return locally distributed game IDs only for a validated local index."""
        entries = self.managed_game_entries()
        return None if entries is None else {metadata.game_id for metadata in entries}

    def refresh_if_changed(self) -> bool:
        """Refresh a provider snapshot when its synchronized index or trust file changes."""
        local_signature = self._stat_local_index()
        trust_signature = self._trust_store.current_registry_signature()
        if (
            local_signature != self._local_source_signature
            or trust_signature != self._local_trust_signature
        ):
            if local_signature is not None or self._local_source_signature is not None:
                refreshed = self.refresh(force=True)
                return (
                    refreshed
                    and self._local_source_signature == local_signature
                    and self._local_trust_signature == trust_signature
                )
            if trust_signature is not None or self._local_trust_signature is not None:
                return self.refresh(force=True)
        if time.time() - self._last_refresh_attempt_at >= self._refresh_seconds:
            return self.refresh(force=True)
        return False

    def set_local_index_path(self, index_path: str | Path) -> None:
        path = Path(index_path).resolve(strict=False)
        with self._lock:
            if path == self._local_index_path:
                return
            self._local_index_path = path
            self._trust_store.set_registry_path(
                path.parent / "trusted-publishers.json"
            )
            self._snapshot = None
            self._local_source_signature = None
            self._local_trust_signature = self._trust_store.current_registry_signature()
            self._last_refresh_attempt_at = 0.0

    def _local_trust_registry_path(self) -> Path | None:
        if self._local_index_path is None:
            return None
        return self._local_index_path.parent / "trusted-publishers.json"

    def get(self, game_id: str) -> GameMetadata | None:
        if not _valid_game_id(game_id):
            return None
        if self._snapshot is None:
            self.refresh(force=True)
        elif self._refresh_seconds > 0 and (
            time.time() - self._last_refresh_attempt_at
        ) >= self._refresh_seconds:
            self.refresh(force=True)
        snapshot = self._snapshot
        if snapshot is None:
            return None
        metadata = snapshot.entries.get(game_id)
        if metadata is None:
            return None
        # LLNG only cares about titles that are actually usable in LAN contexts.
        # Broad catalog entries may exist, but explicit non-LAN titles are skipped.
        if metadata.lan_supported is False:
            return None
        return metadata

    def ouisync_repository_access(
        self, game_id: str
    ) -> OuisyncRepositoryAccess | None:
        metadata = self.get(game_id)
        if (
            metadata is None
            or metadata.distribution_provider != "ouisync"
            or not metadata.distribution_read_token
        ):
            return None
        return OuisyncRepositoryAccess(
            game_id=metadata.game_id,
            read_token=metadata.distribution_read_token,
            expected_info_hash=metadata.distribution_info_hash,
            editable_files=tuple(metadata.distribution_editable_files),
        )

    def ouisync_catalog_entries(self, locale: str = "en") -> list[dict[str, str]]:
        """Return safe labels for signed Ouisync games without exposing their tokens."""
        snapshot = self._snapshot
        if snapshot is None:
            return []
        result = []
        for game_id, metadata in snapshot.entries.items():
            if (
                metadata.distribution_provider != "ouisync"
                or not metadata.distribution_read_token
                or metadata.lan_supported is False
            ):
                continue
            info_hash = str(metadata.distribution_info_hash or "").strip()
            if not info_hash:
                continue
            result.append(
                {
                    "game_id": game_id,
                    "title": metadata.effective_title(locale),
                    "info_hash": info_hash,
                }
            )
        return result

    def _read_remote_index(self) -> str | None:
        if not self._index_url:
            return None
        parsed = urlparse(self._index_url)
        if parsed.scheme in {"http", "https"}:
            request = Request(
                self._index_url,
                headers={"User-Agent": "LANLauncherNG-GameIndex/1.0"},
            )
            try:
                with urlopen(request, timeout=self._timeout) as response:  # noqa: S310
                    raw = response.read().decode("utf-8", errors="replace")
            except OSError:
                return None
            return raw
        if parsed.scheme == "file":
            candidate = Path(url2pathname(parsed.path))
        elif parsed.scheme:
            return None
        else:
            candidate = Path(self._index_url)
        try:
            return candidate.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None

    def _local_index_uri(self) -> str:
        return self._local_index_path.as_uri() if self._local_index_path else ""

    def _stat_local_index(self) -> tuple[str, int, int, int, int] | None:
        if self._local_index_path is None:
            return None
        try:
            stat = self._local_index_path.stat()
        except OSError:
            return None
        return (
            str(self._local_index_path),
            int(stat.st_mtime_ns),
            int(stat.st_size),
            int(getattr(stat, "st_dev", 0)),
            int(getattr(stat, "st_ino", 0)),
        )

    def _read_stable_local_index(
        self,
    ) -> tuple[str | None, tuple[str, int, int, int, int] | None]:
        if self._local_index_path is None:
            return None, None
        for attempt in range(3):
            before = self._stat_local_index()
            if before is None:
                return None, None
            try:
                payload = self._local_index_path.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                payload = None
            after = self._stat_local_index()
            if payload is not None and before == after:
                return payload, after
            if attempt < 2:
                time.sleep(0.05 * (attempt + 1))
        return None, None

    def _read_cache(self) -> str | None:
        try:
            return self._cache_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None

    def _write_cache(self, payload: str) -> None:
        temp_path: Path | None = None
        try:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self._cache_path.parent,
                prefix=f".{self._cache_path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temp_file:
                temp_file.write(payload)
                temp_file.flush()
                os.fsync(temp_file.fileno())
                temp_path = Path(temp_file.name)
            os.replace(temp_path, self._cache_path)
        except OSError:
            # Cache writes are best-effort only; the live fetch already succeeded.
            return
        finally:
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass

    def _parse_entries(
        self, payload: str, source_base_url: str = ""
    ) -> tuple[dict[str, GameMetadata], list[str]] | None:
        try:
            raw = strict_json_loads(payload)
        except (json.JSONDecodeError, ValueError):
            return None
        if not isinstance(raw, dict):
            return None

        schema_version = raw.get("schema_version", 1)
        if (
            isinstance(schema_version, bool)
            or not isinstance(schema_version, int)
            or schema_version not in {1, 2}
        ):
            return None
        if schema_version == 2 and not verify_catalog_signature(
            raw, self._publisher_keys
        ):
            return None

        base_url = _coerce_string(
            raw.get("source", {}).get("page_url")
            if isinstance(raw.get("source"), dict)
            else raw.get("page_url")
        )
        if not base_url:
            base_url = source_base_url or self._index_url
        games = raw.get("games")
        if not isinstance(games, list):
            return None

        entries: dict[str, GameMetadata] = {}
        seen_game_ids: set[str] = set()
        for item in games:
            if not isinstance(item, dict):
                continue
            local_media_base = (
                source_base_url
                if urlparse(source_base_url).scheme == "file"
                else ""
            )
            metadata = self._parse_entry(
                item, base_url, local_media_base, schema_version=schema_version
            )
            if metadata is None:
                continue
            normalized_game_id = metadata.game_id.casefold()
            if schema_version == 2 and normalized_game_id in seen_game_ids:
                return None
            seen_game_ids.add(normalized_game_id)
            entries[metadata.game_id] = metadata
        if schema_version == 2 and not accept_monotonic_revision(
            raw, "index_revision", self._index_revision_state_path
        ):
            return None
        return entries

    def _parse_entry(
        self,
        raw: dict[str, Any],
        base_url: str,
        local_media_base: str = "",
        *,
        schema_version: int = 1,
    ) -> GameMetadata | None:
        game_id = _coerce_string(raw.get("game_id"))
        if not _valid_game_id(game_id):
            return None

        llng_distribution: tuple[str, str, str, list[str]] = ("", "", "", [])
        if schema_version >= 2 and "llng" in raw:
            parsed_distribution = _parse_llng_distribution(raw.get("llng"))
            if parsed_distribution is None:
                return None
            llng_distribution = parsed_distribution

        title_en, title_de = _coerce_locale_text(raw.get("title"))
        description_en, description_de, description_fr = _coerce_locale_description(
            raw.get("description") or raw.get("readme")
        )
        genre_en, genre_de = _coerce_locale_text(raw.get("genre"))

        media = raw.get("media") if isinstance(raw.get("media"), dict) else {}
        image = _resolve_media_url(
            base_url,
            local_media_base,
            media.get("image_url") or media.get("image"),
        )
        video = _resolve_media_url(
            base_url,
            local_media_base,
            media.get("video_url") or media.get("video"),
        )
        game_provider_type = _coerce_string(
            raw.get("game_provider_type") or raw.get("provider_type")
        ).lower()
        if game_provider_type == "syncthing":
            game_provider_type = "ouisync"
        if game_provider_type not in {"", "resilio", "ouisync", "local"}:
            game_provider_type = ""

        archive_file = ""
        archive_format = ""
        archive_sha256 = ""
        archive_version_file = ""
        distribution = raw.get("distribution")
        archive = distribution.get("archive") if isinstance(distribution, dict) else None
        if isinstance(archive, dict):
            archive_file = _safe_relative_file_path(
                archive.get("file") or archive.get("path")
            )
            candidate_format = _coerce_string(archive.get("format")).lower()
            if candidate_format in {"eti", "rar", "tar.gz"}:
                archive_format = candidate_format
            archive_sha256_candidate = _coerce_string(archive.get("sha256")).lower()
            if re.fullmatch(r"[a-f0-9]{64}", archive_sha256_candidate):
                archive_sha256 = archive_sha256_candidate
            archive_version_file = _safe_relative_file_path(
                archive.get("version_file")
            )
            if not archive_file or not archive_format:
                archive_file = ""
                archive_format = ""
                archive_sha256 = ""
                archive_version_file = ""

        raw_installer_tasks = raw.get("installer_tasks", [])
        installer_tasks = (
            [dict(item) for item in raw_installer_tasks if isinstance(item, dict)]
            if isinstance(raw_installer_tasks, list)
            else []
        )
        raw_game_start = raw.get("game_start")
        game_start = raw_game_start if isinstance(raw_game_start, dict) else {}
        game_start_file = _safe_relative_file_path(game_start.get("file"))
        raw_game_start_args = game_start.get("args", [])
        if isinstance(raw_game_start_args, list):
            game_start_args = [
                _coerce_string(value)
                for value in raw_game_start_args
                if _coerce_string(value)
            ]
        elif isinstance(raw_game_start_args, str) and raw_game_start_args.strip():
            game_start_args = [raw_game_start_args.strip()]
        else:
            game_start_args = []

        links = _coerce_links(raw.get("links"), base_url)
        seen_urls = {str(entry.get("url", "")) for entry in links}
        for url_key, label in (
            ("page_url", {"en": "Game page", "de": "Spielseite"}),
            ("website_url", {"en": "Project website", "de": "Projekt-Website"}),
            ("community_url", {"en": "Community board", "de": "Community-Forum"}),
            ("discord_url", {"en": "Discord", "de": "Discord"}),
            ("download_url", {"en": "Download", "de": "Download"}),
        ):
            url = _resolve_url(base_url, raw.get(url_key))
            if url and url not in seen_urls:
                links.append({"label": label, "url": url, "kind": url_key})
                seen_urls.add(url)

        return GameMetadata(
            game_id=game_id,
            title=title_en,
            title_de=title_de,
            description=description_en,
            description_de=description_de,
            description_fr=description_fr,
            key=_coerce_string(raw.get("key") or raw.get("game_key")),
            release_year=_coerce_string(raw.get("release_year") or raw.get("year")),
            publisher=_coerce_string(raw.get("publisher")),
            size_gb=_coerce_float(
                raw.get("size_gb")
                if raw.get("size_gb") is not None
                else raw.get("size")
            ),
            max_players=_coerce_string(raw.get("max_players") or raw.get("players")),
            master_required=_coerce_optional_bool(
                raw.get("master_required")
                if raw.get("master_required") is not None
                else raw.get("master_req")
            ),
            version=_coerce_string(raw.get("version")),
            genre=genre_en,
            genre_de=genre_de,
            genre_id=_coerce_optional_int(raw.get("genre_id")),
            lan_supported=_coerce_optional_bool(
                raw.get("lan_supported", raw.get("lan_mode"))
            ),
            game_provider_type=game_provider_type,
            distribution_provider=llng_distribution[0],
            distribution_read_token=llng_distribution[1],
            distribution_info_hash=llng_distribution[2],
            distribution_editable_files=llng_distribution[3],
            runner=_coerce_string(raw.get("runner")),
            game_start_file=game_start_file,
            game_start_args=game_start_args,
            installer_tasks=installer_tasks,
            archive_file=archive_file,
            archive_format=archive_format,
            archive_sha256=archive_sha256,
            archive_version_file=archive_version_file,
            image=image or None,
            video=video or None,
            links=links,
            source_file=self._index_url,
        )
