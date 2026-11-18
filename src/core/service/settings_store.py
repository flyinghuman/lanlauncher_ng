"""Persistent user settings storage."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class UserSettings:
    nickname: str
    theme: str
    log_level: str
    auto_start_sync: bool
    library_path_initialized: bool
    windows_game_drive_letter: str
    linux_install_path: str
    linux_windows_runtime: str = "wine"
    linux_proton_path: str = ""
    linux_proton_ge_path: str = ""
    extra_sync_items: list[dict] = field(default_factory=list)
    sync_only_mode: bool = False
    lan_mode: str = "client"
    ouisync_storage_path: str = ""
    ouisync_storage_fallback_paths: list[str] = field(default_factory=list)


def _normalize_drive_letter(raw: str) -> str:
    value = (raw or "").strip().upper()
    if len(value) != 1 or not ("A" <= value <= "Z"):
        raise ValueError("invalid_windows_drive_letter")
    return value


def _normalize_theme(raw: str) -> str:
    value = (raw or "").strip().lower()
    if value not in {"dark", "light"}:
        raise ValueError("invalid_theme")
    return value


def _normalize_log_level(raw: str) -> str:
    value = (raw or "").strip().upper()
    if value not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        raise ValueError("invalid_log_level")
    return value


def _normalize_linux_windows_runtime(raw: str) -> str:
    value = (raw or "").strip().lower()
    allowed = {"native", "wine", "proton", "proton-ge"}
    if value not in allowed:
        raise ValueError("invalid_linux_windows_runtime")
    return value


def _normalize_lan_mode(raw: str) -> str:
    value = (raw or "").strip().lower()
    allowed = {"client", "server"}
    if value not in allowed:
        raise ValueError("invalid_lan_mode")
    return value


class SettingsStore:
    def __init__(self, path: str):
        self._path = Path(path)

    def load(self, defaults: UserSettings) -> UserSettings:
        if not self._path.exists():
            return defaults
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return defaults
        if not isinstance(raw, dict):
            return defaults
        try:
            return self._build_from_payload(raw, defaults)
        except ValueError:
            return defaults

    def exists(self) -> bool:
        return self._path.exists()

    def save(self, settings: UserSettings) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(asdict(settings), indent=2), encoding="utf-8")

    def merge_and_validate(self, current: UserSettings, payload: dict) -> UserSettings:
        if not isinstance(payload, dict):
            raise ValueError("invalid_payload")
        public_payload = dict(payload)
        public_payload.pop("ouisync_storage_fallback_paths", None)
        return self._build_from_payload(public_payload, current)

    def _build_from_payload(
        self, payload: dict, fallback: UserSettings
    ) -> UserSettings:
        nickname = str(payload.get("nickname", fallback.nickname)).strip()
        if len(nickname) > 32:
            raise ValueError("nickname_too_long")

        theme = _normalize_theme(str(payload.get("theme", fallback.theme)))
        log_level = _normalize_log_level(
            str(payload.get("log_level", fallback.log_level))
        )
        drive = _normalize_drive_letter(
            str(
                payload.get(
                    "windows_game_drive_letter", fallback.windows_game_drive_letter
                )
            )
        )
        linux_install_path = str(
            payload.get("linux_install_path", fallback.linux_install_path)
        ).strip()
        if not linux_install_path:
            raise ValueError("linux_install_path_required")
        linux_windows_runtime = _normalize_linux_windows_runtime(
            str(payload.get("linux_windows_runtime", fallback.linux_windows_runtime))
        )
        linux_proton_path = str(
            payload.get("linux_proton_path", fallback.linux_proton_path)
        ).strip()
        linux_proton_ge_path = str(
            payload.get("linux_proton_ge_path", fallback.linux_proton_ge_path)
        ).strip()
        ouisync_storage_path = str(
            payload.get("ouisync_storage_path", fallback.ouisync_storage_path)
        ).strip()
        fallback_paths_raw = payload.get(
            "ouisync_storage_fallback_paths", fallback.ouisync_storage_fallback_paths
        )
        if not isinstance(fallback_paths_raw, (list, tuple)):
            raise ValueError("invalid_ouisync_storage_fallback_paths")
        ouisync_storage_fallback_paths = []
        for raw_path in fallback_paths_raw[-16:]:
            value = str(raw_path or "").strip()
            if value and value not in ouisync_storage_fallback_paths:
                ouisync_storage_fallback_paths.append(value)
        auto_start_raw = payload.get("auto_start_sync", fallback.auto_start_sync)
        if isinstance(auto_start_raw, bool):
            auto_start_sync = auto_start_raw
        elif isinstance(auto_start_raw, str):
            auto_start_sync = auto_start_raw.strip().lower() in {
                "1",
                "true",
                "yes",
                "on",
            }
        else:
            auto_start_sync = bool(auto_start_raw)

        sync_only_raw = payload.get("sync_only_mode", fallback.sync_only_mode)
        if isinstance(sync_only_raw, bool):
            sync_only_mode = sync_only_raw
        elif isinstance(sync_only_raw, str):
            sync_only_mode = sync_only_raw.strip().lower() in {
                "1",
                "true",
                "yes",
                "on",
            }
        else:
            sync_only_mode = bool(sync_only_raw)

        lan_mode = _normalize_lan_mode(
            str(
                payload.get(
                    "lan_mode",
                    payload.get("syncthing_cluster_role", fallback.lan_mode),
                )
            )
        )

        return UserSettings(
            nickname=nickname,
            theme=theme,
            log_level=log_level,
            auto_start_sync=auto_start_sync,
            sync_only_mode=sync_only_mode,
            library_path_initialized=bool(
                payload.get(
                    "library_path_initialized", fallback.library_path_initialized
                )
            ),
            windows_game_drive_letter=drive,
            linux_install_path=linux_install_path,
            linux_windows_runtime=linux_windows_runtime,
            linux_proton_path=linux_proton_path,
            linux_proton_ge_path=linux_proton_ge_path,
            extra_sync_items=list(
                payload.get("extra_sync_items", fallback.extra_sync_items) or []
            ),
            lan_mode=lan_mode,
            ouisync_storage_path=ouisync_storage_path,
            ouisync_storage_fallback_paths=ouisync_storage_fallback_paths,
        )
