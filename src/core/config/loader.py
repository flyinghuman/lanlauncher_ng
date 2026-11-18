"""Runtime configuration model and loader."""

from __future__ import annotations

import json
import os
import platform
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class AppConfig:
    """Configuration values for the core process."""

    bind_host: str = "127.0.0.1"
    bind_port: int = 18080
    db_path: str = "data/lanlauncher.db"
    legacy_db_path: str = "data/legacy/game.db"
    library_path: str = "library"
    log_path: str = "data/logs/log.txt"
    log_level: str = "WARNING"
    default_locale: str = "en"
    sync_provider: str = "ouisync"
    sync_binary_path: str = "vendor/bin/windows-amd64/btsync.exe"
    sync_config_path: str = "config/resilio/config.json"
    sync_pid_path: str = "data/sync/rslsync.pid"
    sync_log_path: str = "data/logs/resilio-sync.log"
    sync_license_key_path: str = "vendor/licenses/resilio/llng.btskey"
    sync_api_url: str = "http://127.0.0.1:13338/api"
    sync_api_key: str = ""
    sync_request_timeout_seconds: float = 2.0
    sync_retry_count: int = 3
    sync_startup_retry_seconds: float = 20.0
    ouisync_binary_path: str = "vendor/bin/windows-amd64/ouisync.exe"
    ouisync_config_dir: str = "data/ouisync"
    ouisync_log_path: str = "data/logs/ouisync.log"
    ouisync_startup_timeout_seconds: float = 15.0
    platform_override: str = ""
    tool_manifest_path: str = "tools/manifest.json"
    repo_root: str = "."
    install_scripts_root: str = "scripts/wrappers"
    install_checks_path: str = "config/install/checks.json"
    windows_game_drive_letter: str = "D"
    windows_lan_root: str = "LAN"
    linux_cmd_wrapper_path: str = "scripts/wrappers/linux/run-cmd-wrapper.sh"
    windows_sync_firewall_script_path: str = (
        "scripts/wrappers/windows/resilio-network-mode.ps1"
    )
    linux_sync_firewall_script_path: str = (
        "scripts/wrappers/linux/resilio-network-mode.sh"
    )
    windows_private_network_script_path: str = (
        "scripts/wrappers/windows/set-lan-network-private.ps1"
    )
    settings_path: str = "data/settings.json"
    default_extra_sync_items_path: str = "config/bootstrap.json"
    optional_extra_sync_items_path: str = "config/optional-bootstrap.json"
    feature_flags_path: str = "config/feature-flags.json"
    update_manifest_path: str = "ng_provider/update/update-manifest.json"
    windows_updater_script_path: str = "scripts/wrappers/windows/llng-updater.ps1"
    linux_updater_script_path: str = "scripts/wrappers/linux/llng-updater.sh"
    launcher_ini_url: str = "http://launcher.lan/launcher.ini"
    launcher_ini_poll_seconds: float = 15.0
    launcher_request_timeout_seconds: float = 2.0
    launcher_stats_interval_seconds: float = 30.0
    game_index_url: str = ""
    game_index_cache_path: str = "data/game-index/index.json"
    game_index_request_timeout_seconds: float = 2.0
    game_index_refresh_seconds: float = 3600.0


def _default_sync_binary_path(platform_override: str) -> str:
    """Pick the local sync binary drop-in path by effective runtime platform."""
    effective = (platform_override or platform.system()).lower()
    if effective.startswith("win"):
        return "vendor/bin/windows-amd64/btsync.exe"
    return "vendor/bin/linux-x64/rslsync"


def _default_ouisync_binary_path(platform_override: str) -> str:
    effective = (platform_override or platform.system()).lower()
    if effective.startswith("win"):
        return "vendor/bin/windows-amd64/ouisync.exe"
    return "vendor/bin/linux-x64/ouisync"


def _int_or_default(value: str | None, default: int) -> int:
    if value is None:
        return default

    try:
        return int(value)
    except ValueError:
        return default


def _normalize_log_level(value: str | None, default: str) -> str:
    if not value:
        return default

    normalized = value.upper()
    allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
    if normalized not in allowed:
        return default
    return normalized


def _normalize_locale(value: str | None, default: str) -> str:
    if not value:
        return default
    normalized = value.lower()
    return normalized if normalized in {"en", "de"} else default


def _float_or_default(value: str | None, default: float) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}

    with path.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)

    if not isinstance(raw, dict):
        raise ValueError(f"Configuration file must contain a JSON object: {path}")

    return raw


def load_config(path: str | None = None) -> AppConfig:
    """Load config from file and env vars with sane defaults.

    Priority order:
    1) explicit file path if provided
    2) local config file (`config/core.json`) if present
    3) environment variable overrides
    4) dataclass defaults
    """

    file_path = Path(path) if path else Path("config/core.json")
    from_file = _load_json(file_path)

    bind_host = os.getenv(
        "LLNG_BIND_HOST", str(from_file.get("bind_host", AppConfig.bind_host))
    )
    bind_port = _int_or_default(
        os.getenv(
            "LLNG_BIND_PORT", str(from_file.get("bind_port", AppConfig.bind_port))
        ),
        AppConfig.bind_port,
    )
    db_path = os.getenv(
        "LLNG_DB_PATH", str(from_file.get("db_path", AppConfig.db_path))
    )
    legacy_db_path = os.getenv(
        "LLNG_LEGACY_DB_PATH",
        str(from_file.get("legacy_db_path", AppConfig.legacy_db_path)),
    )
    library_path = os.getenv(
        "LLNG_LIBRARY_PATH", str(from_file.get("library_path", AppConfig.library_path))
    )
    log_level = _normalize_log_level(
        os.getenv(
            "LLNG_LOG_LEVEL", str(from_file.get("log_level", AppConfig.log_level))
        ),
        AppConfig.log_level,
    )
    log_path = os.getenv(
        "LLNG_LOG_PATH", str(from_file.get("log_path", AppConfig.log_path))
    )
    default_locale = _normalize_locale(
        os.getenv(
            "LLNG_DEFAULT_LOCALE",
            str(from_file.get("default_locale", AppConfig.default_locale)),
        ),
        AppConfig.default_locale,
    )
    sync_provider = os.getenv(
        "LLNG_SYNC_PROVIDER",
        str(from_file.get("sync_provider", AppConfig.sync_provider)),
    )
    if sync_provider.strip().lower() == "syncthing":
        sync_provider = "ouisync"
    platform_override = os.getenv(
        "LLNG_PLATFORM_OVERRIDE",
        str(from_file.get("platform_override", AppConfig.platform_override)),
    )
    default_sync_binary_path = _default_sync_binary_path(platform_override)
    sync_binary_path = os.getenv(
        "LLNG_SYNC_BINARY_PATH",
        str(from_file.get("sync_binary_path", default_sync_binary_path)),
    )
    sync_config_path = os.getenv(
        "LLNG_SYNC_CONFIG_PATH",
        str(from_file.get("sync_config_path", AppConfig.sync_config_path)),
    )
    sync_pid_path = os.getenv(
        "LLNG_SYNC_PID_PATH",
        str(from_file.get("sync_pid_path", AppConfig.sync_pid_path)),
    )
    sync_log_path = os.getenv(
        "LLNG_SYNC_LOG_PATH",
        str(from_file.get("sync_log_path", AppConfig.sync_log_path)),
    )
    sync_license_key_path = os.getenv(
        "LLNG_SYNC_LICENSE_KEY_PATH",
        str(from_file.get("sync_license_key_path", AppConfig.sync_license_key_path)),
    )
    sync_api_url = os.getenv(
        "LLNG_SYNC_API_URL", str(from_file.get("sync_api_url", AppConfig.sync_api_url))
    )
    sync_api_key = os.getenv(
        "LLNG_SYNC_API_KEY", str(from_file.get("sync_api_key", AppConfig.sync_api_key))
    )
    sync_request_timeout_seconds = _float_or_default(
        os.getenv(
            "LLNG_SYNC_REQUEST_TIMEOUT_SECONDS",
            str(
                from_file.get(
                    "sync_request_timeout_seconds",
                    AppConfig.sync_request_timeout_seconds,
                )
            ),
        ),
        AppConfig.sync_request_timeout_seconds,
    )
    sync_retry_count = _int_or_default(
        os.getenv(
            "LLNG_SYNC_RETRY_COUNT",
            str(from_file.get("sync_retry_count", AppConfig.sync_retry_count)),
        ),
        AppConfig.sync_retry_count,
    )
    sync_startup_retry_seconds = _float_or_default(
        os.getenv(
            "LLNG_SYNC_STARTUP_RETRY_SECONDS",
            str(
                from_file.get(
                    "sync_startup_retry_seconds", AppConfig.sync_startup_retry_seconds
                )
            ),
        ),
        AppConfig.sync_startup_retry_seconds,
    )
    ouisync_binary_path = os.getenv(
        "LLNG_OUISYNC_BINARY_PATH",
        str(
            from_file.get(
                "ouisync_binary_path",
                _default_ouisync_binary_path(platform_override),
            )
        ),
    )
    ouisync_config_dir = os.getenv(
        "LLNG_OUISYNC_CONFIG_DIR",
        str(from_file.get("ouisync_config_dir", AppConfig.ouisync_config_dir)),
    )
    ouisync_log_path = os.getenv(
        "LLNG_OUISYNC_LOG_PATH",
        str(from_file.get("ouisync_log_path", AppConfig.ouisync_log_path)),
    )
    ouisync_startup_timeout_seconds = _float_or_default(
        os.getenv(
            "LLNG_OUISYNC_STARTUP_TIMEOUT_SECONDS",
            str(
                from_file.get(
                    "ouisync_startup_timeout_seconds",
                    AppConfig.ouisync_startup_timeout_seconds,
                )
            ),
        ),
        AppConfig.ouisync_startup_timeout_seconds,
    )
    tool_manifest_path = os.getenv(
        "LLNG_TOOL_MANIFEST_PATH",
        str(from_file.get("tool_manifest_path", AppConfig.tool_manifest_path)),
    )
    repo_root = os.getenv(
        "LLNG_REPO_ROOT", str(from_file.get("repo_root", AppConfig.repo_root))
    )
    install_scripts_root = os.getenv(
        "LLNG_INSTALL_SCRIPTS_ROOT",
        str(from_file.get("install_scripts_root", AppConfig.install_scripts_root)),
    )
    install_checks_path = os.getenv(
        "LLNG_INSTALL_CHECKS_PATH",
        str(from_file.get("install_checks_path", AppConfig.install_checks_path)),
    )
    windows_game_drive_letter = os.getenv(
        "LLNG_WINDOWS_GAME_DRIVE_LETTER",
        str(
            from_file.get(
                "windows_game_drive_letter", AppConfig.windows_game_drive_letter
            )
        ),
    )
    windows_lan_root = os.getenv(
        "LLNG_WINDOWS_LAN_ROOT",
        str(from_file.get("windows_lan_root", AppConfig.windows_lan_root)),
    )
    linux_cmd_wrapper_path = os.getenv(
        "LLNG_LINUX_CMD_WRAPPER_PATH",
        str(from_file.get("linux_cmd_wrapper_path", AppConfig.linux_cmd_wrapper_path)),
    )
    windows_sync_firewall_script_path = os.getenv(
        "LLNG_WINDOWS_SYNC_FIREWALL_SCRIPT_PATH",
        str(
            from_file.get(
                "windows_sync_firewall_script_path",
                AppConfig.windows_sync_firewall_script_path,
            )
        ),
    )
    linux_sync_firewall_script_path = os.getenv(
        "LLNG_LINUX_SYNC_FIREWALL_SCRIPT_PATH",
        str(
            from_file.get(
                "linux_sync_firewall_script_path",
                AppConfig.linux_sync_firewall_script_path,
            )
        ),
    )
    windows_private_network_script_path = os.getenv(
        "LLNG_WINDOWS_PRIVATE_NETWORK_SCRIPT_PATH",
        str(
            from_file.get(
                "windows_private_network_script_path",
                AppConfig.windows_private_network_script_path,
            )
        ),
    )
    settings_path = os.getenv(
        "LLNG_SETTINGS_PATH",
        str(from_file.get("settings_path", AppConfig.settings_path)),
    )
    default_extra_sync_items_path = os.getenv(
        "LLNG_DEFAULT_EXTRA_SYNC_ITEMS_PATH",
        str(
            from_file.get(
                "default_extra_sync_items_path", AppConfig.default_extra_sync_items_path
            )
        ),
    )
    optional_extra_sync_items_path = os.getenv(
        "LLNG_OPTIONAL_EXTRA_SYNC_ITEMS_PATH",
        str(
            from_file.get(
                "optional_extra_sync_items_path",
                AppConfig.optional_extra_sync_items_path,
            )
        ),
    )
    feature_flags_path = os.getenv(
        "LLNG_FEATURE_FLAGS_PATH",
        str(from_file.get("feature_flags_path", AppConfig.feature_flags_path)),
    )
    update_manifest_path = os.getenv(
        "LLNG_UPDATE_MANIFEST_PATH",
        str(from_file.get("update_manifest_path", AppConfig.update_manifest_path)),
    )
    windows_updater_script_path = os.getenv(
        "LLNG_WINDOWS_UPDATER_SCRIPT_PATH",
        str(
            from_file.get(
                "windows_updater_script_path", AppConfig.windows_updater_script_path
            )
        ),
    )
    linux_updater_script_path = os.getenv(
        "LLNG_LINUX_UPDATER_SCRIPT_PATH",
        str(
            from_file.get(
                "linux_updater_script_path", AppConfig.linux_updater_script_path
            )
        ),
    )
    launcher_ini_url = os.getenv(
        "LLNG_LAUNCHER_INI_URL",
        str(from_file.get("launcher_ini_url", AppConfig.launcher_ini_url)),
    )
    launcher_ini_poll_seconds = _float_or_default(
        os.getenv(
            "LLNG_LAUNCHER_INI_POLL_SECONDS",
            str(
                from_file.get(
                    "launcher_ini_poll_seconds", AppConfig.launcher_ini_poll_seconds
                )
            ),
        ),
        AppConfig.launcher_ini_poll_seconds,
    )
    launcher_request_timeout_seconds = _float_or_default(
        os.getenv(
            "LLNG_LAUNCHER_REQUEST_TIMEOUT_SECONDS",
            str(
                from_file.get(
                    "launcher_request_timeout_seconds",
                    AppConfig.launcher_request_timeout_seconds,
                )
            ),
        ),
        AppConfig.launcher_request_timeout_seconds,
    )
    launcher_stats_interval_seconds = _float_or_default(
        os.getenv(
            "LLNG_LAUNCHER_STATS_INTERVAL_SECONDS",
            str(
                from_file.get(
                    "launcher_stats_interval_seconds",
                    AppConfig.launcher_stats_interval_seconds,
                )
            ),
        ),
        AppConfig.launcher_stats_interval_seconds,
    )
    game_index_url = os.getenv(
        "LLNG_GAME_INDEX_URL",
        str(from_file.get("game_index_url", AppConfig.game_index_url)),
    )
    game_index_cache_path = os.getenv(
        "LLNG_GAME_INDEX_CACHE_PATH",
        str(
            from_file.get("game_index_cache_path", AppConfig.game_index_cache_path)
        ),
    )
    game_index_request_timeout_seconds = _float_or_default(
        os.getenv(
            "LLNG_GAME_INDEX_REQUEST_TIMEOUT_SECONDS",
            str(
                from_file.get(
                    "game_index_request_timeout_seconds",
                    AppConfig.game_index_request_timeout_seconds,
                )
            ),
        ),
        AppConfig.game_index_request_timeout_seconds,
    )
    game_index_refresh_seconds = _float_or_default(
        os.getenv(
            "LLNG_GAME_INDEX_REFRESH_SECONDS",
            str(
                from_file.get(
                    "game_index_refresh_seconds",
                    AppConfig.game_index_refresh_seconds,
                )
            ),
        ),
        AppConfig.game_index_refresh_seconds,
    )

    return AppConfig(
        bind_host=bind_host,
        bind_port=bind_port,
        db_path=db_path,
        legacy_db_path=legacy_db_path,
        library_path=library_path,
        log_path=log_path,
        log_level=log_level,
        default_locale=default_locale,
        sync_provider=sync_provider,
        sync_binary_path=sync_binary_path,
        sync_config_path=sync_config_path,
        sync_pid_path=sync_pid_path,
        sync_log_path=sync_log_path,
        sync_license_key_path=sync_license_key_path,
        sync_api_url=sync_api_url,
        sync_api_key=sync_api_key,
        sync_request_timeout_seconds=sync_request_timeout_seconds,
        sync_retry_count=sync_retry_count,
        sync_startup_retry_seconds=sync_startup_retry_seconds,
        ouisync_binary_path=ouisync_binary_path,
        ouisync_config_dir=ouisync_config_dir,
        ouisync_log_path=ouisync_log_path,
        ouisync_startup_timeout_seconds=ouisync_startup_timeout_seconds,
        platform_override=platform_override,
        tool_manifest_path=tool_manifest_path,
        repo_root=repo_root,
        install_scripts_root=install_scripts_root,
        install_checks_path=install_checks_path,
        windows_game_drive_letter=windows_game_drive_letter,
        windows_lan_root=windows_lan_root,
        linux_cmd_wrapper_path=linux_cmd_wrapper_path,
        windows_sync_firewall_script_path=windows_sync_firewall_script_path,
        linux_sync_firewall_script_path=linux_sync_firewall_script_path,
        windows_private_network_script_path=windows_private_network_script_path,
        settings_path=settings_path,
        default_extra_sync_items_path=default_extra_sync_items_path,
        optional_extra_sync_items_path=optional_extra_sync_items_path,
        feature_flags_path=feature_flags_path,
        update_manifest_path=update_manifest_path,
        windows_updater_script_path=windows_updater_script_path,
        linux_updater_script_path=linux_updater_script_path,
        launcher_ini_url=launcher_ini_url,
        launcher_ini_poll_seconds=launcher_ini_poll_seconds,
        launcher_request_timeout_seconds=launcher_request_timeout_seconds,
        launcher_stats_interval_seconds=launcher_stats_interval_seconds,
        game_index_url=game_index_url,
        game_index_cache_path=game_index_cache_path,
        game_index_request_timeout_seconds=game_index_request_timeout_seconds,
        game_index_refresh_seconds=game_index_refresh_seconds,
    )
