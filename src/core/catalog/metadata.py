"""Per-game metadata loading and validation."""

from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass, field, replace
from pathlib import Path
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any
from urllib.parse import urlparse

_GAME_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_SUPPORTED_RUNNERS = {"", "wine", "proton", "proton-ge", "native", "auto", "windows"}
_SUPPORTED_EXTS = {
    "image": {".jpg", ".jpeg", ".png", ".webp"},
    "video": {".mp4", ".mkv", ".webm", ".avi", ".mov"},
}
_SUPPORTED_ARCHIVE_FORMATS = {"eti", "rar", "tar.gz"}
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


@dataclass(frozen=True)
class GameMetadata:
    """Metadata representation used to enrich catalog data."""

    game_id: str
    title: str = ""
    title_de: str = ""
    description: str = ""
    description_de: str = ""
    description_fr: str = ""
    key: str = ""
    release_year: str = ""
    publisher: str = ""
    size_gb: float | None = None
    max_players: str = ""
    master_required: bool | None = None
    version: str = ""
    genre: str = ""
    genre_de: str = ""
    genre_id: int | None = None
    lan_supported: bool | None = None
    game_provider_type: str = ""
    runner: str = ""
    game_start_file: str = ""
    game_start_args: list[str] = field(default_factory=list)
    installer_tasks: list[dict[str, Any]] = field(default_factory=list)
    archive_file: str = ""
    archive_format: str = ""
    archive_sha256: str = ""
    archive_version_file: str = ""
    distribution_provider: str = ""
    distribution_read_token: str = ""
    distribution_info_hash: str = ""
    distribution_editable_files: list[str] = field(default_factory=list)
    links: list[dict[str, Any]] = field(default_factory=list)
    image: str | None = None
    video: str | None = None
    source_file: str = ""

    def effective_title(self, locale: str) -> str:
        normalized = str(locale or "").strip().lower()
        if normalized == "de" and self.title_de:
            return self.title_de
        return self.title

    def effective_description(self, locale: str) -> str:
        normalized = str(locale or "").strip().lower()
        if normalized == "fr" and self.description_fr:
            return self.description_fr
        if normalized == "de" and self.description_de:
            return self.description_de
        return self.description

    def effective_genre(self, locale: str) -> str:
        normalized = str(locale or "").strip().lower()
        if normalized == "de" and self.genre_de:
            return self.genre_de
        return self.genre

    def as_payload(self) -> dict[str, Any]:
        return {
            "title": {"en": self.title, "de": self.title_de},
            "description": {
                "en": self.description,
                "de": self.description_de,
                "fr": self.description_fr,
            },
            "catalog": {
                "key": self.key,
                "release_year": self.release_year,
                "publisher": self.publisher,
                "size_gb": self.size_gb,
                "max_players": self.max_players,
                "master_required": self.master_required,
                "version": self.version,
                "genre": {"en": self.genre, "de": self.genre_de},
                "genre_id": self.genre_id,
                "lan_supported": self.lan_supported,
                "game_provider_type": self.game_provider_type,
            },
            "runner": self.runner,
            "game_start": {
                "file": self.game_start_file,
                "args": list(self.game_start_args),
            },
            "installer": {"tasks": list(self.installer_tasks)},
            "distribution": {
                "archive": {
                    "file": self.archive_file,
                    "format": self.archive_format,
                    "sha256": self.archive_sha256,
                    "version_file": self.archive_version_file,
                },
                "provider": self.distribution_provider,
                "info_hash": self.distribution_info_hash,
                "editable_files": list(self.distribution_editable_files),
            },
            "links": list(self.links),
            "media": {
                "image": self.image,
                "video": self.video,
            },
            "source_file": self.source_file,
        }


def _coerce_string(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _coerce_args(value: Any) -> list[str]:
    if isinstance(value, list):
        return [_coerce_string(item) for item in value if str(item).strip()]
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        return [text]
    return []


def _coerce_tasks(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        tasks = []
        for item in value:
            if isinstance(item, dict):
                tasks.append(dict(item))
        return tasks
    if isinstance(value, dict):
        tasks = value.get("tasks")
        return _coerce_tasks(tasks)
    return []


def _coerce_link_url(raw: Any) -> str:
    url = _coerce_string(raw)
    if not url:
        return ""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return url


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


def _coerce_links(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []

    links: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        url = _coerce_link_url(item.get("url"))
        if not url:
            continue
        label = _coerce_link_label(item.get("label"))
        entry: dict[str, Any] = {"url": url}
        if label:
            entry["label"] = label
        kind = _coerce_string(item.get("kind"))
        if kind:
            entry["kind"] = kind
        links.append(entry)
    return links


def _default_links(raw: dict[str, Any]) -> list[dict[str, Any]]:
    # Keep a small set of common link fields available even when authors prefer
    # the shorter top-level JSON form.
    defaults = [
        ("page_url", {"en": "Game page", "de": "Spielseite"}),
        ("website_url", {"en": "Project website", "de": "Projekt-Website"}),
        ("community_url", {"en": "Community board", "de": "Community-Forum"}),
        ("discord_url", {"en": "Discord", "de": "Discord"}),
        ("download_url", {"en": "Download", "de": "Download"}),
    ]
    links: list[dict[str, Any]] = []
    seen: set[str] = set()
    for key, label in defaults:
        url = _coerce_link_url(raw.get(key))
        if not url or url in seen:
            continue
        seen.add(url)
        links.append({"label": label, "url": url, "kind": key})
    return links


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


def _coerce_runner(raw: Any) -> str:
    value = _coerce_string(raw).lower()
    if value in _SUPPORTED_RUNNERS:
        return value
    if not value:
        return ""
    return "wine"


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


def _coerce_media_path(root: Path, raw: Any, media_type: str) -> str | None:
    path_text = _coerce_string(raw)
    if not path_text:
        return None

    if path_text.isdigit():
        return None

    candidate = Path(path_text.replace("\\", "/"))
    if candidate.is_absolute():
        return None
    if ".." in candidate.parts:
        return None

    resolved_root = root.resolve(strict=False)
    candidate = (resolved_root / candidate).resolve(strict=False)
    if not candidate.is_file():
        return None

    if media_type in _SUPPORTED_EXTS:
        if candidate.suffix.lower() not in _SUPPORTED_EXTS[media_type]:
            return None
    try:
        return candidate.relative_to(resolved_root).as_posix()
    except ValueError:
        return None


def _safe_relative_file(raw: Any) -> str:
    value = _coerce_string(raw).replace("\\", "/")
    if not value:
        return ""
    posix_path = PurePosixPath(value)
    windows_path = PureWindowsPath(value)
    if (
        posix_path.is_absolute()
        or windows_path.is_absolute()
        or windows_path.drive
        or ".." in posix_path.parts
    ):
        return ""
    return posix_path.as_posix()


def _default_media_path(root: Path, game_id: str, media_type: str) -> str | None:
    ext = "jpg" if media_type == "image" else "mp4"
    resolved_root = root.resolve(strict=False)
    candidate = (resolved_root / f"{game_id}.{ext}").resolve(strict=False)
    if not candidate.is_file():
        return None
    try:
        return candidate.relative_to(resolved_root).as_posix()
    except ValueError:
        return None


def _coerce_json_object(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    return {}


@dataclass
class _CachedMetadata:
    path: Path
    mtime_ns: int
    metadata: GameMetadata


class MetadataStore:
    """Load-and-cache per-game metadata JSON files."""

    def __init__(self, metadata_root: Path | str):
        self._metadata_root = Path(metadata_root).resolve(strict=False)
        self._cache: dict[str, _CachedMetadata] = {}
        self._lock = threading.Lock()

    def _metadata_file(self, game_id: str) -> Path:
        return self._metadata_root / f"{_safe_game_id(game_id)}.json"

    def get(self, game_id: str) -> GameMetadata | None:
        if not _is_valid_game_id(game_id):
            return None
        return self._load(game_id, self._metadata_file(game_id))

    def get_game_folder_metadata(self, game_id: str) -> GameMetadata | None:
        """Load the portable metadata.json stored beside the game's archive."""
        if not _is_valid_game_id(game_id):
            return None
        return self._load(game_id, self._metadata_root / "metadata.json")

    def _load(self, game_id: str, metadata_file: Path) -> GameMetadata | None:
        if not metadata_file.exists():
            self._cache.pop(game_id, None)
            return None
        if not metadata_file.is_file():
            self._cache.pop(game_id, None)
            return None

        try:
            mtime_ns = metadata_file.stat().st_mtime_ns
        except OSError:
            self._cache.pop(game_id, None)
            return None

        with self._lock:
            cached = self._cache.get(game_id)
            if cached is not None and cached.mtime_ns == mtime_ns:
                return cached.metadata

        try:
            parsed = self._parse_file(metadata_file)
        except (OSError, json.JSONDecodeError):
            self._cache.pop(game_id, None)
            return None
        if not parsed:
            self._cache.pop(game_id, None)
            return None

        parsed["source_file"] = str(metadata_file)
        source_file = parsed.get("source_file", "")
        metadata = _parse_metadata(
            game_id=game_id, raw=parsed, root=self._metadata_root
        )
        if metadata is None:
            self._cache.pop(game_id, None)
            return None
        if source_file:
            metadata = replace(metadata, source_file=source_file)

        cached = _CachedMetadata(
            path=metadata_file, mtime_ns=mtime_ns, metadata=metadata
        )
        with self._lock:
            self._cache[game_id] = cached
        return metadata

    def _parse_file(self, path: Path) -> dict[str, Any]:
        text = path.read_text(encoding="utf-8", errors="replace")
        raw = json.loads(text)
        parsed = _coerce_json_object(raw)
        if not parsed:
            return {}
        return parsed


def _parse_metadata(
    game_id: str, raw: dict[str, Any], root: Path
) -> GameMetadata | None:
    if not _is_valid_game_id(game_id):
        return None
    declared_game_id = _coerce_string(raw.get("game_id"))
    if declared_game_id and declared_game_id.casefold() != game_id.casefold():
        return None
    title_en, title_de = _coerce_locale_text(_coerce_json_object(raw).get("title"))
    if not title_en and not title_de:
        # Keep metadata file but don't force empty titles into catalog UI.
        title_en = _coerce_string(raw.get("name"))
        title_de = _coerce_string(raw.get("name_de"))

    # Many Lutris-like payloads use `readme`, while existing metadata may use
    # `description`; support both so authoring can stay lightweight.
    desc_en, desc_de, desc_fr = _coerce_locale_description(
        raw.get("description", raw.get("readme"))
    )
    genre_en, genre_de = _coerce_locale_text(raw.get("genre", raw.get("category")))

    raw_runner = _coerce_runner(raw.get("runner"))

    start_raw = raw.get("game_start") if isinstance(raw.get("game_start"), dict) else {}
    if not start_raw and isinstance(raw.get("start"), dict):
        start_raw = raw.get("start")

    start_file = _safe_relative_file(
        (start_raw.get("file") if isinstance(start_raw, dict) else None)
        or raw.get("game_start_file")
    )
    start_args = _coerce_args(
        start_raw.get("args") if isinstance(start_raw, dict) else None
    )

    installer_tasks = _coerce_tasks(
        raw.get("installer_tasks", raw.get("installer", raw.get("script")))
    )
    links = _coerce_links(raw.get("links"))
    for link in _default_links(raw):
        if not any(str(item.get("url", "")) == str(link.get("url", "")) for item in links):
            links.append(link)

    image = _coerce_media_path(
        root,
        raw.get("image")
        or raw.get("image_path")
        or _coerce_json_object(raw.get("media")).get("image"),
        "image",
    ) or _default_media_path(root, game_id, "image")
    video = _coerce_media_path(
        root,
        raw.get("video")
        or raw.get("video_path")
        or _coerce_json_object(raw.get("media")).get("video"),
        "video",
    ) or _default_media_path(root, game_id, "video")
    distribution = _coerce_json_object(raw.get("distribution"))
    raw_distribution_version = distribution.get("schema_version")
    distribution_version = _coerce_optional_int(raw_distribution_version)
    archive = _coerce_json_object(distribution.get("archive") or raw.get("archive"))
    archive_format = _coerce_string(archive.get("format")).lower()
    if raw_distribution_version is not None and distribution_version != 1:
        archive = {}
        archive_format = ""
    archive_file = _safe_archive_path(
        archive.get("file") or archive.get("path"), archive_format
    )
    if not archive_file:
        archive_format = ""
    elif archive_format not in _SUPPORTED_ARCHIVE_FORMATS:
        archive_format = _infer_archive_format(archive_file)
    archive_sha256 = _coerce_string(archive.get("sha256")).lower()
    if not archive_file or not _SHA256_RE.fullmatch(archive_sha256):
        archive_sha256 = ""
    archive_version_file = _safe_relative_file(archive.get("version_file"))
    key = _coerce_string(raw.get("key") or raw.get("game_key"))
    release_year = _coerce_string(raw.get("release_year") or raw.get("year"))
    publisher = _coerce_string(raw.get("publisher"))
    size_gb = _coerce_float(raw.get("size_gb", raw.get("size")))
    max_players = _coerce_string(raw.get("max_players", raw.get("players")))
    master_required = _coerce_optional_bool(
        raw.get("master_required", raw.get("master_req"))
    )
    version = _coerce_string(raw.get("version"))
    genre_id = _coerce_optional_int(raw.get("genre_id"))
    lan_supported = _coerce_optional_bool(
        raw.get("lan_supported", raw.get("lan_mode"))
    )
    game_provider_type = _coerce_string(
        raw.get("game_provider_type", raw.get("provider_type"))
    ).lower()
    if game_provider_type == "syncthing":
        game_provider_type = "ouisync"
    if game_provider_type not in {"", "resilio", "ouisync", "local"}:
        game_provider_type = ""

    return GameMetadata(
        game_id=game_id,
        title=title_en,
        title_de=title_de,
        description=desc_en,
        description_de=desc_de,
        description_fr=desc_fr,
        key=key,
        release_year=release_year,
        publisher=publisher,
        size_gb=size_gb,
        max_players=max_players,
        master_required=master_required,
        version=version,
        genre=genre_en,
        genre_de=genre_de,
        genre_id=genre_id,
        lan_supported=lan_supported,
        game_provider_type=game_provider_type,
        runner=raw_runner,
        game_start_file=start_file,
        game_start_args=start_args,
        installer_tasks=installer_tasks,
        archive_file=archive_file,
        archive_format=archive_format,
        archive_sha256=archive_sha256,
        archive_version_file=archive_version_file,
        links=links,
        image=image,
        video=video,
    )


def _safe_game_id(game_id: str) -> str:
    return str(game_id or "").strip()


def _is_valid_game_id(game_id: str) -> bool:
    return bool(_GAME_ID_RE.match(_safe_game_id(game_id)))


def _safe_archive_path(raw: Any, archive_format: str = "") -> str:
    value = _coerce_string(raw).replace("\\", "/")
    if not value:
        return ""
    posix_path = PurePosixPath(value)
    windows_path = PureWindowsPath(value)
    if (
        posix_path.is_absolute()
        or windows_path.is_absolute()
        or windows_path.drive
        or ".." in posix_path.parts
        or any(part in {"", "."} for part in posix_path.parts)
    ):
        return ""
    if (
        str(archive_format or "").lower() not in _SUPPORTED_ARCHIVE_FORMATS
        and _infer_archive_format(value) not in _SUPPORTED_ARCHIVE_FORMATS
    ):
        return ""
    return posix_path.as_posix()


def _infer_archive_format(value: str) -> str:
    lowered = str(value or "").strip().lower()
    if lowered.endswith(".tar.gz"):
        return "tar.gz"
    if lowered.endswith(".rar"):
        return "rar"
    if lowered.endswith(".eti"):
        return "eti"
    return ""
