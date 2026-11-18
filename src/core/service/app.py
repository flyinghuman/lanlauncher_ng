"""Application lifecycle wiring."""

from __future__ import annotations

import base64
import ctypes
import hashlib
import http.client
import json
import logging
import math
import os
import platform
import shlex
import re
import secrets
import shutil
import sqlite3
import subprocess
import tempfile
import time
import uuid
from contextlib import closing
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from threading import Event, Lock, Thread
from urllib.parse import urlencode, urlparse
from urllib.request import urlopen

from src.core.api.server import create_server
from src.core.catalog.importer import import_legacy_catalog
from src.core.catalog.install_support import InstallSupport
from src.core.catalog.game_index import GameIndexStore, OuisyncRepositoryAccess
from src.core.catalog.cover_download import download_cover
from src.core.catalog.lan_publish import publish_shared_games, read_game_folder_metadata
from src.core.catalog.lan_snapshot import read_snapshot
from src.core.catalog.lan_shares import InvalidLanShares, LanShareStore
from src.core.catalog.lan_settings import (
    InvalidLanSettings,
    display_links as lan_settings_display_links,
    new_settings as new_lan_settings,
    publish_settings as publish_lan_settings,
    read_settings as read_lan_settings,
)
from src.core.catalog.metadata import GameMetadata, MetadataStore
from src.core.catalog.repository import CatalogRepository, ListQuery
from src.core.catalog.scanner import InstallStateScanner
from src.core.config.loader import AppConfig
from src.core.db.store import Database, open_database
from src.core.launcher.game_manager import GameActionResult, GameLifecycleManager
from src.core.platform.base import PlatformAdapter
from src.core.platform.factory import create_platform_adapter
from src.core.platform.browser import close_browser_app_mode
from src.core.service.feature_flags import FeatureFlags, load_feature_flags
from src.core.service.launcher_site import (
    DEFAULT_LAUNCHER_INI_URL,
    LauncherSiteSnapshot,
    build_snapshot_from_ini,
    default_snapshot,
    derive_launcher_ini_url,
    derive_stats_url,
)
from src.core.service.logging_setup import get_recent_logs, set_log_level
from src.core.service.settings_store import SettingsStore, UserSettings
from src.core.sync.router import create_dual_sync_provider
from src.core.sync.provider import NoopSyncProvider, SyncProvider, SyncStatus
from src.core.sync.resilio_provider import (
    ResilioSyncProvider,
    parse_json_with_comments,
    persist_runtime_paths as persist_resilio_runtime_paths,
)
from src.core.sync.ouisync_repository import (
    copy_repository_assets,
    game_repository_path,
    remove_repository_assets,
    validate_repository_id_not_case_colliding,
)
from src.core.sync.lan_discovery import (
    LanDiscoveryServer,
    LanPairing,
    discover_servers,
    paired_peer_addresses,
    pair_server_capabilities,
)
from src.core.tools.bundle_check import run_bundle_checks
from src.core.version import APP_VERSION

_SHA256_DIGEST_INFO_PREFIX = bytes.fromhex("3031300d060960864801650304020105000420")

# Embedded trusted public keys for update-manifest signature validation.
# Values use raw RSA modulus/exponent to avoid third-party crypto dependencies.
UPDATE_MANIFEST_PUBLIC_KEYS: dict[str, tuple[int, int]] = {
    "llng-root-2026": (
17982009649046820426200332897992525854227845369274109633089565247059446412021708567128333854820033035034594110698403419828713356512816421688671791252413810792175529256232006997742171758788201026283112426978955380851421695795641724977086872422557428052073428552480561289573401000604810395859231303406790613449391968679207897076031415904830342784629947014889749291197778802898634126831597579740505339019541714812456642322832441724040854549393299683548638938792448343588873963086056687831803795648817208132953235516421958895853920864171909577959462565543150359333471055678520456743353205431163874505662231839767347594027,
        65537,
    ),
}
DEFAULT_LINUX_INSTALL_PATH = "/media/library"
DEFAULT_WINDOWS_UNRAR_PATH = Path("vendor/bin/windows-amd64/unrar.exe")
WINETRICKS_COMMON_PACKAGE_IDS = (
    "d3dx9",
    "vcrun2008",
    "vcrun2010",
    "xact",
    "corefonts",
)
GAME_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
OUISYNC_INSTALL_INTERRUPTED = "ouisync_install_interrupted"
OUISYNC_DOWNLOAD_RESUME_RETRY_SECONDS = 60.0
OUISYNC_DOWNLOAD_RESUME_RETRY_MAX_SECONDS = 900.0
WINETRICKS_PACKAGE_OPTIONS = (
    {"id": "binkw32", "category": "media"},
    {"id": "cmd", "category": "system"},
    {"id": "cnc_ddraw", "category": "graphics"},
    {"id": "corefonts", "category": "fonts"},
    {"id": "crypt32_winxp", "category": "system"},
    {"id": "d2gl", "category": "graphics"},
    {"id": "d3dx10_43", "category": "graphics"},
    {"id": "d3dx9", "category": "graphics"},
    {"id": "directplay", "category": "network"},
    {"id": "directshow", "category": "media"},
    {"id": "dmusic", "category": "audio"},
    {"id": "dotnet35sp1", "category": "dotnet"},
    {"id": "dotnet48", "category": "dotnet"},
    {"id": "dsound", "category": "audio"},
    {"id": "dxdiag", "category": "system"},
    {"id": "dxvk", "category": "graphics"},
    {"id": "vcrun2005", "category": "runtime"},
    {"id": "vcrun2008", "category": "runtime"},
    {"id": "vcrun2010", "category": "runtime"},
    {"id": "vcrun2012", "category": "runtime"},
    {"id": "vcrun2013", "category": "runtime"},
    {"id": "vcrun2015", "category": "runtime"},
    {"id": "vcrun2017", "category": "runtime"},
    {"id": "vcrun2019", "category": "runtime"},
    {"id": "vcrun2022", "category": "runtime"},
    {"id": "xact", "category": "audio"},
    {"id": "3dmark05", "category": "benchmark"},
)
WINETRICKS_ALLOWED_PACKAGE_IDS = frozenset(
    option["id"] for option in WINETRICKS_PACKAGE_OPTIONS
)


def _coerce_game_provider_type(raw: object) -> str:
    value = str(raw or "").strip().lower()
    if value == "syncthing":
        return "ouisync"
    if value in {"resilio", "ouisync", "local"}:
        return value
    return "ouisync"


def _normalize_sync_provider_type(raw: object) -> str | None:
    value = str(raw or "").strip().lower()
    if value == "syncthing":
        return "ouisync"
    if value in {"resilio", "ouisync"}:
        return value
    return None


@dataclass(frozen=True)
class LocalDiskIoSample:
    timestamp: float
    read_bytes: int
    write_bytes: int


@dataclass(frozen=True)
class _LinuxMountPoint:
    major: int
    minor: int
    mount_point: Path


def _read_posix_process_io_sample(
    pid: int | None = None,
    proc_root: Path = Path("/proc"),
) -> LocalDiskIoSample | None:
    io_path = proc_root / "self" / "io" if pid is None else proc_root / str(pid) / "io"
    if not io_path.exists() or not io_path.is_file():
        return None
    read_bytes = 0
    write_bytes = 0
    try:
        for raw_line in io_path.read_text(
            encoding="utf-8", errors="replace"
        ).splitlines():
            key, separator, value = raw_line.partition(":")
            if separator != ":":
                continue
            amount = int(value.strip() or "0")
            if key.strip() == "read_bytes":
                read_bytes = max(0, amount)
            elif key.strip() == "write_bytes":
                write_bytes = max(0, amount)
    except OSError:
        return None
    except ValueError:
        return None
    return LocalDiskIoSample(time.monotonic(), read_bytes, write_bytes)


def _unescape_linux_mountinfo_path(raw: str) -> str:
    return (
        raw.replace("\\040", " ")
        .replace("\\011", "\t")
        .replace("\\012", "\n")
        .replace("\\134", "\\")
    )


def _read_linux_mountinfo_entries(
    mountinfo_path: Path = Path("/proc/self/mountinfo"),
) -> list[_LinuxMountPoint]:
    if not mountinfo_path.exists() or not mountinfo_path.is_file():
        return []
    entries: list[_LinuxMountPoint] = []
    try:
        lines = mountinfo_path.read_text(
            encoding="utf-8", errors="replace"
        ).splitlines()
    except OSError:
        return []
    for raw_line in lines:
        pre, separator, _post = raw_line.partition(" - ")
        if not separator:
            continue
        fields = pre.split()
        if len(fields) < 5:
            continue
        major_minor = fields[2]
        mount_point_raw = fields[4]
        if ":" not in major_minor:
            continue
        major_raw, minor_raw = major_minor.split(":", 1)
        try:
            major = int(major_raw)
            minor = int(minor_raw)
        except ValueError:
            continue
        entries.append(
            _LinuxMountPoint(
                major=major,
                minor=minor,
                mount_point=Path(_unescape_linux_mountinfo_path(mount_point_raw)),
            )
        )
    return entries


def _read_linux_block_device_io_sample(
    library_path: str | Path,
    mountinfo_path: Path = Path("/proc/self/mountinfo"),
    sys_dev_block_root: Path = Path("/sys/dev/block"),
) -> LocalDiskIoSample | None:
    target_path = Path(library_path).expanduser().resolve(strict=False)
    mount_entries = _read_linux_mountinfo_entries(mountinfo_path)
    best_entry: _LinuxMountPoint | None = None
    best_length = -1
    for entry in mount_entries:
        try:
            target_path.relative_to(entry.mount_point)
        except ValueError:
            continue
        mount_length = len(str(entry.mount_point))
        if mount_length > best_length:
            best_entry = entry
            best_length = mount_length
    if best_entry is None:
        return None
    stat_path = sys_dev_block_root / f"{best_entry.major}:{best_entry.minor}" / "stat"
    if not stat_path.exists() or not stat_path.is_file():
        return None
    try:
        fields = stat_path.read_text(encoding="utf-8", errors="replace").split()
    except OSError:
        return None
    if len(fields) < 7:
        return None
    try:
        read_sectors = max(0, int(fields[2]))
        write_sectors = max(0, int(fields[6]))
    except ValueError:
        return None
    # Linux reports block-device sectors in 512-byte units.
    return LocalDiskIoSample(
        time.monotonic(),
        read_sectors * 512,
        write_sectors * 512,
    )


class _IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_ulonglong),
        ("WriteOperationCount", ctypes.c_ulonglong),
        ("OtherOperationCount", ctypes.c_ulonglong),
        ("ReadTransferCount", ctypes.c_ulonglong),
        ("WriteTransferCount", ctypes.c_ulonglong),
        ("OtherTransferCount", ctypes.c_ulonglong),
    ]


def _read_windows_process_io_sample() -> LocalDiskIoSample | None:
    try:
        kernel32 = ctypes.windll.kernel32
    except AttributeError:
        return None
    counters = _IO_COUNTERS()
    process_handle = kernel32.GetCurrentProcess()
    success = kernel32.GetProcessIoCounters(
        process_handle,
        ctypes.byref(counters),
    )
    if not success:
        return None
    return LocalDiskIoSample(
        time.monotonic(),
        int(counters.ReadTransferCount),
        int(counters.WriteTransferCount),
    )


def collect_local_disk_io_sample(
    library_path: str | Path | None = None,
    process_pid: int | None = None,
) -> LocalDiskIoSample | None:
    platform_name = os.name.lower()
    if platform_name == "nt":
        return _read_windows_process_io_sample()
    if platform_name == "posix":
        # Prefer the library-backed block device so the metric reflects actual
        # storage activity instead of only the sync process's direct file I/O.
        if library_path is not None:
            sample = _read_linux_block_device_io_sample(library_path)
            if sample is not None:
                return sample
        if process_pid is not None and process_pid > 0:
            sample = _read_posix_process_io_sample(process_pid)
            if sample is not None:
                return sample
        return _read_posix_process_io_sample()
    return None


def calculate_local_disk_metrics(
    previous: LocalDiskIoSample | None, current: LocalDiskIoSample | None
) -> dict[str, int]:
    if previous is None or current is None:
        return {
            "disk_read_bps": 0,
            "disk_write_bps": 0,
            "disk_total_bps": 0,
            "disk_activity_bps": 0,
        }
    elapsed = current.timestamp - previous.timestamp
    if elapsed <= 0:
        return {
            "disk_read_bps": 0,
            "disk_write_bps": 0,
            "disk_total_bps": 0,
            "disk_activity_bps": 0,
        }
    read_delta = max(0, current.read_bytes - previous.read_bytes)
    write_delta = max(0, current.write_bytes - previous.write_bytes)
    read_bps = int(read_delta / elapsed)
    write_bps = int(write_delta / elapsed)
    return {
        "disk_read_bps": max(0, read_bps),
        "disk_write_bps": max(0, write_bps),
        "disk_total_bps": max(0, read_bps + write_bps),
        "disk_activity_bps": max(0, read_bps + write_bps),
    }


def default_linux_install_path(platform_name: str, configured_library_path: str) -> str:
    """Return Linux wizard/settings default path without changing config defaults."""
    if platform_name == "linux":
        return DEFAULT_LINUX_INSTALL_PATH
    return configured_library_path


def discover_steam_proton_binaries(home_path: Path | None = None) -> tuple[str, str]:
    root = (home_path or Path.home()).expanduser()

    steam_common_roots = [
        root / ".steam" / "steam" / "steamapps" / "common",
        root / ".steam" / "root" / "steamapps" / "common",
        root / ".local" / "share" / "Steam" / "steamapps" / "common",
        root
        / ".var"
        / "app"
        / "com.valvesoftware.Steam"
        / ".local"
        / "share"
        / "Steam"
        / "steamapps"
        / "common",
    ]
    steam_ge_roots = [
        root / ".steam" / "root" / "compatibilitytools.d",
        root / ".steam" / "steam" / "compatibilitytools.d",
        root / ".local" / "share" / "Steam" / "compatibilitytools.d",
        root
        / ".var"
        / "app"
        / "com.valvesoftware.Steam"
        / ".local"
        / "share"
        / "Steam"
        / "compatibilitytools.d",
    ]

    def _select_best_proton(roots: list[Path], matcher) -> str:
        candidates: list[tuple[int, tuple[int, ...], int, float, str]] = []
        seen_paths: set[Path] = set()
        for scan_root in roots:
            if not scan_root.exists() or not scan_root.is_dir():
                continue
            try:
                entries = list(scan_root.iterdir())
            except OSError:
                continue
            for tool_dir in entries:
                if not tool_dir.is_dir():
                    continue
                label = tool_dir.name.strip()
                normalized_label = label.lower()
                if not matcher(normalized_label):
                    continue
                script = tool_dir / "proton"
                if not script.exists() or not script.is_file():
                    continue
                try:
                    canonical = script.resolve()
                except OSError:
                    canonical = script
                if canonical in seen_paths:
                    continue
                seen_paths.add(canonical)
                version_tokens = tuple(
                    int(chunk) for chunk in re.findall(r"\d+", normalized_label)
                )
                has_version = 1 if version_tokens else 0
                is_experimental = 0 if "experimental" in normalized_label else 1
                try:
                    mtime = script.stat().st_mtime
                except OSError:
                    mtime = 0.0
                candidates.append(
                    (
                        has_version,
                        version_tokens,
                        is_experimental,
                        mtime,
                        str(script),
                    )
                )
        if not candidates:
            return ""
        # Prefer versioned tool dirs, then highest parsed version, then non-experimental.
        candidates.sort(reverse=True)
        return candidates[0][4]

    proton_path = _select_best_proton(
        steam_common_roots,
        lambda label: (
            label.startswith("proton")
            and "ge-proton" not in label
            and not label.startswith("proton-ge")
        ),
    )
    proton_ge_path = _select_best_proton(
        steam_ge_roots,
        lambda label: "ge-proton" in label or label.startswith("proton-ge"),
    )
    return proton_path, proton_ge_path


def apply_linux_proton_autodiscovery(
    settings: UserSettings,
    platform_name: str,
    home_path: Path | None = None,
) -> tuple[UserSettings, bool]:
    if str(platform_name or "").strip().lower() != "linux":
        return settings, False
    proton_path, proton_ge_path = discover_steam_proton_binaries(home_path)
    merged = settings
    changed = False
    if not merged.linux_proton_path and proton_path:
        merged = replace(merged, linux_proton_path=proton_path)
        changed = True
    if not merged.linux_proton_ge_path and proton_ge_path:
        merged = replace(merged, linux_proton_ge_path=proton_ge_path)
        changed = True
    return merged, changed


def runtime_requirements_hint(platform_name: str) -> str:
    normalized = str(platform_name or "").strip().lower()
    if normalized == "linux":
        return (
            "runtime_dependency_hint: install system packages for full functionality: "
            "python3, unrar, and a terminal emulator "
            "(konsole, gnome-terminal, xfce4-terminal, xterm, or x-terminal-emulator). "
            "For Windows-scripted games also install wine, winetricks, and/or proton."
        )
    return (
        "runtime_dependency_hint: install system packages for full functionality: "
        "python3 and unrar; interactive terminal emulators are mainly required on Linux."
    )


def local_docs_file_url(base_path: Path | None = None) -> str:
    target = (base_path or Path.cwd()) / "site" / "index.html"
    try:
        resolved = target.resolve(strict=False)
    except OSError:
        return ""
    if not resolved.exists() or not resolved.is_file():
        return ""
    try:
        return resolved.as_uri()
    except ValueError:
        return ""


def local_docs_file_path(base_path: Path | None = None) -> str:
    target = (base_path or Path.cwd()) / "site" / "index.html"
    try:
        resolved = target.resolve(strict=False)
    except OSError:
        return ""
    if not resolved.exists() or not resolved.is_file():
        return ""
    return str(resolved)


@dataclass
class AppState:
    config: AppConfig
    database: Database | None = None
    repository: CatalogRepository | None = None
    install_support: InstallSupport | None = None
    scanner: InstallStateScanner | None = None
    sync_provider: SyncProvider | None = None
    platform_adapter: PlatformAdapter | None = None
    game_manager: GameLifecycleManager | None = None
    settings_store: SettingsStore | None = None
    user_settings: UserSettings | None = None
    sync_watchdog_thread: Thread | None = None
    sync_watchdog_stop: Event | None = None
    legacy_db_watchdog_thread: Thread | None = None
    legacy_db_watchdog_stop: Event | None = None
    runtime_db_last_imported_signatures: dict[str, tuple[str, int, int]] | None = None
    runtime_db_last_failed_signatures: dict[str, tuple[str, int, int]] | None = None
    lan_index_last_signature: tuple[str, int, int] | None = None
    lan_settings_last_signature: tuple[str, int, int] | None = None
    lan_settings_failed_signature: tuple[str, int, int] | None = None
    rescan_sync_thread: Thread | None = None
    rescan_sync_lock: Lock | None = None
    rescan_sync_progress: dict | None = None
    install_retry_after: dict[str, float] | None = None
    install_failed_archive_signatures: dict[str, tuple[str, int, int]] | None = None
    install_console_lines: dict[str, list[str]] | None = None
    install_console_lock: Lock | None = None
    shutdown_update_state: dict | None = None
    shutdown_update_lock: Lock | None = None
    shutdown_update_thread: Thread | None = None
    launcher_site_thread: Thread | None = None
    launcher_site_stop: Event | None = None
    launcher_site_lock: Lock | None = None
    launcher_site_snapshot: LauncherSiteSnapshot | None = None
    lan_settings_snapshot: dict | None = None
    lan_settings_lock: Lock | None = None
    stats_report_inflight: bool = False
    stats_report_last_sent_at: float = 0.0
    log_timeline_cache: list[dict] | None = None
    log_timeline_cache_limit: int = 0
    log_timeline_cache_updated_at: float = 0.0
    log_timeline_lock: Lock | None = None
    ouisync_seed_reconcile_next_at: float = 0.0
    current_game_id: str = ""
    desired_sync_running: bool = False
    sync_watchdog_paused: bool = False
    sync_watchdog_last_restart_at: float = 0.0
    metadata_root: Path = Path.cwd() / "metadata"
    metadata_store: MetadataStore | None = None
    local_metadata_stores: dict[str, MetadataStore] | None = None
    game_index_store: GameIndexStore | None = None
    started: bool = False


class Application:
    def __init__(self, config: AppConfig):
        self._config = config
        self._feature_flags: FeatureFlags = load_feature_flags(
            config.feature_flags_path
        )
        self._shutdown = Event()
        self._stopped = False
        self._stop_lock = Lock()
        self._state = AppState(config=config)
        self._state.metadata_root = self._metadata_root_path()
        self._state.metadata_store = MetadataStore(self._state.metadata_root)
        self._state.local_metadata_stores = {}
        self._state.game_index_store = GameIndexStore(
            index_url=self._config.game_index_url,
            cache_path=self._config.game_index_cache_path,
            request_timeout_seconds=self._config.game_index_request_timeout_seconds,
            refresh_seconds=self._config.game_index_refresh_seconds,
            local_index_path=(
                Path(self._config.library_path)
                / "ng_provider"
                / "update"
                / "index.json"
            ),
            trust_state_path=(
                Path(self._config.db_path).resolve(strict=False).parent
                / "publisher-trust-state.json"
            ),
        )
        self._provider_image_archive_cache: dict[str, tuple[int, float, bool]] = {}
        self._provider_image_archive_cache_lock = Lock()
        self._sync_metrics_lock = Lock()
        self._sync_metrics_disk_sample: LocalDiskIoSample | None = None
        self._lan_discovery: LanDiscoveryServer | None = None
        self._lan_discovery_retry_at = 0.0
        self._lan_catalog_refresh_after = 0.0
        # game_id -> (next allowed resume attempt, current retry delay)
        self._ouisync_download_resume: dict[str, tuple[float, float]] = {}
        self._lan_state_dir = (
            Path(config.db_path).expanduser().resolve(strict=False).parent / "lan"
        )
        self._lan_shares = LanShareStore(self._lan_state_dir / "shared-games.json")
        self._lan_pairing = LanPairing(
            self._lan_pairing_server_id,
            self._lan_pairing_issue_capabilities,
            storage=self._lan_state_dir / "pairing.json",
        )
        self._server = create_server(
            config.bind_host,
            config.bind_port,
            self._is_started,
            self._get_repo,
            self._scan_install_state,
            self._rescan_start,
            self._rescan_status,
            self._sync_status,
            self._sync_metrics,
            self._sync_start,
            self._sync_stop,
            self._platform_info,
            self._available_storage_locations,
            self._winetricks_packages_read,
            self._install_prerequisites_bundle,
            self._install_wine_common_dependencies,
            self._install_game_proton_common_dependencies,
            self._manage_game_prefix_wine_dependencies,
            self._save_game_metadata_file,
            self._local_game_settings_update,
            self._set_resilio_network_mode,
            self._set_local_network_private,
            self._validate_storage,
            self._open_folder,
            self._install_script_info,
            self._game_action,
            self._game_launch_settings_read,
            self._game_launch_settings_update,
            self._game_sync_status,
            self._game_sync_start,
            self._game_sync_stop,
            self._game_video_path,
            self._game_image_path,
            self._settings_read,
            self._launcher_site_read,
            self._disabled_game_ids,
            self._is_game_disabled,
            self._settings_update,
            self._extra_sync_items_read,
            self._extra_sync_item_upsert,
            self._extra_sync_item_toggle,
            self._extra_sync_item_refresh_images,
            self._extra_sync_item_delete,
            self._extra_sync_item_delete_data,
            self._extra_sync_item_wipe,
            self._app_log_level_update,
            self._logs_read,
            self._debug_logs_read,
            self._app_shutdown_request,
            self._app_shutdown_prepare,
            self._app_shutdown_apply,
            self._app_shutdown_status,
            self._app_shutdown_finalize,
            self._app_update_check,
            self._app_update_rollback,
            self._app_feature_flags_read,
            self._sync_metrics_for_game,
            self._provider_interfaces_payload,
            self._sync_provider_action,
            self._lan_game_inventory_read,
            self._lan_game_share_update,
            self._game_visibility_update,
            self._lan_server_game_inventory_read,
            self._lan_server_settings_update,
            self._lan_server_settings_read,
            self._lan_disabled_game_ids,
            self._ouisync_repository_inventory_read,
            self._ouisync_debug_action,
            self._ouisync_repository_settings_update,
            self._ouisync_repository_action,
            self._ouisync_repository_entry_copy,
            self._extra_sync_items_import_bootstrap,
            self._ouisync_peer_action,
        )

    def _is_started(self) -> bool:
        return self._state.started

    def _get_repo(self) -> CatalogRepository | None:
        return self._state.repository

    def _resolve_game_provider_type(self, game_id: str) -> str | None:
        if not game_id:
            return None
        if self._state.repository is not None:
            try:
                game = self._state.repository.get_game(game_id, locale="en")
            except Exception:  # noqa: BLE001
                game = None
            if isinstance(game, dict):
                provider_type = _coerce_game_provider_type(
                    game.get("game_provider_type", "")
                )
                if provider_type:
                    return provider_type
                metadata = game.get("metadata")
                if isinstance(metadata, dict):
                    catalog = metadata.get("catalog")
                    if isinstance(catalog, dict):
                        provider_type = _coerce_game_provider_type(
                            catalog.get("game_provider_type", "")
                        )
                        if provider_type:
                            return provider_type
                    provider_type = _coerce_game_provider_type(
                        metadata.get("game_provider_type", "")
                    )
                    if provider_type:
                        return provider_type
        return None

    def _is_lan_catalog_game(self, game_id: str) -> bool:
        lookup = getattr(self._state.repository, "game_id_records", None)
        ownership = lookup(game_id) if callable(lookup) else None
        source = ownership.get("lan_source") if isinstance(ownership, dict) else ""
        return isinstance(source, str) and bool(source)

    def _sync_provider_for_game(self, game_id: str):
        provider = self._state.sync_provider
        if provider is None:
            return None
        provider_for_game = getattr(provider, "provider_for_game", None)
        if callable(provider_for_game):
            return provider_for_game(game_id)
        return provider

    def _sync_provider_for_game_payload(self, game: dict | None):
        game_id = str((game or {}).get("id", "") or "").strip()
        provider_type = _coerce_game_provider_type(
            (game or {}).get("game_provider_type", "")
        )
        provider = self._state.sync_provider
        if provider is None:
            return None
        provider_for_type = getattr(provider, "provider_for_type", None)
        if callable(provider_for_type):
            if provider_type:
                return provider_for_type(provider_type)
            if game_id:
                return provider_for_type(self._resolve_game_provider_type(game_id))
        if game_id:
            return self._sync_provider_for_game(game_id)
        return provider

    def _sync_provider_for_type(self, provider_type: str | None):
        provider = self._state.sync_provider
        if provider is None:
            return None
        provider_for_type = getattr(provider, "provider_for_type", None)
        if callable(provider_for_type):
            try:
                provider = provider_for_type(provider_type)
            except Exception as exc:  # noqa: BLE001
                logging.getLogger(__name__).warning(
                    "sync_provider_resolve_failed provider=%s error=%s",
                    provider_type,
                    exc,
                )
                return None
        # The router falls back to Resilio for unknown types. Ouisync-specific
        # actions (reset, mount, inventory) must never run against Resilio.
        if str(provider_type or "").strip().lower() == "ouisync" and isinstance(
            provider, (ResilioSyncProvider, NoopSyncProvider)
        ):
            return None
        return provider

    def _lan_mode(self) -> str:
        if self._state.user_settings is None:
            return "client"
        value = str(self._state.user_settings.lan_mode or "").strip().lower()
        return "server" if value == "server" else "client"

    def _ouisync_game_repository_path(self, game_id: str) -> Path:
        """Resolve the current path or retain an existing repository at its old root."""
        library = (
            Path(self._effective_library_path()).expanduser().resolve(strict=False)
        )
        settings = self._state.user_settings
        configured = getattr(settings, "ouisync_storage_path", "") if settings else ""
        roots = [
            Path(configured).expanduser().resolve(strict=False)
            if str(configured or "").strip()
            else library
        ]
        roots.extend(
            Path(value).expanduser().resolve(strict=False)
            for value in reversed(
                getattr(settings, "ouisync_storage_fallback_paths", []) or []
            )
            if str(value or "").strip()
        )
        roots.append(library)
        candidates: list[Path] = []
        for root in roots:
            candidate = game_repository_path(library, game_id, root)
            if candidate not in candidates:
                candidates.append(candidate)
        target = candidates[0]
        for candidate in candidates:
            if candidate.exists() or Path(f"{candidate}.ouisyncdb").exists():
                return candidate
        legacy_root = library / game_id / ".ouisync"
        for name in ("repository", "lan-repository"):
            legacy = legacy_root / name
            if legacy.exists() or Path(f"{legacy}.ouisyncdb").exists():
                return legacy
        return target

    def _ouisync_game_access(self, game_id: str) -> OuisyncRepositoryAccess | None:
        if self._is_lan_catalog_game(game_id):
            lookup = getattr(self._state.repository, "lan_game_ouisync_access", None)
            return lookup(game_id) if callable(lookup) else None
        index_store = self._state.game_index_store
        return (
            index_store.ouisync_repository_access(game_id)
            if index_store is not None
            else None
        )

    def _ouisync_lan_repository_path(self, folder_path: str) -> Path:
        folder = Path(folder_path).expanduser().resolve(strict=False)
        settings = self._state.user_settings
        storage_root = getattr(settings, "ouisync_storage_path", "") if settings else ""
        roots = [
            Path(storage_root).expanduser().resolve(strict=False)
            if str(storage_root or "").strip()
            else folder.parent
        ]
        roots.extend(
            Path(value).expanduser().resolve(strict=False)
            for value in reversed(
                getattr(settings, "ouisync_storage_fallback_paths", []) or []
            )
            if str(value or "").strip()
        )
        roots.append(folder.parent)
        for root in roots:
            validate_repository_id_not_case_colliding(root, folder.name)
        candidates = list(
            dict.fromkeys(
                root / folder.name / ".ouisync" / "lan-repository"
                for root in roots
            )
        )
        for candidate in candidates:
            if candidate.exists() or Path(f"{candidate}.ouisyncdb").exists():
                return candidate
        return candidates[0]

    def _lan_game_inventory_read(self, *, server_role_preview: bool = False) -> dict:
        root = Path(self._effective_library_path()).expanduser().resolve(strict=False)
        selected_role = self._lan_mode()
        try:
            shared_ids = {value.casefold() for value in self._lan_shares.read()}
            repo = self._state.repository
            if (server_role_preview or selected_role == "server") and repo is None:
                raise ValueError("repository_unavailable")
            is_server_inventory = server_role_preview or selected_role == "server"
            excluded = (
                repo.non_lan_share_game_ids()
                if repo is not None and is_server_inventory
                else set()
            )
            children = (
                sorted(
                    (item for item in root.iterdir() if item.is_dir()),
                    key=lambda item: item.name.casefold(),
                )
                if root.is_dir()
                else []
            )
        except (OSError, InvalidLanShares, ValueError, sqlite3.Error, RuntimeError):
            logging.getLogger(__name__).warning("lan_game_inventory_unavailable")
            return {
                "root_path": str(root),
                "folders": [],
                "message": "lan_game_inventory_unavailable",
            }
        folders: list[dict] = []
        for child in children:
            game_id = child.name
            if (
                not GAME_ID_RE.fullmatch(game_id)
                or game_id.casefold() in {"locallansync", "ng_provider"}
                or child.name.casefold() in excluded
            ):
                continue
            folder = {
                "name": game_id,
                "path": str(child.resolve(strict=False)),
                "shared": game_id.casefold() in shared_ids,
                "configured": game_id.casefold() in shared_ids,
                "paused": game_id.casefold() not in shared_ids,
                "type": "sendonly" if game_id.casefold() in shared_ids else "local",
            }
            try:
                metadata_file, metadata = read_game_folder_metadata(child)
                folder["metadata_available"] = metadata_file is not None
                folder["metadata"] = metadata
            except (OSError, ValueError, KeyError):
                folder["metadata_available"] = False
                folder["metadata_invalid"] = True
            folders.append(folder)
        return {"root_path": str(root), "folders": folders}

    def _lan_server_game_inventory_read(self) -> dict:
        return self._lan_game_inventory_read(server_role_preview=True)

    def _lan_game_share_update(self, payload: dict) -> dict:
        if payload.get("action") == "download_cover":
            if self._lan_mode() != "server":
                return {"ok": False, "message": "server_mode_required"}
            try:
                mime, data = download_cover(str(payload.get("url") or "").strip())
            except (OSError, ValueError, UnicodeError, http.client.HTTPException):
                return {"ok": False, "message": "lan_cover_download_failed"}
            return {
                "ok": True,
                "message": "ok",
                "data_url": f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}",
            }
        pairing_action = payload.get("action")
        if pairing_action in {"begin_pairing", "renew_pairing"}:
            if self._lan_mode() != "server":
                return {"ok": False, "message": "lan_server_mode_required"}
            try:
                if self._lan_discovery is None or not self._lan_pairing_server_id():
                    return {"ok": False, "message": "lan_pair_unavailable"}
            except Exception:
                return {"ok": False, "message": "lan_pair_unavailable"}
            try:
                code = (
                    self._lan_pairing.renew()
                    if pairing_action == "renew_pairing"
                    else self._lan_pairing.begin()
                )
            except OSError:
                return {"ok": False, "message": "lan_pair_unavailable"}
            return {
                "ok": True,
                "message": "ok",
                "code": code,
                "expires_in": self._lan_pairing.remaining(),
            }
        if payload.get("action") == "pair_server":
            if self._lan_mode() != "client":
                return {"ok": False, "message": "lan_client_mode_required"}
            try:
                server_id = str(payload.get("device_id") or "")
                client_id = self._lan_device_id()
                ouisync_provider = self._sync_provider_for_type("ouisync")
                listener_addrs = getattr(
                    ouisync_provider, "network_listener_addrs", None
                )
                client_peer_addrs = listener_addrs() if callable(listener_addrs) else []
                capabilities = pair_server_capabilities(
                    str(payload.get("address") or ""),
                    server_id,
                    client_id,
                    str(payload.get("code") or ""),
                    peer_addrs=client_peer_addrs,
                )
                if capabilities is None:
                    return {"ok": False, "message": "lan_pair_failed"}
                catalog_token = capabilities.get("catalog_token")
                catalog_hash = capabilities.get("catalog_hash")
                if isinstance(catalog_token, str) and isinstance(catalog_hash, str):
                    try:
                        peer_addrs = paired_peer_addresses(
                            capabilities, str(payload.get("address") or "").strip()
                        )
                    except ValueError:
                        return {"ok": False, "message": "lan_pair_failed"}
                    ouisync_provider = self._sync_provider_for_type("ouisync")
                    add_peers = getattr(ouisync_provider, "add_network_peers", None)
                    if callable(add_peers):
                        add_peers(peer_addrs)
                    if not self._lan_pair_access_save(
                        server_id, catalog_token, catalog_hash, peer_addrs
                    ):
                        return {"ok": False, "message": "lan_pair_failed"}
                    self._lan_catalog_refresh_after = 0.0
                    self._ouisync_lan_catalog_cycle()
                    return {"ok": True, "message": "ok"}
                return {"ok": False, "message": "lan_pair_failed"}
            except Exception:  # noqa: BLE001 - return a stable local API error
                return {"ok": False, "message": "lan_pair_failed"}
        if payload.get("action") == "discover_servers":
            if self._lan_mode() != "client":
                return {"ok": False, "message": "lan_client_mode_required"}
            try:
                servers = discover_servers(
                    target=str(payload.get("address") or "255.255.255.255").strip()
                )
            except (OSError, ValueError):
                return {"ok": False, "message": "lan_discovery_failed"}
            return {"ok": True, "message": "ok", "servers": servers}
        if payload.get("action") == "save_metadata":
            return self._save_server_folder_metadata(payload)
        folder_path = str(
            payload.get("folder_path")
            or payload.get("path")
            or payload.get("folder")
            or ""
        ).strip()
        shared_raw = payload.get("shared")
        if isinstance(shared_raw, bool):
            shared = shared_raw
        elif isinstance(shared_raw, str):
            shared = shared_raw.strip().lower() in {"1", "true", "yes", "on"}
        else:
            shared = bool(shared_raw)
        try:
            root = (
                Path(self._effective_library_path()).expanduser().resolve(strict=True)
            )
            folder = Path(folder_path).expanduser().resolve(strict=True)
            if (
                folder.parent != root
                or not folder.is_dir()
                or folder.name in {"locallansync", "ng_provider"}
            ):
                return {"ok": False, "message": "lan_game_folder_invalid"}
            game_id = folder.name
            if not GAME_ID_RE.fullmatch(game_id):
                return {"ok": False, "message": "invalid_game_id"}
            if shared and self._game_id_conflicts(
                game_id,
                allow_existing_local=True,
                allow_owned_lan=True,
            ):
                return {"ok": False, "message": "duplicate_game_id"}
            self._lan_shares.set_shared(game_id, shared)
        except (OSError, InvalidLanShares, ValueError, sqlite3.Error) as exc:
            logging.getLogger(__name__).warning(
                "lan_game_share_update_failed error=%s", exc
            )
            return {"ok": False, "message": "lan_share_update_failed"}
        return {
            "ok": True,
            "message": "lan_share_updated",
            "lan": self._lan_game_inventory_read(),
        }

    def _game_id_conflicts(
        self,
        game_id: str,
        *,
        allow_existing_local: bool = False,
        allow_existing_index: bool = False,
        allow_owned_lan: bool = False,
    ) -> bool:
        repo = self._state.repository
        if repo is None:
            raise ValueError("repository_unavailable")
        records = repo.game_id_records(game_id)
        catalog = records["catalog"]
        if records["extra"]:
            return True
        catalog_root = Path(self._effective_library_path()) / "locallansync"
        index_path = catalog_root / ".ouisync" / "index.json"
        if not index_path.is_file():
            index_path = catalog_root / "index.json"
        try:
            snapshot = read_snapshot(index_path)
        except FileNotFoundError:
            snapshot = None
        owned_lan = bool(
            allow_owned_lan
            and snapshot
            and catalog
            and catalog[0] == game_id
            and records.get("lan_source") == snapshot["source"]["id"]
        )
        if (
            catalog
            and not owned_lan
            and not (allow_existing_local and str(catalog[1] or "").lower() == "local")
        ):
            return True
        if (
            not (allow_existing_index or owned_lan)
            and snapshot
            and any(
                item["game_id"].casefold() == game_id.casefold()
                for item in snapshot["games"]
            )
        ):
            return True
        for _, path in self._resolve_runtime_update_db_sources():
            if not path.is_file():
                continue
            with closing(
                sqlite3.connect(
                    path.resolve().as_uri() + "?mode=ro", uri=True, timeout=1
                )
            ) as conn:
                if conn.execute(
                    "SELECT 1 FROM games WHERE game_id = ? COLLATE NOCASE LIMIT 1",
                    (game_id,),
                ).fetchone():
                    return True
        return False

    def _save_server_folder_metadata(self, payload: dict) -> dict:
        if self._lan_mode() != "server":
            return {"ok": False, "message": "server_mode_required"}
        item = payload.get("item")
        if not isinstance(item, dict):
            return {"ok": False, "message": "lan_metadata_invalid"}
        try:
            root = Path(self._effective_library_path()).resolve(strict=True)
            folder = Path(str(payload.get("folder_path") or "")).resolve(strict=True)
            if (
                folder.parent != root
                or not folder.is_dir()
                or folder.name == "locallansync"
            ):
                return {"ok": False, "message": "lan_game_folder_invalid"}
            game_id = folder.name
            if not GAME_ID_RE.fullmatch(game_id) or game_id in {".", ".."}:
                return {"ok": False, "message": "invalid_game_id"}
            metadata_file, metadata = read_game_folder_metadata(folder)
            records = (
                self._state.repository.game_id_records(game_id)
                if self._state.repository
                else {}
            )
            local = records.get("catalog")
            editing_local = bool(
                metadata_file
                and local
                and local[0] == game_id
                and str(local[1] or "").lower() == "local"
            )
            try:
                collision = self._game_id_conflicts(
                    game_id,
                    allow_existing_local=editing_local,
                    allow_existing_index=editing_local,
                    allow_owned_lan=bool(metadata_file),
                )
            except (OSError, ValueError, sqlite3.Error):
                return {"ok": False, "message": "game_id_check_unavailable"}
            if collision:
                return {"ok": False, "message": "duplicate_game_id"}
            title_en = str(item.get("title_en") or "").strip()
            if not title_en:
                return {"ok": False, "message": "local_game_title_required"}
            size = float(item.get("size_gb") or 0)
            if size < 0 or not math.isfinite(size):
                return {"ok": False, "message": "local_game_size_invalid"}
            metadata = dict(metadata)
            # Sidecar image paths are relative to its metadata directory.
            if (
                metadata_file
                and metadata_file.parent != folder
                and isinstance(metadata.get("image"), str)
            ):
                old_image = metadata["image"]
                if not urlparse(old_image).scheme and not Path(old_image).is_absolute():
                    metadata["image"] = f"metadata/{old_image}"
            metadata.update(
                {
                    "game_id": game_id,
                    "title": {
                        "en": title_en,
                        "de": str(item.get("title_de") or title_en).strip(),
                    },
                    "description": {
                        "en": str(item.get("readme_en") or "").strip(),
                        "de": str(
                            item.get("readme_de") or item.get("readme_en") or ""
                        ).strip(),
                    },
                    "release_year": str(item.get("release_year") or "").strip(),
                    "publisher": str(item.get("publisher") or "").strip(),
                    "size_gb": size,
                    "max_players": str(item.get("max_players") or "").strip(),
                    "version": str(item.get("version") or "").strip(),
                }
            )
            genre = item.get("genre_id")
            if genre not in (None, "", "all"):
                metadata["genre_id"] = int(genre)
            else:
                metadata.pop("genre_id", None)
            start_file = str(item.get("game_start_file") or "").strip()
            if start_file:
                metadata["game_start"] = {
                    "file": start_file,
                    "args": self._local_game_args_to_list(item.get("game_start_args")),
                }
            else:
                metadata.pop("game_start", None)
            data_url = str(item.get("game_image_data_url") or "")
            if data_url:
                parsed = self._data_url_to_bytes(data_url)
                if (
                    not parsed
                    or parsed[0] not in {"image/jpeg", "image/png", "image/webp"}
                    or len(parsed[1]) > 10 * 1024 * 1024
                ):
                    return {"ok": False, "message": "invalid_local_game_image"}
                extension = self._mime_to_extension(parsed[0])
                image_name = (
                    f"cover-{hashlib.sha256(parsed[1]).hexdigest()[:20]}{extension}"
                )
                image_path = folder / image_name
                if not image_path.exists():
                    name = ""
                    try:
                        with tempfile.NamedTemporaryFile(
                            dir=folder, prefix=".cover-", delete=False
                        ) as tmp:
                            name = tmp.name
                            tmp.write(parsed[1])
                        os.replace(name, image_path)
                    finally:
                        if name:
                            Path(name).unlink(missing_ok=True)
                metadata.pop("image", None)
                media = (
                    metadata.get("media")
                    if isinstance(metadata.get("media"), dict)
                    else {}
                )
                metadata["media"] = {**media, "image_url": image_name}
            data = (
                json.dumps(metadata, ensure_ascii=False, indent=2, allow_nan=False)
                + "\n"
            ).encode("utf-8")
            if len(data) > 1024 * 1024:
                return {"ok": False, "message": "lan_metadata_too_large"}
            name = ""
            try:
                with tempfile.NamedTemporaryFile(
                    dir=folder, prefix=".metadata-", delete=False
                ) as tmp:
                    name = tmp.name
                    tmp.write(data)
                os.replace(name, folder / "metadata.json")
            finally:
                if name:
                    Path(name).unlink(missing_ok=True)
        except (OSError, ValueError, sqlite3.Error, TypeError):
            return {"ok": False, "message": "lan_metadata_invalid"}
        return {
            "ok": True,
            "message": "ok",
            "game_id": game_id,
            "lan": self._lan_game_inventory_read(),
        }

    def _ouisync_manage_lan_cycle(self) -> None:
        repo = self._state.repository
        if repo is None:
            return
        if self._lan_mode() != "server":
            self._ouisync_lan_catalog_cycle()
            return
        library = (
            Path(self._effective_library_path()).expanduser().resolve(strict=False)
        )
        try:
            shared_ids = self._lan_shares.read()
            shared = [
                {"id": game_id, "path": str(library / game_id)}
                for game_id in shared_ids
                if (library / game_id).is_dir()
            ]
            self._ensure_lan_server_settings()
            ouisync = self._sync_provider_for_type("ouisync")
            publish_game = getattr(ouisync, "publish_lan_game", None)
            if not callable(publish_game):
                raise RuntimeError("ouisync_lan_publisher_unavailable")

            def publisher(folder: str) -> dict:
                return publish_game(
                    folder, str(self._ouisync_lan_repository_path(folder))
                )

            publish_shared_games(library, shared, ouisync_publisher=publisher)
            publisher(str(library / "locallansync"))
            reconcile_shared = getattr(ouisync, "reconcile_lan_shared_games", None)
            if callable(reconcile_shared):
                reconcile_shared(
                    [
                        str(
                            self._ouisync_lan_repository_path(
                                str(library / "locallansync")
                            )
                        ),
                        *(
                            str(self._ouisync_lan_repository_path(folder["path"]))
                            for folder in shared
                        ),
                    ]
                )
            self._try_import_lan_catalog()
        except (
            OSError,
            InvalidLanShares,
            ValueError,
            RuntimeError,
            sqlite3.Error,
        ) as exc:
            logging.getLogger(__name__).warning(
                "ouisync_lan_catalog_publish_failed error=%s", exc
            )

    def _lan_pairing_server_id(self) -> str:
        return self._lan_device_id() if self._lan_mode() == "server" else ""

    def _lan_device_id(self) -> str:
        path = self._lan_state_dir / "device-id"
        try:
            value = path.read_text(encoding="ascii").strip()
        except (OSError, UnicodeError):
            value = ""
        if re.fullmatch(r"(?:[A-Z2-7]{7}-){7}[A-Z2-7]{7}", value):
            return value
        encoded = base64.b32encode(secrets.token_bytes(35)).decode("ascii")
        value = "-".join(encoded[index : index + 7] for index in range(0, 56, 7))
        self._lan_state_dir.mkdir(parents=True, exist_ok=True)
        temp_name = ""
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="ascii",
                dir=self._lan_state_dir,
                prefix=".device-id-",
                delete=False,
            ) as stream:
                temp_name = stream.name
                stream.write(value + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.chmod(temp_name, 0o600)
            except OSError:
                pass
            os.replace(temp_name, path)
        finally:
            if temp_name:
                Path(temp_name).unlink(missing_ok=True)
        return value

    def _lan_pairing_issue_capabilities(self, _client_id: str) -> dict | bool:
        if self._lan_mode() != "server":
            return False
        provider = self._sync_provider_for_type("ouisync")
        publish = getattr(provider, "publish_lan_game", None)
        if not callable(publish):
            return False
        try:
            catalog_folder = str(
                Path(self._effective_library_path()) / "locallansync"
            )
            capability = publish(
                catalog_folder,
                str(self._ouisync_lan_repository_path(catalog_folder)),
            )
        except (OSError, RuntimeError, ValueError):
            return False
        if not isinstance(capability, dict):
            return False
        token = capability.get("read_token")
        info_hash = capability.get("info_hash")
        if (
            not isinstance(token, str)
            or not token
            or not isinstance(info_hash, str)
            or not info_hash
        ):
            return False
        listener_addrs = getattr(provider, "network_listener_addrs", None)
        peer_addrs = listener_addrs() if callable(listener_addrs) else []
        return {
            "catalog_token": token,
            "catalog_hash": info_hash,
            "peer_addrs": peer_addrs[:4] if isinstance(peer_addrs, list) else [],
        }

    def _lan_pair_access_path(self) -> Path:
        return (
            Path(self._config.db_path).expanduser().resolve(strict=False).parent
            / "lan-paired-catalog.json"
        )

    def _lan_pair_access_read(self) -> dict | None:
        try:
            value = json.loads(self._lan_pair_access_path().read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return None
        if not isinstance(value, dict):
            return None
        token = value.get("catalog_token")
        info_hash = value.get("catalog_hash")
        server_id = value.get("server_id")
        if (
            not isinstance(token, str)
            or not token
            or token != token.strip()
            or len(token) > 8192
            or any(char.isspace() or ord(char) < 32 for char in token)
            or not isinstance(info_hash, str)
            or not info_hash
            or len(info_hash) > 256
            or any(char.isspace() or ord(char) < 32 for char in info_hash)
            or not isinstance(server_id, str)
        ):
            return None
        try:
            value["peer_addrs"] = paired_peer_addresses(
                {"known_peer_addrs": value.get("peer_addrs", [])}, "127.0.0.1"
            )
        except ValueError:
            return None
        return value

    def _lan_pair_access_save(
        self,
        server_id: str,
        catalog_token: str,
        catalog_hash: str,
        peer_addrs: list[str] | None = None,
    ) -> bool:
        try:
            peer_addrs = paired_peer_addresses(
                {"known_peer_addrs": peer_addrs or []}, "127.0.0.1"
            )
        except ValueError:
            return False
        path = self._lan_pair_access_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_name = ""
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix=".lan-paired-catalog-",
                delete=False,
            ) as stream:
                temp_name = stream.name
                json.dump(
                    {
                        "server_id": server_id,
                        "catalog_token": catalog_token,
                        "catalog_hash": catalog_hash,
                        "peer_addrs": peer_addrs,
                    },
                    stream,
                    ensure_ascii=True,
                    separators=(",", ":"),
                )
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.chmod(temp_name, 0o600)
            except OSError:
                pass
            os.replace(temp_name, path)
            return True
        except OSError:
            return False
        finally:
            if temp_name:
                Path(temp_name).unlink(missing_ok=True)

    def _ouisync_lan_catalog_cycle(self) -> None:
        access_data = self._lan_pair_access_read()
        if access_data is None:
            return
        provider = self._sync_provider_for_type("ouisync")
        add_peers = getattr(provider, "add_network_peers", None)
        peer_addrs = access_data.get("peer_addrs", [])
        if callable(add_peers) and isinstance(peer_addrs, list):
            add_peers(peer_addrs)
        status_fn = getattr(provider, "game_materialization_status", None)
        start_fn = getattr(provider, "start_game_materialization", None)
        if not callable(status_fn) or not callable(start_fn):
            return
        status = status_fn("locallansync")
        phase = str(status.get("phase", "idle")) if isinstance(status, dict) else "idle"
        if phase in {"queued", "syncing"}:
            return
        if phase == "complete":
            self._try_import_lan_catalog()
        if time.monotonic() < self._lan_catalog_refresh_after:
            return
        access = OuisyncRepositoryAccess(
            game_id="locallansync",
            read_token=access_data["catalog_token"],
            expected_info_hash=access_data["catalog_hash"],
            editable_files=(),
            # The private LAN catalog must not be announced on the public DHT.
            repository_namespace="lan-repository",
        )
        target = Path(self._effective_library_path()) / "locallansync"
        target.mkdir(parents=True, exist_ok=True)
        ok, _detail = start_fn(
            access,
            str(target),
            str(self._ouisync_game_repository_path("locallansync")),
        )
        if ok:
            self._lan_catalog_refresh_after = time.monotonic() + 60

    def _lan_discovery_info(self) -> dict | None:
        if self._lan_mode() != "server":
            return None
        return {
            "device_id": self._lan_device_id(),
            "name": self._state.user_settings.nickname
            if self._state.user_settings
            else "",
            "tcp_port": 28384,
        }

    def _refresh_lan_discovery(self) -> None:
        enabled = self._state.user_settings is not None and self._lan_mode() == "server"
        if not enabled and self._lan_discovery is not None:
            self._lan_discovery.close()
            self._lan_discovery = None
        elif (
            enabled
            and self._lan_discovery is None
            and time.monotonic() >= self._lan_discovery_retry_at
        ):
            server = None
            try:
                server = LanDiscoveryServer(
                    self._lan_discovery_info, pairing=self._lan_pairing
                )
                server.start()
                self._lan_discovery = server
            except (OSError, RuntimeError) as exc:
                if server is not None:
                    server.close()
                self._lan_discovery_retry_at = time.monotonic() + 30
                logging.getLogger(__name__).warning(
                    "lan_discovery_start_failed error=%s", exc
                )

    def _sync_status_payload(self, status: SyncStatus) -> dict:
        return {
            "provider": status.provider,
            "running": status.running,
            "state": status.state,
            "pid": status.pid,
            "last_error": status.last_error,
        }

    def _is_shutdown_update_finalize_pending(self) -> bool:
        with self._shutdown_update_lock():
            state = self._state.shutdown_update_state or {}
            if not bool(state.get("will_apply_update", False)):
                return False
            phase = str(state.get("phase", "")).strip().lower()
            return phase in {"done", "failed"}

    def _scan_install_state(self, force: bool) -> dict:
        if self._state.scanner is None:
            return {"scanned": 0, "installed": 0, "missing": 0}
        if self._is_shutdown_update_finalize_pending():
            # After swap, old DB handles can point to moved backup paths.
            # Keep shutdown-finalize phase read-only and avoid write attempts.
            logging.getLogger(__name__).info(
                "scan_install_state_skipped_during_finalize_pending"
            )
            return {"scanned": 0, "installed": 0, "missing": 0}
        try:
            stats = self._state.scanner.scan(force=force)
        except sqlite3.OperationalError as exc:
            if "readonly" in str(exc).lower():
                logging.getLogger(__name__).warning(
                    "scan_install_state_readonly_skipped error=%s", exc
                )
                return {"scanned": 0, "installed": 0, "missing": 0}
            raise
        return {
            "scanned": stats.scanned,
            "installed": stats.installed,
            "missing": stats.missing,
        }

    def _rescan_status_payload(self) -> dict:
        progress = self._state.rescan_sync_progress or {}
        total = int(progress.get("total", 0) or 0)
        processed = int(progress.get("processed", 0) or 0)
        percent = 100 if total <= 0 else int((processed * 100) / total)
        return {
            "running": bool(progress.get("running", False)),
            "phase": str(progress.get("phase", "idle") or "idle"),
            "total": total,
            "processed": processed,
            "added": int(progress.get("added", 0) or 0),
            "skipped": int(progress.get("skipped", 0) or 0),
            "failed": int(progress.get("failed", 0) or 0),
            "percent": max(0, min(100, percent)),
            "current_game_id": str(progress.get("current_game_id", "") or ""),
            "current_title": str(progress.get("current_title", "") or ""),
            "message": str(progress.get("message", "") or ""),
        }

    def _rescan_status(self) -> dict:
        return self._rescan_status_payload()

    def _rescan_start(self, force: bool) -> dict:
        scan = self._scan_install_state(force)
        self._ensure_resilio_folder_sync_rescan()
        return {"scan": scan, "resync": self._rescan_status_payload()}

    def _ensure_resilio_folder_sync_rescan(self) -> None:
        if self._state.rescan_sync_lock is None:
            self._state.rescan_sync_lock = Lock()
        if self._state.rescan_sync_progress is None:
            self._state.rescan_sync_progress = {
                "running": False,
                "phase": "idle",
                "total": 0,
                "processed": 0,
                "added": 0,
                "skipped": 0,
                "failed": 0,
                "current_game_id": "",
                "current_title": "",
                "message": "",
            }

        with self._state.rescan_sync_lock:
            thread = self._state.rescan_sync_thread
            if thread is not None and thread.is_alive():
                return
            self._state.rescan_sync_progress.update(
                {
                    "running": True,
                    "phase": "preparing",
                    "total": 0,
                    "processed": 0,
                    "added": 0,
                    "skipped": 0,
                    "failed": 0,
                    "current_game_id": "",
                    "current_title": "",
                    "message": "queued",
                }
            )
            self._state.rescan_sync_thread = Thread(
                target=self._run_resilio_folder_sync_rescan, daemon=True
            )
            self._state.rescan_sync_thread.start()

    def _run_resilio_folder_sync_rescan(self) -> None:
        logger = logging.getLogger(__name__)
        progress = self._state.rescan_sync_progress
        if progress is None or self._state.repository is None:
            return
        provider = self._state.sync_provider
        game_manager = self._state.game_manager
        if provider is None:
            progress.update(
                {
                    "running": False,
                    "phase": "done",
                    "message": "sync_provider_unavailable",
                }
            )
            return

        targets = self._state.repository.list_sync_targets()
        progress.update(
            {
                "phase": "sync_reconcile",
                "total": len(targets),
                "processed": 0,
                "added": 0,
                "skipped": 0,
                "failed": 0,
                "message": "running",
            }
        )

        base = Path(self._effective_library_path())
        for target in targets:
            game_id = str(target.get("id", "") or "")
            game_title = str(target.get("title", "") or game_id)
            game_key = str(target.get("key", "") or "").strip()
            progress["current_game_id"] = game_id
            progress["current_title"] = game_title
            if self._is_game_disabled(game_id):
                progress["skipped"] += 1
                progress["processed"] += 1
                continue

            if not game_id or not game_key or self._is_lan_catalog_game(game_id):
                progress["skipped"] += 1
                progress["processed"] += 1
                continue

            folder = base / game_id
            archive = (
                game_manager.archive_path(game_id)
                if game_manager is not None
                else folder / f"{game_id}.eti"
            )
            if not archive.is_file():
                progress["skipped"] += 1
                progress["processed"] += 1
                continue

            ok, detail = provider.ensure_folder_synced(str(folder), game_key)
            if ok:
                progress["added"] += 1
            else:
                progress["failed"] += 1
                logger.warning(
                    "rescan_sync_folder_failed game_id=%s detail=%s", game_id, detail
                )
            progress["processed"] += 1
            time.sleep(0.35)

        progress.update(
            {
                "running": False,
                "phase": "done",
                "current_game_id": "",
                "current_title": "",
                "message": "completed",
            }
        )

    def _sync_status(self) -> dict:
        if self._state.sync_provider is None:
            return {
                "provider": "none",
                "running": False,
                "state": "disabled",
                "pid": None,
                "last_error": "",
            }
        status = self._state.sync_provider.status()
        return self._sync_status_payload(status)

    def _sync_metrics(self) -> dict:
        return self._sync_metrics_for_game(None)

    def _sync_metrics_for_game(self, game_id: str | None) -> dict:
        download_bps = 0
        upload_bps = 0
        sync_pid = None
        if self._state.sync_provider is not None:
            try:
                provider = self._state.sync_provider
                if game_id and hasattr(provider, "metrics_for_game"):
                    metrics = provider.metrics_for_game(game_id)
                    status_provider = self._sync_provider_for_game(game_id)
                    if status_provider is not None:
                        sync_status = status_provider.status()
                        sync_pid = sync_status.pid
                else:
                    metrics = provider.metrics()
                    sync_status = provider.status()
                    sync_pid = sync_status.pid
                download_bps = max(0, int(metrics.download_bps))
                upload_bps = max(0, int(metrics.upload_bps))
            except Exception as exc:  # noqa: BLE001
                if "HTTP Error 400" not in str(exc):
                    logging.getLogger(__name__).warning("sync_metrics_failed: %s", exc)
        with self._sync_metrics_lock:
            previous_sample = self._sync_metrics_disk_sample
            current_sample = collect_local_disk_io_sample(
                self._effective_library_path(), process_pid=sync_pid
            )
            disk_metrics = calculate_local_disk_metrics(previous_sample, current_sample)
            if current_sample is not None:
                self._sync_metrics_disk_sample = current_sample
        return {
            "download_bps": download_bps,
            "upload_bps": upload_bps,
            "provider_game_id": game_id or "",
            **disk_metrics,
        }

    def _sync_start(self) -> dict:
        if self._state.sync_provider is None:
            return self._sync_status()
        if (
            self._state.user_settings is not None
            and not self._state.user_settings.library_path_initialized
        ):
            return {
                "provider": "resilio",
                "running": False,
                "state": "blocked",
                "pid": None,
                "last_error": "library_path_not_initialized",
            }
        self._state.sync_watchdog_paused = False
        self._state.desired_sync_running = True
        self._state.sync_watchdog_last_restart_at = time.monotonic()
        self._persist_resilio_library_path(self._effective_library_path())
        logger = logging.getLogger(__name__)
        provider_name = str(type(self._state.sync_provider).__name__).lower()
        if "ouisync" in provider_name:
            provider_label = "ouisync"
        elif "resilio" in provider_name:
            provider_label = "resilio"
        else:
            provider_label = "sync"
        try:
            status = self._state.sync_provider.start()
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "sync_start_failed provider=%s",
                type(self._state.sync_provider).__name__,
            )
            status = SyncStatus(
                provider=provider_label,
                running=False,
                state="failed",
                last_error=str(exc),
            )
        if status.running:
            self._state.sync_watchdog_last_restart_at = 0.0
        if status.running:
            self._apply_all_extra_sync_items()
        if status.last_error:
            logger.warning(
                "sync_start_failed provider=%s state=%s pid=%s last_error=%s",
                status.provider,
                status.state,
                status.pid,
                status.last_error,
            )
        logger.info(
            "sync_start requested provider=%s running=%s pid=%s state=%s",
            status.provider,
            status.running,
            status.pid,
            status.state,
        )
        return self._sync_status_payload(status)

    def _sync_stop(self) -> dict:
        if self._state.sync_provider is None:
            return self._sync_status()
        self._state.sync_watchdog_paused = True
        self._state.desired_sync_running = False
        self._state.sync_watchdog_last_restart_at = 0.0
        status = self._state.sync_provider.stop()
        logging.getLogger(__name__).info(
            "sync_stop requested running=%s pid=%s", status.running, status.pid
        )
        return self._sync_status_payload(status)

    def _sync_provider_action(self, provider_type: str, action: str) -> dict:
        if self._state.sync_provider is None:
            return self._sync_status()

        normalized_provider_type = _normalize_sync_provider_type(provider_type)
        if normalized_provider_type is None:
            return {
                "provider": str(provider_type or "").strip().lower() or "unknown",
                "running": False,
                "state": "failed",
                "pid": None,
                "last_error": "sync_provider_action_invalid",
            }
        provider = self._sync_provider_for_type(normalized_provider_type)
        if provider is None:
            return {
                "provider": normalized_provider_type,
                "running": False,
                "state": "disabled",
                "pid": None,
                "last_error": "sync_provider_unavailable",
            }

        action_name = str(action or "").strip().lower()
        if action_name not in {"start", "stop", "restart"}:
            return {
                "provider": normalized_provider_type,
                "running": False,
                "state": "failed",
                "pid": None,
                "last_error": "sync_provider_action_invalid",
            }

        if (
            action_name in {"start", "restart"}
            and self._state.user_settings is not None
        ):
            if not self._state.user_settings.library_path_initialized:
                return {
                    "provider": normalized_provider_type,
                    "running": False,
                    "state": "blocked",
                    "pid": None,
                    "last_error": "library_path_not_initialized",
                }

        if action_name == "stop":
            status = provider.stop()
            logging.getLogger(__name__).info(
                "sync_provider_stop requested provider=%s running=%s pid=%s",
                normalized_provider_type,
                status.running,
                status.pid,
            )
            return self._sync_status_payload(status)

        if action_name == "restart":
            try:
                provider.stop()
            except Exception as exc:  # noqa: BLE001
                logging.getLogger(__name__).warning(
                    "sync_provider_restart_stop_failed provider=%s error=%s",
                    normalized_provider_type,
                    exc,
                )

        if normalized_provider_type == "resilio":
            self._persist_resilio_library_path(self._effective_library_path())

        status = provider.start()
        if status.running:
            self._apply_all_extra_sync_items()
        logging.getLogger(__name__).info(
            "sync_provider_%s requested provider=%s running=%s pid=%s",
            action_name,
            normalized_provider_type,
            status.running,
            status.pid,
        )
        return self._sync_status_payload(status)

    def _platform_info(self) -> dict:
        if self._state.platform_adapter is None:
            return {"name": "unknown"}
        return {"name": self._state.platform_adapter.platform_name()}

    def _available_storage_locations(self) -> list[dict]:
        if self._state.platform_adapter is None:
            return []
        return self._state.platform_adapter.list_storage_locations()

    def _install_prerequisites_bundle(self) -> dict:
        if self._state.platform_adapter is None:
            return {"ok": False, "message": "platform_adapter_unavailable", "path": ""}
        if self._state.platform_adapter.platform_name() != "windows":
            return {"ok": False, "message": "not_supported_on_platform", "path": ""}

        target = (
            Path(self._effective_library_path())
            / "eti_launcher"
            / "bin"
            / "preqsetup.exe"
        )
        result = self._state.platform_adapter.launch_executable(str(target), args=[])
        return {"ok": result.ok, "message": result.message, "path": str(target)}

    def _install_wine_common_dependencies(self) -> dict:
        if self._state.platform_adapter is None:
            return {
                "ok": False,
                "message": "platform_adapter_unavailable",
                "detail": "",
            }
        if self._state.platform_adapter.platform_name() != "linux":
            return {"ok": False, "message": "not_supported_on_platform", "detail": ""}

        common_packages = list(WINETRICKS_COMMON_PACKAGE_IDS)
        result = self._state.platform_adapter.install_common_wine_dependencies(
            common_packages,
            winetricks_path=self._resolve_provider_winetricks_path(),
            cache_path=self._resolve_provider_winetricks_cache_path(),
        )
        return {
            "ok": result.ok,
            "message": result.message,
            "detail": result.detail,
            "packages": common_packages,
            "prefix": str(Path.home() / ".wine"),
        }

    def _winetricks_packages_read(self) -> dict:
        return {
            "packages": list(WINETRICKS_PACKAGE_OPTIONS),
            "default_selected": list(WINETRICKS_COMMON_PACKAGE_IDS),
        }

    def _resolve_game_wine_prefix_path(self, game_id: str, runtime: str) -> Path:
        return Path(self._effective_library_path()) / game_id / ".compatdata" / runtime

    def _normalize_winetricks_packages(
        self, raw_packages: object, allow_empty: bool = False
    ) -> list[str]:
        if not isinstance(raw_packages, list):
            raise ValueError("invalid_winetricks_package_set")

        normalized: list[str] = []
        seen: set[str] = set()
        for item in raw_packages:
            package_id = str(item or "").strip().lower()
            if not package_id:
                continue
            if package_id not in WINETRICKS_ALLOWED_PACKAGE_IDS:
                raise ValueError("invalid_winetricks_package_selection")
            if package_id in seen:
                continue
            seen.add(package_id)
            normalized.append(package_id)
        if not normalized and not allow_empty:
            raise ValueError("invalid_winetricks_package_set")
        return normalized

    def _normalize_winetricks_action(self, raw_action: object) -> str:
        action = str(raw_action or "install").strip().lower()
        if action not in {"install", "remove"}:
            raise ValueError("invalid_winetricks_action")
        return action

    def _manage_game_prefix_wine_dependencies(
        self, game_id: str, payload: dict
    ) -> dict:
        game_key = str(game_id or "").strip()
        if not game_key:
            return {
                "ok": False,
                "message": "invalid_game_id",
                "detail": "",
                "game_id": "",
            }
        if self._state.platform_adapter is None:
            return {
                "ok": False,
                "message": "platform_adapter_unavailable",
                "detail": "",
                "game_id": game_key,
            }
        if self._state.platform_adapter.platform_name() != "linux":
            return {
                "ok": False,
                "message": "not_supported_on_platform",
                "detail": "",
                "game_id": game_key,
            }

        try:
            action = self._normalize_winetricks_action(payload.get("action", "install"))
            packages = self._normalize_winetricks_packages(payload.get("packages", []))
        except ValueError as exc:
            return {
                "ok": False,
                "message": str(exc),
                "detail": "",
                "game_id": game_key,
                "packages": [],
            }

        runtime = self._effective_linux_runtime_for_game(game_key).lower()
        # Launcher-managed prefixes exist only for Windows-backed runtime modes.
        if runtime not in {"wine", "proton", "proton-ge"}:
            return {
                "ok": False,
                "message": "windows_runtime_prefix_required",
                "detail": runtime,
                "game_id": game_key,
                "runtime": runtime,
                "packages": packages,
            }

        prefix_path = self._resolve_game_wine_prefix_path(game_key, runtime)
        if action == "install":
            result = self._state.platform_adapter.install_common_wine_dependencies_for_prefix(
                str(prefix_path),
                packages,
                winetricks_path=self._resolve_provider_winetricks_path(),
                cache_path=self._resolve_provider_winetricks_cache_path(),
            )
        else:
            result = self._state.platform_adapter.open_wine_prefix_uninstaller(
                str(prefix_path)
            )

        return {
            "ok": result.ok,
            "message": result.message,
            "detail": result.detail,
            "packages": packages,
            "prefix": str(prefix_path),
            "runtime": runtime,
            "game_id": game_key,
            "action": action,
        }

    def _local_game_root(self, game_id: str) -> Path:
        return Path(self._effective_library_path()) / game_id

    @staticmethod
    def _local_game_args_to_list(raw: object) -> list[str]:
        if raw is None:
            return []
        if isinstance(raw, list):
            values: list[str] = []
            for item in raw:
                text = str(item or "").strip()
                if text:
                    values.append(text)
            return values
        text = str(raw or "").strip()
        if not text:
            return []
        try:
            return shlex.split(text)
        except ValueError:
            return [part for part in text.splitlines() if part.strip()]

    @staticmethod
    def _data_url_to_bytes(raw: str) -> tuple[str, bytes] | None:
        value = str(raw or "").strip()
        if not value.startswith("data:") or "," not in value:
            return None
        header, payload = value.split(",", 1)
        if ";base64" not in header:
            return None
        mime = header[5:].split(";", 1)[0].strip().lower() or "application/octet-stream"
        try:
            data = base64.b64decode(payload, validate=True)
        except ValueError:
            return None
        return mime, data

    @staticmethod
    def _mime_to_extension(mime: str, fallback: str = ".png") -> str:
        normalized = str(mime or "").strip().lower()
        if normalized in {"image/jpeg", "image/jpg"}:
            return ".jpg"
        if normalized == "image/png":
            return ".png"
        if normalized == "image/webp":
            return ".webp"
        if normalized == "image/svg+xml":
            return ".svg"
        if normalized.endswith("/bmp"):
            return ".bmp"
        return fallback

    def _write_local_game_metadata(
        self,
        game_id: str,
        payload: dict,
        *,
        preserve_image_path: str = "",
    ) -> dict:
        game_key = str(game_id or "").strip()
        if not GAME_ID_RE.match(game_key):
            return {
                "ok": False,
                "message": "invalid_game_id",
                "detail": "",
                "game_id": "",
            }

        metadata_root = self._local_game_root(game_key)
        try:
            metadata_root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logging.getLogger(__name__).warning(
                "local_game_metadata_root_unavailable game_id=%s path=%s error=%s",
                game_key,
                metadata_root,
                exc,
            )
            return {
                "ok": False,
                "message": "metadata_root_unavailable",
                "detail": "",
                "game_id": game_key,
            }

        image_path = str(preserve_image_path or "").strip()
        image_data_url = str(payload.get("game_image_data_url", "") or "").strip()
        image_name = str(payload.get("game_image_name", "") or "").strip()
        if image_data_url:
            parsed_image = self._data_url_to_bytes(image_data_url)
            if parsed_image is None:
                return {
                    "ok": False,
                    "message": "invalid_local_game_image",
                    "detail": "",
                    "game_id": game_key,
                }
            mime, image_bytes = parsed_image
            ext = Path(image_name or "cover.png").suffix.lower()
            if ext not in {".jpg", ".jpeg", ".png", ".webp", ".svg", ".bmp"}:
                ext = self._mime_to_extension(mime)
            image_file = metadata_root / f"cover{ext}"
            try:
                for existing in metadata_root.glob("cover.*"):
                    if existing != image_file:
                        existing.unlink(missing_ok=True)
                image_file.write_bytes(image_bytes)
            except OSError as exc:
                logging.getLogger(__name__).warning(
                    "local_game_image_write_failed game_id=%s path=%s error=%s",
                    game_key,
                    image_file,
                    exc,
                )
                return {
                    "ok": False,
                    "message": "local_game_image_io_error",
                    "detail": "",
                    "game_id": game_key,
                }
            image_path = image_file.name

        title_en = str(payload.get("title_en", "") or "").strip()
        title_de = str(payload.get("title_de", "") or "").strip()
        description_en = str(payload.get("readme_en", "") or "").strip()
        description_de = str(payload.get("readme_de", "") or "").strip()
        start_file = str(payload.get("game_start_file", "") or "").strip()
        start_args = self._local_game_args_to_list(payload.get("game_start_args", []))

        metadata_payload: dict[str, object] = {
            "title": {"en": title_en, "de": title_de or title_en},
            "description": {
                "en": description_en,
                "de": description_de or description_en,
                "fr": str(payload.get("readme_fr", "") or "").strip(),
            },
            "key": str(payload.get("key", "") or game_key).strip() or game_key,
            "release_year": str(payload.get("release_year", "") or "").strip(),
            "publisher": str(payload.get("publisher", "") or "").strip(),
            "size_gb": float(payload.get("size_gb", 0) or 0),
            "max_players": str(payload.get("max_players", "") or "").strip(),
            "master_required": bool(payload.get("master_required", False)),
            "version": str(payload.get("version", "") or "").strip(),
            "game_provider_type": "local",
        }
        genre_id = payload.get("genre_id")
        if genre_id not in {None, "", "all"}:
            metadata_payload["genre_id"] = genre_id
        if start_file:
            metadata_payload["game_start"] = {
                "file": start_file,
                "args": start_args,
            }
        if image_path:
            metadata_payload["image"] = image_path

        metadata_payload["game_id"] = game_key
        metadata_file = metadata_root / "metadata.json"
        try:
            tmp_file = metadata_file.with_suffix(".tmp")
            tmp_file.write_text(
                json.dumps(metadata_payload, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            tmp_file.replace(metadata_file)
        except OSError as exc:
            logging.getLogger(__name__).warning(
                "local_game_metadata_write_failed game_id=%s path=%s error=%s",
                game_key,
                metadata_file,
                exc,
            )
            try:
                tmp_file.unlink(missing_ok=True)
            except OSError:
                pass
            return {
                "ok": False,
                "message": "metadata_io_error",
                "detail": "",
                "game_id": game_key,
            }

        return {
            "ok": True,
            "message": "ok",
            "detail": "",
            "game_id": game_key,
            "metadata_file": str(metadata_file),
            "metadata": metadata_payload,
            "image_path": image_path,
        }

    def _save_game_metadata_file(self, game_id: str, payload: dict) -> dict:
        game_key = str(game_id or "").strip()
        if not GAME_ID_RE.match(game_key):
            return {
                "ok": False,
                "message": "invalid_game_id",
                "detail": "",
                "game_id": "",
            }

        if self._state.database is None or self._state.repository is None:
            return {
                "ok": False,
                "message": "database_unavailable",
                "detail": "",
                "game_id": game_key,
            }

        metadata_root = Path(self._effective_library_path()) / game_key
        try:
            metadata_root.mkdir(parents=True, exist_ok=True)
            if not metadata_root.is_dir():
                return {
                    "ok": False,
                    "message": "metadata_root_unavailable",
                    "detail": "",
                    "game_id": game_key,
                }
        except OSError as exc:
            logging.getLogger(__name__).warning(
                "metadata_root_unavailable game_id=%s path=%s error=%s",
                game_key,
                metadata_root,
                exc,
            )
            return {
                "ok": False,
                "message": "metadata_root_unavailable",
                "detail": "",
                "game_id": game_key,
            }

        repo = self._state.repository
        en_entry = repo.get_game(game_key, locale="en")
        de_entry = repo.get_game(game_key, locale="de")
        if en_entry is None and de_entry is None:
            return {
                "ok": False,
                "message": "game_not_found",
                "detail": "",
                "game_id": game_key,
            }

        en_entry = en_entry or {}
        de_entry = de_entry or en_entry
        try:
            packages = self._normalize_winetricks_packages(
                payload.get("packages", []), allow_empty=True
            )
        except ValueError as exc:
            message = str(exc)
            if message == "invalid_winetricks_package_selection":
                message = "invalid_winetricks_package_set"
            return {
                "ok": False,
                "message": message,
                "detail": "",
                "game_id": game_key,
            }

        existing_metadata = self._game_metadata(game_key)
        base_payload = {}
        if existing_metadata is not None:
            if existing_metadata.title or existing_metadata.title_de:
                base_payload["title"] = {
                    "en": existing_metadata.title,
                    "de": existing_metadata.title_de,
                }
            if (
                existing_metadata.description
                or existing_metadata.description_de
                or existing_metadata.description_fr
            ):
                base_payload["description"] = {
                    "en": existing_metadata.description,
                    "de": existing_metadata.description_de,
                    "fr": existing_metadata.description_fr,
                }
            if existing_metadata.key:
                base_payload["key"] = existing_metadata.key
            if existing_metadata.release_year:
                base_payload["release_year"] = existing_metadata.release_year
            if existing_metadata.publisher:
                base_payload["publisher"] = existing_metadata.publisher
            if existing_metadata.size_gb is not None:
                base_payload["size_gb"] = existing_metadata.size_gb
            if existing_metadata.max_players:
                base_payload["max_players"] = existing_metadata.max_players
            if existing_metadata.master_required is not None:
                base_payload["master_required"] = existing_metadata.master_required
            if existing_metadata.version:
                base_payload["version"] = existing_metadata.version
            if existing_metadata.genre or existing_metadata.genre_de:
                base_payload["genre"] = {
                    "en": existing_metadata.genre,
                    "de": existing_metadata.genre_de,
                }
            if existing_metadata.genre_id is not None:
                base_payload["genre_id"] = existing_metadata.genre_id
            if existing_metadata.game_start_file or existing_metadata.game_start_args:
                base_payload["game_start"] = {
                    "file": existing_metadata.game_start_file,
                    "args": list(existing_metadata.game_start_args),
                }
            if existing_metadata.image:
                base_payload["image"] = existing_metadata.image
            if existing_metadata.video:
                base_payload["video"] = existing_metadata.video
            if existing_metadata.runner:
                base_payload["runner"] = existing_metadata.runner

            existing_non_winetricks_tasks = []
            for task in existing_metadata.installer_tasks:
                if not isinstance(task, dict):
                    continue
                task_name = (
                    str(task.get("name", "") or task.get("action", "")).strip().lower()
                )
                if task_name in {"winetricks", "protontricks"}:
                    continue
                existing_non_winetricks_tasks.append(dict(task))
            if existing_non_winetricks_tasks:
                base_payload["installer_tasks"] = existing_non_winetricks_tasks
            elif "installer_tasks" in base_payload:
                base_payload.pop("installer_tasks")

        effective_runtime = self._effective_linux_runtime_for_game(game_key).lower()
        if effective_runtime in {"wine", "proton", "proton-ge"}:
            base_payload["runner"] = effective_runtime

        base_payload["title"] = {
            "en": str(
                en_entry.get("title", "") or base_payload.get("title", {}).get("en", "")
            ),
            "de": str(
                de_entry.get("title", "") or base_payload.get("title", {}).get("de", "")
            ),
        }

        base_payload["description"] = {
            "en": str(
                en_entry.get("readme", "")
                or base_payload.get("description", {}).get("en", "")
            ),
            "de": str(
                de_entry.get("readme", "")
                or base_payload.get("description", {}).get("de", "")
            ),
            "fr": str(base_payload.get("description", {}).get("fr", "")),
        }

        key = str(en_entry.get("key", "") or de_entry.get("key", "") or "").strip()
        if key:
            base_payload["key"] = key
        release_year = str(
            en_entry.get("release_year", de_entry.get("release_year", "")) or ""
        ).strip()
        if release_year:
            base_payload["release_year"] = release_year
        publisher = str(
            en_entry.get("publisher", de_entry.get("publisher", "")) or ""
        ).strip()
        if publisher:
            base_payload["publisher"] = publisher
        size_gb = en_entry.get("size_gb", de_entry.get("size_gb", None))
        if size_gb is not None:
            base_payload["size_gb"] = size_gb
        max_players = str(
            en_entry.get("max_players", de_entry.get("max_players", "")) or ""
        ).strip()
        if max_players:
            base_payload["max_players"] = max_players
        master_required = en_entry.get(
            "master_required", de_entry.get("master_required", None)
        )
        if master_required is not None:
            if isinstance(master_required, bool):
                base_payload["master_required"] = master_required
            else:
                try:
                    base_payload["master_required"] = bool(int(master_required))
                except (TypeError, ValueError):
                    text = str(master_required).strip().lower()
                    if text in {"true", "1", "yes", "on"}:
                        base_payload["master_required"] = True
                    elif text in {"false", "0", "no", "off"}:
                        base_payload["master_required"] = False
        version = str(
            en_entry.get("version", de_entry.get("version", "")) or ""
        ).strip()
        if version:
            base_payload["version"] = version
        genre = str(en_entry.get("genre", de_entry.get("genre", "")) or "").strip()
        genre_de = str(de_entry.get("genre", en_entry.get("genre", "")) or "").strip()
        if genre or genre_de:
            base_payload["genre"] = {"en": genre, "de": genre_de}
        genre_id = en_entry.get("genre_id", de_entry.get("genre_id", None))
        if genre_id is not None:
            base_payload["genre_id"] = genre_id

        existing_tasks = []
        if isinstance(base_payload.get("installer_tasks"), list):
            existing_tasks = base_payload.get("installer_tasks") or []
        selected_tasks = [
            {"name": "winetricks", "app": package} for package in sorted(set(packages))
        ]
        if selected_tasks:
            base_payload["installer_tasks"] = [*existing_tasks, *selected_tasks]
        elif "installer_tasks" in base_payload:
            base_payload.pop("installer_tasks")

        base_payload["game_id"] = game_key
        metadata_file = metadata_root / "metadata.json"
        try:
            tmp_file = metadata_file.with_suffix(".tmp")
            tmp_file.write_text(
                json.dumps(base_payload, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            tmp_file.replace(metadata_file)
        except OSError as exc:
            logging.getLogger(__name__).warning(
                "metadata_io_error game_id=%s path=%s error=%s",
                game_key,
                metadata_file,
                exc,
            )
            try:
                tmp_file.unlink(missing_ok=True)
            except OSError:
                pass
            return {
                "ok": False,
                "message": "metadata_io_error",
                "detail": "",
                "game_id": game_key,
                "packages": [],
            }

        return {
            "ok": True,
            "message": "ok",
            "detail": "",
            "game_id": game_key,
            "packages": packages,
        }

    def _local_game_settings_update(self, payload: dict) -> dict:
        if self._state.database is None or self._state.repository is None:
            return {
                "ok": False,
                "message": "database_unavailable",
                "detail": "",
                "game_id": "",
            }

        body = payload if isinstance(payload, dict) else {}
        item = body.get("item", body)
        if not isinstance(item, dict):
            item = {}

        game_key = str(item.get("game_id", "") or "").strip()
        if not GAME_ID_RE.match(game_key):
            return {
                "ok": False,
                "message": "invalid_game_id",
                "detail": "",
                "game_id": "",
            }

        key = str(item.get("key", "") or "").strip() or game_key
        title_en = str(item.get("title_en", "") or "").strip()
        title_de = str(item.get("title_de", "") or "").strip() or title_en
        if not title_en:
            return {
                "ok": False,
                "message": "local_game_title_required",
                "detail": "",
                "game_id": game_key,
            }

        try:
            size_gb = float(item.get("size_gb", 0) or 0)
        except (TypeError, ValueError):
            return {
                "ok": False,
                "message": "local_game_size_invalid",
                "detail": "",
                "game_id": game_key,
            }
        if size_gb < 0:
            return {
                "ok": False,
                "message": "local_game_size_invalid",
                "detail": "",
                "game_id": game_key,
            }

        genre_id_raw = item.get("genre_id", None)
        genre_id: int | None
        if genre_id_raw in {None, "", "all"}:
            genre_id = None
        else:
            try:
                genre_id = int(genre_id_raw)
            except (TypeError, ValueError):
                return {
                    "ok": False,
                    "message": "local_game_genre_invalid",
                    "detail": "",
                    "game_id": game_key,
                }

        original_id = str(body.get("original_game_id", "") or "").strip()
        try:
            records = self._state.repository.game_id_records(game_key)
            existing = records["catalog"]
            editing_local = bool(
                existing
                and str(existing[1] or "").lower() == "local"
                and original_id == game_key == str(existing[0])
            )
            conflict = self._game_id_conflicts(
                game_key,
                allow_existing_local=editing_local,
                allow_existing_index=editing_local,
            )
        except (OSError, ValueError, sqlite3.Error):
            return {
                "ok": False,
                "message": "game_id_check_unavailable",
                "detail": "",
                "game_id": game_key,
            }
        if conflict:
            return {
                "ok": False,
                "message": "duplicate_game_id",
                "detail": "",
                "game_id": game_key,
            }

        metadata_root = self._local_game_root(game_key)
        try:
            metadata_root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logging.getLogger(__name__).warning(
                "local_game_metadata_root_unavailable game_id=%s path=%s error=%s",
                game_key,
                metadata_root,
                exc,
            )
            return {
                "ok": False,
                "message": "metadata_root_unavailable",
                "detail": "",
                "game_id": game_key,
            }

        existing_metadata = self._game_metadata(game_key)
        preserve_image_path = str(
            (existing_metadata.image if existing_metadata is not None else "") or ""
        ).strip()
        metadata_result = self._write_local_game_metadata(
            game_key,
            {
                "title_en": title_en,
                "title_de": title_de,
                "release_year": str(item.get("release_year", "") or "").strip(),
                "publisher": str(item.get("publisher", "") or "").strip(),
                "size_gb": size_gb,
                "max_players": str(item.get("max_players", "") or "").strip(),
                "master_required": bool(item.get("master_required", False)),
                "version": str(item.get("version", "") or "").strip(),
                "genre_id": genre_id,
                "game_start_file": str(item.get("game_start_file", "") or "").strip(),
                "game_start_args": item.get("game_start_args", []),
                "game_image_data_url": str(
                    item.get("game_image_data_url", "") or ""
                ).strip(),
                "game_image_name": str(item.get("game_image_name", "") or "").strip(),
                "key": key,
            },
            preserve_image_path=preserve_image_path,
        )
        if not metadata_result.get("ok", False):
            return metadata_result

        conn = self._state.database.connection
        with conn:
            conn.execute(
                """
                INSERT INTO game_catalog(
                    id, title_en, title_de, key, release_year, publisher, size_gb,
                    readme_en, readme_de, max_players, master_required, genre_id,
                    version, game_provider_type
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title_en = excluded.title_en,
                    title_de = excluded.title_de,
                    key = excluded.key,
                    release_year = excluded.release_year,
                    publisher = excluded.publisher,
                    size_gb = excluded.size_gb,
                    readme_en = excluded.readme_en,
                    readme_de = excluded.readme_de,
                    max_players = excluded.max_players,
                    master_required = excluded.master_required,
                    genre_id = excluded.genre_id,
                    version = excluded.version,
                    game_provider_type = excluded.game_provider_type
                """,
                (
                    game_key,
                    title_en,
                    title_de,
                    key,
                    str(item.get("release_year", "") or "").strip(),
                    str(item.get("publisher", "") or "").strip(),
                    size_gb,
                    str(item.get("readme_en", "") or "").strip(),
                    str(item.get("readme_de", "") or "").strip()
                    or str(item.get("readme_en", "") or "").strip(),
                    str(item.get("max_players", "") or "").strip(),
                    1 if bool(item.get("master_required", False)) else 0,
                    genre_id,
                    str(item.get("version", "") or "").strip(),
                    "local",
                ),
            )

        if self._state.scanner is not None:
            try:
                self._state.scanner.scan(force=True)
            except Exception:  # noqa: BLE001
                logging.getLogger(__name__).warning(
                    "local_game_scan_refresh_failed game_id=%s", game_key
                )

        return {
            "ok": True,
            "message": "saved",
            "detail": "",
            "game_id": game_key,
            "metadata": metadata_result.get("metadata", {}),
            "metadata_file": metadata_result.get("metadata_file", ""),
        }

    def _game_visibility_update(self, game_id: str, hidden: bool) -> dict:
        game_key = str(game_id or "").strip()
        if self._state.repository is None:
            return {
                "ok": False,
                "message": "repository_unavailable",
                "game_id": game_key,
            }
        if (
            not game_key
            or self._state.repository.get_game(game_key, locale="en") is None
        ):
            return {"ok": False, "message": "game_not_found", "game_id": game_key}
        if not self._state.repository.set_game_hidden(game_key, bool(hidden)):
            return {
                "ok": False,
                "message": "visibility_update_failed",
                "game_id": game_key,
            }
        logging.getLogger(__name__).info(
            "catalog_game_visibility_updated game_id=%s hidden=%s",
            game_key,
            bool(hidden),
        )
        return {
            "ok": True,
            "message": "hidden" if hidden else "visible",
            "game_id": game_key,
            "hidden": bool(hidden),
        }

    def _install_game_proton_common_dependencies(self, game_id: str) -> dict:
        return self._manage_game_prefix_wine_dependencies(
            game_id,
            {
                "action": "install",
                "packages": list(WINETRICKS_COMMON_PACKAGE_IDS),
            },
        )

    def _set_resilio_network_mode(self, payload: dict) -> dict:
        if self._state.platform_adapter is None:
            return {
                "ok": False,
                "message": "platform_adapter_unavailable",
                "mode": "",
                "detail": "",
            }
        mode = str(payload.get("mode", "")).strip().lower()
        if mode not in {"lan", "internet"}:
            return {
                "ok": False,
                "message": "invalid_network_mode",
                "mode": mode,
                "detail": "",
            }

        platform_name = self._state.platform_adapter.platform_name()
        if platform_name == "windows":
            script_path = self._config.windows_sync_firewall_script_path
        elif platform_name == "linux":
            script_path = self._config.linux_sync_firewall_script_path
        else:
            return {
                "ok": False,
                "message": "not_supported_on_platform",
                "mode": mode,
                "detail": "",
            }

        result = self._state.platform_adapter.configure_sync_network_mode(
            script_path=script_path,
            sync_binary_path=self._config.sync_binary_path,
            mode=mode,
        )
        return {
            "ok": result.ok,
            "message": result.message,
            "mode": mode,
            "detail": result.detail,
        }

    def _set_local_network_private(self, payload: dict) -> dict:
        _ = payload
        if self._state.platform_adapter is None:
            return {
                "ok": False,
                "message": "platform_adapter_unavailable",
                "detail": "",
            }
        if self._state.platform_adapter.platform_name() != "windows":
            return {"ok": False, "message": "not_supported_on_platform", "detail": ""}
        result = self._state.platform_adapter.set_local_network_private(
            script_path=self._config.windows_private_network_script_path
        )
        return {
            "ok": result.ok,
            "message": result.message,
            "detail": result.detail,
        }

    def _validate_storage(self, raw_path: str) -> dict:
        if self._state.platform_adapter is None:
            return {
                "path": raw_path,
                "exists": False,
                "writable": False,
                "is_directory": False,
                "ok": False,
                "message": "platform_adapter_unavailable",
            }
        result = self._state.platform_adapter.validate_storage_path(raw_path)
        return {
            "path": result.path,
            "exists": result.exists,
            "writable": result.writable,
            "is_directory": result.is_directory,
            "ok": result.ok,
            "message": result.message,
        }

    def _open_folder(self, raw_path: str) -> dict:
        if self._state.platform_adapter is None:
            return {"ok": False, "message": "platform_adapter_unavailable"}
        target = raw_path
        if raw_path == "library":
            target = self._effective_library_path()
        result = self._state.platform_adapter.open_folder(target)
        return {"ok": result.ok, "message": result.message}

    def _install_script_info(self, game_id: str) -> dict:
        if self._state.install_support is None or self._state.platform_adapter is None:
            return {
                "game_id": game_id,
                "platform": "unknown",
                "exists": False,
                "path": "",
            }
        info = self._state.install_support.install_script_for(
            game_id=game_id,
            platform_name=self._state.platform_adapter.platform_name(),
        )
        return {
            "game_id": info.game_id,
            "platform": info.platform,
            "exists": info.exists,
            "path": info.path,
        }

    def _normalize_game_lang(self, raw: str) -> str:
        value = str(raw or "").strip().lower()
        if value in {"en", "de"}:
            return value
        fallback = str(self._config.default_locale or "").strip().lower()
        if fallback in {"en", "de"}:
            return fallback
        return "en"

    def _game_action(self, game_id: str, action: str, game_lang: str = "") -> dict:
        if self._is_game_disabled(game_id):
            return {
                "ok": False,
                "action": action,
                "game_id": game_id,
                "message": "game_disabled_by_launcher_ini",
                "details": {},
            }
        if action == "delete":
            return self._delete_game_action(game_id)
        if action == "remove-sync-data":
            return self._remove_ouisync_game_data(game_id)

        if self._state.game_manager is None:
            return {
                "ok": False,
                "action": action,
                "game_id": game_id,
                "message": "game_manager_unavailable",
                "details": {},
            }

        manager = self._state.game_manager
        repo = self._state.repository
        game_provider_type = ""
        if repo is not None:
            game = repo.get_game(game_id, locale="en") or {}
            game_provider_type = (
                str(game.get("game_provider_type", "") or "").strip().lower()
            )
        if game_provider_type == "local" and action in {
            "install",
            "update",
            "uninstall",
        }:
            return {
                "ok": False,
                "action": action,
                "game_id": game_id,
                "message": "local_game_no_sync",
                "details": {},
            }
        runtime_override = self._get_game_linux_runtime_override(game_id)
        leave_terminal_open = self._get_game_linux_leave_terminal_open(game_id)
        launch_lang = self._normalize_game_lang(game_lang)

        def run_ouisync_install(operation: str) -> GameActionResult:
            access = self._ouisync_game_access(game_id)
            provider = self._sync_provider_for_game(game_id)
            mount_action = getattr(provider, "run_with_game_repository_mounted", None)
            if access is None or not callable(mount_action):
                return GameActionResult(
                    False,
                    operation,
                    game_id,
                    "ouisync_catalog_access_unavailable",
                    {},
                )
            status_reader = getattr(provider, "status", None)
            starter = getattr(provider, "start", None)
            if callable(status_reader) and callable(starter):
                provider_status = status_reader()
                if str(getattr(provider_status, "state", "")) != "running":
                    provider_status = starter()
                if str(getattr(provider_status, "state", "")) != "running":
                    return GameActionResult(
                        False,
                        operation,
                        game_id,
                        str(
                            getattr(provider_status, "last_error", "")
                            or "ouisync_session_unavailable"
                        ),
                        {},
                    )
            game_folder = Path(self._effective_library_path()) / game_id
            try:
                repository_path = self._ouisync_game_repository_path(game_id)
            except ValueError as exc:
                return GameActionResult(False, operation, game_id, str(exc), {})

            def output(line: str) -> None:
                self._append_install_console_line(game_id, line)

            def provider_stopped() -> bool:
                # A failure while Ouisync is shutting down is an interruption, not a
                # broken archive: the download must resume after the next start.
                if not callable(status_reader):
                    return False
                try:
                    return str(getattr(status_reader(), "state", "")) != "running"
                except Exception:  # noqa: BLE001 - an unreadable provider is not running
                    return True

            def interrupted() -> GameActionResult:
                return GameActionResult(
                    False, operation, game_id, OUISYNC_INSTALL_INTERRUPTED, {}
                )

            def install_from_mount(mount_path: Path) -> GameActionResult:
                copy_repository_assets(
                    mount_path,
                    game_folder,
                    game_id=game_id,
                    editable_files=tuple(access.editable_files),
                )
                if operation == "update":
                    return manager.update(
                        game_id,
                        output_callback=output,
                        archive_source_root=mount_path,
                    )
                return manager.install(
                    game_id,
                    output_callback=output,
                    archive_source_root=mount_path,
                )

            try:
                result = mount_action(access, str(repository_path), install_from_mount)
            except Exception as exc:  # noqa: BLE001 - convert provider/mount failures to stable result
                if provider_stopped():
                    return interrupted()
                message = (
                    str(exc)
                    if str(exc).startswith("ouisync_")
                    else "ouisync_repository_mount_failed"
                )
                return GameActionResult(
                    False,
                    operation,
                    game_id,
                    message,
                    {},
                )
            if not result.ok and provider_stopped():
                return interrupted()
            return result

        if action == "status":
            result = manager.check_status(game_id)
        elif action == "install":
            previous_version = ""
            if repo is not None:
                game = repo.get_game(game_id, locale="en") or {}
                previous_version = str(game.get("installed_version", "") or "")
                repo.set_install_state(game_id, "installing", previous_version)
            self._append_install_console_line(game_id, "running install extraction")
            result = (
                run_ouisync_install("install")
                if game_provider_type == "ouisync"
                else manager.install(
                    game_id,
                    output_callback=lambda line, gid=game_id: (
                        self._append_install_console_line(gid, line)
                    ),
                )
            )
            if repo is not None:
                final_version = previous_version
                if result.ok:
                    status = manager.check_status(game_id)
                    final_version = str(
                        status.details.get("installed_version", "") or previous_version
                    )
                    repo.set_install_state(game_id, "installed", final_version)
                else:
                    rollback_state = "installed" if previous_version else "missing"
                    if (
                        result.message == OUISYNC_INSTALL_INTERRUPTED
                        and not previous_version
                    ):
                        # Keep the download intent so the watchdog resumes it.
                        rollback_state = "downloading"
                    repo.set_install_state(
                        game_id,
                        rollback_state,
                        previous_version if rollback_state == "installed" else "",
                    )
        elif action == "update":
            previous_version = ""
            if repo is not None:
                game = repo.get_game(game_id, locale="en") or {}
                previous_version = str(game.get("installed_version", "") or "")
                repo.set_install_state(game_id, "installing", previous_version)
            self._append_install_console_line(game_id, "running update extraction")
            result = (
                run_ouisync_install("update")
                if game_provider_type == "ouisync"
                else manager.update(
                    game_id,
                    output_callback=lambda line, gid=game_id: (
                        self._append_install_console_line(gid, line)
                    ),
                )
            )
            if repo is not None:
                final_version = previous_version
                if result.ok:
                    status = manager.check_status(game_id)
                    final_version = str(
                        status.details.get("installed_version", "") or previous_version
                    )
                    repo.set_install_state(game_id, "installed", final_version)
                else:
                    rollback_state = "installed" if previous_version else "missing"
                    repo.set_install_state(
                        game_id,
                        rollback_state,
                        previous_version if rollback_state == "installed" else "",
                    )
        elif action == "uninstall":
            result = manager.uninstall(game_id)
            if result.ok and repo is not None:
                repo.set_install_state(game_id, "missing", "")
                self._refresh_game_index_if_changed()
        elif action == "start":
            player = (
                self._state.user_settings.nickname
                if self._state.user_settings is not None
                else ""
            )
            result = manager.start_game(
                game_id,
                server=False,
                game_lang=launch_lang,
                player=player,
                linux_runtime_override=runtime_override,
                linux_leave_terminal_open=leave_terminal_open,
            )
        elif action == "start-server":
            player = (
                self._state.user_settings.nickname
                if self._state.user_settings is not None
                else ""
            )
            result = manager.start_game(
                game_id,
                server=True,
                game_lang=launch_lang,
                player=player,
                linux_runtime_override=runtime_override,
                linux_leave_terminal_open=leave_terminal_open,
            )
        else:
            return {
                "ok": False,
                "action": action,
                "game_id": game_id,
                "message": "unknown_action",
                "details": {},
            }

        logging.getLogger(__name__).info(
            "game_action action=%s game_id=%s ok=%s message=%s",
            result.action,
            result.game_id,
            result.ok,
            result.message,
        )
        if action in {"start", "start-server"} and result.ok:
            self._state.current_game_id = str(game_id or "").strip()
            self._schedule_stats_report(force=True)
        return {
            "ok": result.ok,
            "action": result.action,
            "game_id": result.game_id,
            "message": result.message,
            "details": result.details,
        }

    def _remove_ouisync_game_data(self, game_id: str) -> dict:
        game = (
            self._state.repository.get_game(game_id, locale="en")
            if self._state.repository
            else None
        )
        if game is None:
            return {
                "ok": False,
                "action": "remove-sync-data",
                "game_id": game_id,
                "message": "game_not_found",
                "details": {},
            }
        if str(game.get("game_provider_type", "") or "").strip().lower() != "ouisync":
            return {
                "ok": False,
                "action": "remove-sync-data",
                "game_id": game_id,
                "message": "ouisync_game_required",
                "details": {},
            }
        provider = self._sync_provider_for_game(game_id)
        remove = getattr(provider, "delete_game_repository", None)
        if not callable(remove):
            return {
                "ok": False,
                "action": "remove-sync-data",
                "game_id": game_id,
                "message": "sync_provider_unavailable",
                "details": {},
            }
        try:
            repository_path = self._ouisync_game_repository_path(game_id)
        except ValueError as exc:
            return {
                "ok": False,
                "action": "remove-sync-data",
                "game_id": game_id,
                "message": str(exc),
                "details": {},
            }
        ok, message = remove(str(repository_path))
        if not ok:
            return {
                "ok": False,
                "action": "remove-sync-data",
                "game_id": game_id,
                "message": message,
                "details": {},
            }
        try:
            remove_repository_assets(Path(self._effective_library_path()) / game_id)
        except OSError as exc:
            logging.getLogger(__name__).warning(
                "ouisync_game_asset_cleanup_failed game_id=%s error=%s",
                game_id,
                type(exc).__name__,
            )
            return {
                "ok": False,
                "action": "remove-sync-data",
                "game_id": game_id,
                "message": "ouisync_repository_assets_cleanup_failed",
                "details": {},
            }
        return {
            "ok": True,
            "action": "remove-sync-data",
            "game_id": game_id,
            "message": message,
            "details": {"installed_game_kept": True},
        }

    def _normalize_linux_runtime_override(self, raw: str) -> str:
        value = str(raw or "").strip().lower()
        allowed = {"", "native", "wine", "proton", "proton-ge"}
        if value not in allowed:
            raise ValueError("invalid_linux_windows_runtime")
        return value

    def _get_game_linux_runtime_override(self, game_id: str) -> str:
        game_key = str(game_id or "").strip()
        if not game_key or self._state.database is None:
            return ""
        row = self._state.database.connection.execute(
            """
            SELECT linux_runtime
            FROM game_launch_settings
            WHERE game_id = ?
            """,
            (game_key,),
        ).fetchone()
        if row is None:
            return ""
        try:
            return self._normalize_linux_runtime_override(str(row[0] if row else ""))
        except ValueError:
            return ""

    def _effective_linux_runtime_for_game(self, game_id: str) -> str:
        override = self._get_game_linux_runtime_override(game_id)
        if override:
            return override
        metadata = self._game_metadata(game_id)
        recommended_runtime = (
            str(metadata.runner or "").strip().lower() if metadata is not None else ""
        )
        if recommended_runtime in {"native", "wine", "proton", "proton-ge"}:
            return recommended_runtime
        if self._state.user_settings is None:
            return "wine"
        return str(self._state.user_settings.linux_windows_runtime or "wine").strip()

    def _normalize_linux_leave_terminal_open(self, raw: object) -> bool:
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, str):
            return str(raw).strip().lower() in {"1", "true", "yes", "on"}
        return bool(raw)

    def _get_game_linux_leave_terminal_open(self, game_id: str) -> bool:
        game_key = str(game_id or "").strip()
        if not game_key or self._state.database is None:
            return False
        row = self._state.database.connection.execute(
            """
            SELECT linux_leave_terminal_open
            FROM game_launch_settings
            WHERE game_id = ?
            """,
            (game_key,),
        ).fetchone()
        if row is None:
            return False
        return bool(int(row[0] or 0))

    def _game_launch_settings_read(self, game_id: str) -> dict:
        if self._state.database is None:
            return {
                "ok": False,
                "message": "database_unavailable",
                "game_id": str(game_id or "").strip(),
                "linux_runtime_override": "",
                "linux_leave_terminal_open": False,
                "effective_linux_runtime": "wine",
            }
        game_key = str(game_id or "").strip()
        if not game_key:
            return {
                "ok": False,
                "message": "invalid_game_id",
                "game_id": "",
                "linux_runtime_override": "",
                "linux_leave_terminal_open": False,
                "effective_linux_runtime": "wine",
            }
        override = self._get_game_linux_runtime_override(game_key)
        return {
            "ok": True,
            "message": "ok",
            "game_id": game_key,
            "linux_runtime_override": override,
            "linux_leave_terminal_open": self._get_game_linux_leave_terminal_open(
                game_key
            ),
            "effective_linux_runtime": self._effective_linux_runtime_for_game(game_key),
        }

    def _game_launch_settings_update(self, game_id: str, payload: dict) -> dict:
        if self._state.database is None:
            return {
                "ok": False,
                "message": "database_unavailable",
                "game_id": str(game_id or "").strip(),
                "linux_runtime_override": "",
                "linux_leave_terminal_open": False,
                "effective_linux_runtime": "wine",
            }
        game_key = str(game_id or "").strip()
        if not game_key:
            return {
                "ok": False,
                "message": "invalid_game_id",
                "game_id": "",
                "linux_runtime_override": "",
                "linux_leave_terminal_open": False,
                "effective_linux_runtime": "wine",
            }
        try:
            current_override = self._get_game_linux_runtime_override(game_key)
            current_leave_terminal_open = self._get_game_linux_leave_terminal_open(
                game_key
            )
            override = self._normalize_linux_runtime_override(
                str(payload.get("linux_runtime_override", current_override))
            )
            leave_terminal_open = self._normalize_linux_leave_terminal_open(
                payload.get("linux_leave_terminal_open", current_leave_terminal_open)
            )
        except ValueError as exc:
            return {
                "ok": False,
                "message": str(exc),
                "game_id": game_key,
                "linux_runtime_override": "",
                "linux_leave_terminal_open": False,
                "effective_linux_runtime": self._effective_linux_runtime_for_game(
                    game_key
                ),
            }
        with self._state.database.connection:
            if override or leave_terminal_open:
                self._state.database.connection.execute(
                    """
                    INSERT INTO game_launch_settings(
                        game_id,
                        linux_runtime,
                        linux_leave_terminal_open,
                        updated_at
                    )
                    VALUES (?, ?, ?, datetime('now'))
                    ON CONFLICT(game_id) DO UPDATE SET
                        linux_runtime = excluded.linux_runtime,
                        linux_leave_terminal_open = excluded.linux_leave_terminal_open,
                        updated_at = datetime('now')
                    """,
                    (game_key, override, int(leave_terminal_open)),
                )
            else:
                self._state.database.connection.execute(
                    "DELETE FROM game_launch_settings WHERE game_id = ?",
                    (game_key,),
                )
        return {
            "ok": True,
            "message": "saved",
            "game_id": game_key,
            "linux_runtime_override": override,
            "linux_leave_terminal_open": leave_terminal_open,
            "effective_linux_runtime": self._effective_linux_runtime_for_game(game_key),
        }

    def _delete_game_action(
        self, game_id: str, *, ignore_sync_errors: bool = False
    ) -> dict:
        if self._state.repository is None:
            return {
                "ok": False,
                "action": "delete",
                "game_id": game_id,
                "message": "repository_unavailable",
                "details": {},
            }

        folder = Path(self._effective_library_path()) / game_id
        provider = self._state.sync_provider
        game_provider_type = ""
        game = self._state.repository.get_game(game_id, locale="en") or {}
        game_provider_type = (
            str(game.get("game_provider_type", "") or "").strip().lower()
        )
        if game_provider_type == "local":
            removed_rows = self._state.repository.remove_catalog_game(game_id)
            if removed_rows <= 0:
                return {
                    "ok": False,
                    "action": "delete",
                    "game_id": game_id,
                    "message": "game_not_found",
                    "details": {},
                }
            # Local entries own only their database record; the user-managed game
            # directory and its metadata sidecar must remain untouched.
            return {
                "ok": True,
                "action": "delete",
                "game_id": game_id,
                "message": "deleted",
                "details": {
                    "folder": str(folder),
                    "local_data_preserved": True,
                    "database_rows_removed": removed_rows,
                    "sync_removed": False,
                    "sync_detail": "not_synced",
                },
            }
        sync_removed = False
        sync_detail = "not_synced"
        if provider is not None and game_provider_type != "local":
            ok, detail = provider.remove_folder_sync(str(folder))
            if not ok:
                if not ignore_sync_errors:
                    return {
                        "ok": False,
                        "action": "delete",
                        "game_id": game_id,
                        "message": "sync_remove_failed",
                        "details": {"folder": str(folder), "sync_error": detail},
                    }
                logging.getLogger(__name__).warning(
                    "delete_game_sync_remove_failed_ignored game_id=%s folder=%s error=%s",
                    game_id,
                    str(folder),
                    detail,
                )
                sync_detail = detail
            else:
                sync_removed = True
                sync_detail = detail
                # Resilio can keep file handles shortly after remove_folder; give it time to release.
                time.sleep(0.75)

        if folder.exists():
            last_error = None
            for attempt in range(5):
                try:
                    if folder.is_dir():
                        shutil.rmtree(folder)
                    else:
                        folder.unlink()
                    last_error = None
                    break
                except OSError as exc:
                    last_error = str(exc)
                    # Backoff for transient file handle locks on Windows.
                    time.sleep(0.35 + (attempt * 0.1))
            if last_error is not None:
                return {
                    "ok": False,
                    "action": "delete",
                    "game_id": game_id,
                    "message": "delete_folder_failed",
                    "details": {"folder": str(folder), "error": last_error},
                }

        self._state.repository.set_install_state(game_id, "missing", "")
        if self._state.install_retry_after is not None:
            self._state.install_retry_after.pop(game_id, None)
        if self._state.install_failed_archive_signatures is not None:
            self._state.install_failed_archive_signatures.pop(game_id, None)
        self._refresh_game_index_if_changed()
        if str(self._state.current_game_id or "").strip().lower() == game_id.lower():
            self._state.current_game_id = ""
            self._schedule_stats_report(force=True)

        return {
            "ok": True,
            "action": "delete",
            "game_id": game_id,
            "message": "deleted",
            "details": {
                "folder": str(folder),
                "sync_removed": sync_removed,
                "sync_detail": sync_detail,
            },
        }

    def _provider_items(self, only_enabled: bool = True) -> list[dict]:
        if self._state.database is None:
            return []
        sql = """
            SELECT
                game_id,
                sync_enabled,
                is_game_provider,
                has_game_db,
                packed_image_path,
                packed_image_password
            FROM extra_sync_items
            WHERE is_game_provider = 1
            ORDER BY game_id
        """
        try:
            rows = self._state.database.connection.execute(sql).fetchall()
        except sqlite3.OperationalError:
            # Older persisted databases may not have provider columns yet.
            return []
        items: list[dict] = []
        for row in rows:
            game_id = str(row[0] if len(row) > 0 else "").strip()
            sync_enabled = bool(row[1]) if len(row) > 1 else False
            is_game_provider = bool(row[2]) if len(row) > 2 else False
            has_game_db = bool(row[3]) if len(row) > 3 else False
            packed_image_path = str(row[4] if len(row) > 4 else "").strip()
            packed_image_password = str(row[5] if len(row) > 5 else "").strip()
            if not game_id or not is_game_provider:
                continue
            if only_enabled and not sync_enabled:
                continue
            items.append(
                {
                    "game_id": game_id,
                    "sync_enabled": sync_enabled,
                    "is_game_provider": is_game_provider,
                    "has_game_db": has_game_db,
                    "packed_image_path": packed_image_path,
                    "packed_image_password": packed_image_password,
                }
            )
        return items

    def _game_metadata(self, game_id: str):
        lan_lookup = getattr(self._state.repository, "lan_game_metadata", None)
        lan_metadata = lan_lookup(game_id) if callable(lan_lookup) else None
        if isinstance(lan_metadata, GameMetadata):
            return lan_metadata
        game_key = str(game_id or "").strip()
        local_metadata = None
        if game_key:
            if self._state.local_metadata_stores is None:
                self._state.local_metadata_stores = {}
            game_root = Path(self._effective_library_path()) / game_key
            for source_root in (game_root / ".ouisync", game_root):
                cache_key = str(source_root)
                store = self._state.local_metadata_stores.get(cache_key)
                if store is None:
                    store = MetadataStore(source_root)
                    self._state.local_metadata_stores[cache_key] = store
                metadata = store.get_game_folder_metadata(game_key)
                if metadata is not None:
                    local_metadata = metadata
                    break
            # Read old provider bundles during migration; new metadata is written to the game root.
            if local_metadata is None:
                legacy_store_root = game_root / "metadata"
                cache_key = str(legacy_store_root)
                store = self._state.local_metadata_stores.get(cache_key)
                if store is None:
                    store = MetadataStore(legacy_store_root)
                    self._state.local_metadata_stores[cache_key] = store
                local_metadata = store.get(game_key)
        index_metadata = None
        if self._state.game_index_store is not None:
            index_metadata = self._state.game_index_store.get(game_id)
        if (
            index_metadata is not None
            and index_metadata.distribution_provider == "ouisync"
        ):
            if local_metadata is None:
                return index_metadata
            return replace(
                local_metadata,
                version=index_metadata.version or local_metadata.version,
                game_provider_type="ouisync",
                runner=index_metadata.runner or local_metadata.runner,
                description_fr=(
                    local_metadata.description_fr or index_metadata.description_fr
                ),
                size_gb=(
                    index_metadata.size_gb
                    if index_metadata.size_gb is not None
                    else local_metadata.size_gb
                ),
                master_required=(
                    index_metadata.master_required
                    if index_metadata.master_required is not None
                    else local_metadata.master_required
                ),
                game_start_file=(
                    local_metadata.game_start_file or index_metadata.game_start_file
                ),
                game_start_args=(
                    local_metadata.game_start_args or index_metadata.game_start_args
                ),
                installer_tasks=(
                    index_metadata.installer_tasks
                    or local_metadata.installer_tasks
                ),
                archive_file=index_metadata.archive_file or local_metadata.archive_file,
                archive_format=index_metadata.archive_format or local_metadata.archive_format,
                archive_sha256=index_metadata.archive_sha256 or local_metadata.archive_sha256,
                archive_version_file=(
                    index_metadata.archive_version_file
                    or local_metadata.archive_version_file
                ),
                distribution_provider="ouisync",
                distribution_read_token=index_metadata.distribution_read_token,
                distribution_info_hash=index_metadata.distribution_info_hash,
                distribution_editable_files=index_metadata.distribution_editable_files,
            )
        if local_metadata is not None:
            return local_metadata
        if self._state.metadata_store is not None:
            metadata = self._state.metadata_store.get(game_id)
            if metadata is not None:
                return metadata
        return index_metadata

    def _candidate_media_paths(
        self, game_id: str, folder_name: str, extension: str
    ) -> list[Path]:
        metadata = self._game_metadata(game_id)
        metadata_media = None
        if folder_name == "image":
            metadata_media = (
                str(metadata.image) if metadata is not None and metadata.image else None
            )
        elif folder_name == "video":
            metadata_media = (
                str(metadata.video) if metadata is not None and metadata.video else None
            )
        base = Path(self._effective_library_path())
        candidates: list[Path] = []
        if folder_name == "image" and self._state.repository is not None:
            lan_cover = self._state.repository.lan_cover_path(game_id)
            if lan_cover is not None:
                candidates.append(lan_cover)
        if metadata_media:
            media_path = Path(metadata_media)
            if not media_path.is_absolute():
                source_file = (
                    str(metadata.source_file)
                    if metadata is not None and metadata.source_file
                    else ""
                )
                if source_file:
                    media_path = (
                        Path(source_file).resolve(strict=False).parent / media_path
                    )
                elif self._state.metadata_root is not None:
                    media_path = self._state.metadata_root / media_path
            candidates.append(media_path)
        if folder_name == "image":
            for ext in ("jpg", "jpeg", "png", "webp"):
                candidates.append(
                    base / "eti_launcher" / folder_name / f"{game_id}.{ext}"
                )
        else:
            candidates.append(
                base / "eti_launcher" / folder_name / f"{game_id}.{extension}"
            )
        if folder_name == "image":
            # Backward-compatibility with legacy ETI launcher asset location on Windows.
            for ext in ("jpg", "jpeg", "png", "webp"):
                candidates.append(
                    Path(r"C:\Program Files\eti\LAN Launcher\assets")
                    / f"{game_id}.{ext}"
                )
        provider_ids: set[str] = set()
        for item in self._provider_items(only_enabled=True):
            provider_game_id = str(item.get("game_id", "") or "").strip()
            if not provider_game_id or provider_game_id == "eti_launcher":
                continue
            provider_ids.add(provider_game_id)
            provider_folder = base / provider_game_id / folder_name
            if folder_name == "image":
                for ext in ("jpg", "jpeg", "png", "webp"):
                    candidates.append(provider_folder / f"{game_id}.{ext}")
            else:
                candidates.append(provider_folder / f"{game_id}.{extension}")

        # Fallback: also probe any synced provider-like folder that contains update/game.db.
        # This keeps media replacement working even when provider metadata is incomplete.
        try:
            for entry in base.iterdir():
                if not entry.is_dir():
                    continue
                provider_game_id = entry.name.strip()
                if (
                    not provider_game_id
                    or provider_game_id == "eti_launcher"
                    or provider_game_id in provider_ids
                ):
                    continue
                if not (entry / "update" / "game.db").exists():
                    continue
                if folder_name == "image":
                    for ext in ("jpg", "jpeg", "png", "webp"):
                        candidates.append(entry / folder_name / f"{game_id}.{ext}")
                else:
                    candidates.append(entry / folder_name / f"{game_id}.{extension}")
        except OSError:
            pass
        return candidates

    @staticmethod
    def _safe_relative_provider_path(raw_path: str) -> Path | None:
        value = str(raw_path or "").strip().replace("\\", "/")
        if not value:
            return None
        candidate = Path(value)
        if candidate.is_absolute() or ".." in candidate.parts:
            return None
        return candidate

    def _resolve_unrar_binary(self) -> str:
        if self._state.platform_adapter is not None and (
            self._state.platform_adapter.platform_name() == "windows"
        ):
            if DEFAULT_WINDOWS_UNRAR_PATH.exists():
                return str(DEFAULT_WINDOWS_UNRAR_PATH)
            return shutil.which("unrar") or ""
        return shutil.which("unrar") or ""

    def _extract_provider_image_archive(
        self, archive: Path, target_dir: Path, password: str = ""
    ) -> bool:
        unrar_command = self._resolve_unrar_binary()
        if not unrar_command:
            logging.getLogger(__name__).warning(
                "provider_image_unrar_missing archive=%s", archive
            )
            return False

        cmd = [unrar_command, "x", "-o+", "-y"]
        if password:
            cmd.append(f"-p{password}")
        else:
            cmd.append("-p-")
        cmd.extend([str(archive), str(target_dir)])
        try:
            completed = subprocess.run(  # noqa: S603 - local bundled binary / system tool
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
        except OSError as exc:
            logging.getLogger(__name__).warning(
                "provider_image_unrar_launch_failed archive=%s error=%s",
                archive,
                exc,
            )
            return False
        if completed.returncode != 0:
            logging.getLogger(__name__).warning(
                "provider_image_unrar_failed archive=%s returncode=%s output=%s",
                archive,
                completed.returncode,
                (completed.stdout or "").strip(),
            )
            return False
        return True

    def _ensure_provider_image_archive_extracted(
        self,
        provider_game_id: str,
        provider_folder: Path,
        item: dict,
    ) -> None:
        archive_rel = self._safe_relative_provider_path(
            str(item.get("packed_image_path", "") or "")
        )
        if archive_rel is None:
            return
        archive = Path(self._effective_library_path()) / provider_game_id / archive_rel
        if not archive.exists() or not archive.is_file():
            return

        target_dir = provider_folder
        logger = logging.getLogger(__name__)
        try:
            archive_stat = archive.stat()
        except OSError:
            return
        marker_path = target_dir / ".llng-image-archive.json"
        try:
            target_exists = target_dir.exists()
            target_dir.mkdir(parents=True, exist_ok=True)
            if not target_exists:
                logger.info(
                    "provider_image_target_dir_created provider_game_id=%s target=%s",
                    provider_game_id,
                    target_dir,
                )
        except OSError as exc:
            logger.warning(
                "provider_image_target_create_failed provider_game_id=%s archive=%s target=%s error=%s",
                provider_game_id,
                archive,
                target_dir,
                exc,
            )
            return

        try:
            target_images = [
                path
                for path in target_dir.iterdir()
                if path.is_file()
                and path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
            ]
        except OSError:
            target_images = []

        marker_state = {
            "archive_mtime_ns": archive_stat.st_mtime_ns,
            "archive_size": archive_stat.st_size,
        }
        try:
            marker_state_existing = json.loads(marker_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            marker_state_existing = {}
        try:
            marker_mtime_ns = int(marker_state_existing.get("archive_mtime_ns", -1))
            marker_size = int(marker_state_existing.get("archive_size", -1))
        except (TypeError, ValueError):
            marker_mtime_ns = -1
            marker_size = -1
        if (
            marker_mtime_ns == marker_state["archive_mtime_ns"]
            and marker_size == marker_state["archive_size"]
            and target_images
        ):
            return

        cache_key = (
            f"{archive.resolve(strict=False)}|{archive_stat.st_mtime_ns}|"
            f"{archive_stat.st_size}|{str(item.get('packed_image_password', '') or '')}"
        )
        now = time.monotonic()
        with self._provider_image_archive_cache_lock:
            cached = self._provider_image_archive_cache.get(cache_key)
            if cached is not None:
                cached_at, cached_ok = cached
                if cached_ok:
                    return
                if (now - cached_at) < 30.0:
                    return

        logger.info(
            "provider_image_archive_extracting provider_game_id=%s archive=%s target=%s existing_images=%s",
            provider_game_id,
            archive,
            target_dir,
            len(target_images),
        )
        ok = self._extract_provider_image_archive(
            archive=archive,
            target_dir=target_dir,
            password=str(item.get("packed_image_password", "") or ""),
        )
        if ok:
            logger.info(
                "provider_image_archive_extracted provider_game_id=%s archive=%s target=%s",
                provider_game_id,
                archive,
                target_dir,
            )
            try:
                marker_path.write_text(
                    json.dumps(marker_state, separators=(",", ":"), sort_keys=True),
                    encoding="utf-8",
                )
            except OSError as exc:
                logger.warning(
                    "provider_image_target_marker_write_failed provider_game_id=%s archive=%s target=%s error=%s",
                    provider_game_id,
                    archive,
                    target_dir,
                    exc,
                )
            return
        with self._provider_image_archive_cache_lock:
            self._provider_image_archive_cache[cache_key] = (now, False)

    def _refresh_provider_image_archives(
        self, provider_game_id: str | None = None
    ) -> dict:
        logger = logging.getLogger(__name__)
        if self._state.database is None:
            return {
                "ok": False,
                "message": "database_unavailable",
                "refreshed": 0,
                "game_id": str(provider_game_id or "").strip(),
            }
        normalized_game_id = str(provider_game_id or "").strip()
        items = self._provider_items(only_enabled=False)
        if normalized_game_id:
            items = [
                item
                for item in items
                if str(item.get("game_id", "")).strip() == normalized_game_id
            ]
            if not items:
                return {
                    "ok": False,
                    "message": "extra_sync_item_not_found",
                    "refreshed": 0,
                    "game_id": normalized_game_id,
                }

        refreshed = 0
        for item in items:
            game_id = str(item.get("game_id", "") or "").strip()
            if not game_id:
                continue
            provider_folder = Path(self._effective_library_path()) / game_id / "image"
            logger.debug(
                "provider_image_refresh_requested provider_game_id=%s target=%s",
                game_id,
                provider_folder,
            )
            self._ensure_provider_image_archive_extracted(
                provider_game_id=game_id,
                provider_folder=provider_folder,
                item=item,
            )
            refreshed += 1
        return {
            "ok": True,
            "message": "refreshed",
            "refreshed": refreshed,
            "game_id": normalized_game_id,
        }

    def _first_existing_path(self, candidates: list[Path]) -> Path | None:
        for candidate in candidates:
            if candidate.exists() and candidate.is_file():
                return candidate
        return None

    def _game_video_path(self, game_id: str) -> str:
        candidates = self._candidate_media_paths(game_id, "video", "mp4")
        candidate = self._first_existing_path(candidates)
        if candidate is None:
            candidate = candidates[0]
        if self._state.platform_adapter is not None:
            normalized = self._state.platform_adapter.normalize_path(str(candidate))
            return normalized
        return str(candidate)

    def _game_image_path(self, game_id: str) -> str:
        candidates = self._candidate_media_paths(game_id, "image", "jpg")
        candidate = self._first_existing_path(candidates)
        if candidate is None:
            candidate = candidates[0]
        if self._state.platform_adapter is not None:
            normalized = self._state.platform_adapter.normalize_path(str(candidate))
            return normalized
        return str(candidate)

    def _folder_sync_status(self, folder: Path, expected_size_gb: float) -> dict:
        provider = self._state.sync_provider
        if provider is None:
            return {
                "active": False,
                "progress_percent": 0,
                "down_eta": 0,
                "down_speed": 0,
                "down_status": 0,
            }
        provider_status = provider.folder_sync_status(str(folder))
        provider_for_game = getattr(provider, "provider_for_game", None)
        if callable(provider_for_game):
            game_provider = provider_for_game(folder.name)
            if game_provider is not None:
                try:
                    provider_status = game_provider.folder_sync_status(str(folder))
                except Exception as exc:  # noqa: BLE001
                    logging.getLogger(__name__).warning(
                        "folder_sync_status_routed_failed folder=%s error=%s",
                        folder,
                        exc,
                    )
        active = bool(provider_status.get("active", False))
        progress = int(provider_status.get("progress_percent", 0) or 0)
        down_eta = int(provider_status.get("down_eta", 0) or 0)
        down_speed = int(provider_status.get("down_speed", 0) or 0)
        down_status = int(provider_status.get("down_status", 0) or 0)
        if (
            progress <= 0
            and expected_size_gb > 0
            and not provider_status.get("authoritative_progress", False)
        ):
            game_manager = self._state.game_manager
            archive = (
                game_manager.archive_path(folder.name)
                if game_manager is not None
                else folder / f"{folder.name}.eti"
            )
            if archive.is_file():
                try:
                    actual_bytes = float(archive.stat().st_size)
                    expected_bytes = expected_size_gb * (1024.0**3)
                    if expected_bytes > 0:
                        progress = int(
                            max(0, min(100, (actual_bytes / expected_bytes) * 100))
                        )
                except OSError:
                    progress = 0
        if down_eta <= 0 and active and down_speed > 0 and progress < 100:
            down_eta = self._estimate_down_eta_seconds(
                provider_status=provider_status,
                expected_size_gb=expected_size_gb,
                progress_percent=progress,
                down_speed_bps=down_speed,
            )
        if down_status <= 0 and active and progress < 100:
            down_status = 1
        return {
            "active": active,
            "progress_percent": max(0, min(100, progress)),
            "down_eta": max(0, down_eta),
            "down_speed": max(0, down_speed),
            "down_status": max(0, down_status),
        }

    def _estimate_down_eta_seconds(
        self,
        provider_status: dict,
        expected_size_gb: float,
        progress_percent: int,
        down_speed_bps: int,
    ) -> int:
        if down_speed_bps <= 0:
            return 0
        safe_progress = max(0, min(100, int(progress_percent or 0)))
        if safe_progress >= 100:
            return 0

        downloaded_bytes = provider_status.get("downloaded_bytes")
        total_bytes = provider_status.get("total_bytes")
        downloaded = (
            float(downloaded_bytes)
            if isinstance(downloaded_bytes, (int, float))
            else -1.0
        )
        total = float(total_bytes) if isinstance(total_bytes, (int, float)) else 0.0

        if total <= 0 and expected_size_gb > 0:
            total = expected_size_gb * (1024.0**3)

        if downloaded < 0 and total > 0 and safe_progress > 0:
            # Reconstruct downloaded bytes from percent when provider byte counters are unavailable.
            downloaded = total * (safe_progress / 100.0)

        if total <= 0:
            return 0
        if downloaded < 0:
            downloaded = 0.0
        remaining = max(0.0, total - downloaded)
        if remaining <= 0:
            return 0
        eta_seconds = int(remaining / float(down_speed_bps))
        return max(1, eta_seconds)

    def _game_sync_status_payload(self, game_id: str) -> dict:
        logger = logging.getLogger(__name__)
        if self._is_game_disabled(game_id):
            return {
                "ok": False,
                "message": "game_disabled_by_launcher_ini",
                "active": False,
                "progress_percent": 0,
            }
        if self._state.repository is None:
            return {
                "ok": False,
                "message": "repository_unavailable",
                "active": False,
                "progress_percent": 0,
            }
        game = self._state.repository.get_game(game_id, locale="en")
        if game is None:
            return {
                "ok": False,
                "message": "game_not_found",
                "active": False,
                "progress_percent": 0,
            }
        provider_type = str(game.get("game_provider_type", "") or "").strip().lower()
        folder = Path(self._effective_library_path()) / game_id
        if provider_type == "local":
            install_state = str(game.get("install_state", "") or "missing").lower()
            if install_state not in {"missing", "installed"}:
                install_state = "missing"
            if install_state == "installed" and not self._installed_game_ready(folder):
                install_state = "missing"
            needs_update = bool(game.get("needs_update", False))
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "game_sync_state_resolved local game_id=%s db_install_state=%s resolved_install_state=%s",
                    game_id,
                    str(game.get("install_state", "") or "missing").lower(),
                    install_state,
                )
            return {
                "ok": True,
                "message": "ok",
                "install_state": install_state,
                "sync_state": install_state,
                "installed": install_state == "installed",
                "needs_update": needs_update,
                "installed_version": str(game.get("installed_version", "") or ""),
                "version": str(game.get("version", "") or ""),
                "install_console_lines": self._install_console_snapshot(game_id),
                "active": False,
                "progress_percent": 0,
                "down_eta": 0,
                "down_speed": 0,
                "down_status": 0,
                "upload_speed": 0,
            }
        status = self._folder_sync_status(folder, float(game.get("size_gb", 0) or 0))
        if provider_type == "ouisync":
            provider = self._sync_provider_for_game(game_id)
            status_reader = getattr(provider, "folder_sync_status", None)
            if callable(status_reader):
                try:
                    status.update(
                        status_reader(str(self._ouisync_game_repository_path(game_id)))
                    )
                except Exception:
                    pass
        materialization = {}
        if provider_type == "ouisync":
            provider = self._sync_provider_for_game(game_id)
            get_materialization = getattr(provider, "game_materialization_status", None)
            if callable(get_materialization):
                materialization = get_materialization(game_id)
                phase = str(materialization.get("phase", "idle"))
                status["materialization_phase"] = phase
                status["materialization_error"] = str(
                    materialization.get("error", "") or ""
                )
                if phase in {"queued", "syncing"}:
                    status["active"] = True
                    status["progress_percent"] = int(
                        materialization.get("progress_percent", 0) or 0
                    )
                elif phase == "complete":
                    status["progress_percent"] = 100
        install_state = str(game.get("install_state", "") or "missing").lower()
        if install_state not in {"missing", "downloading", "installing", "installed"}:
            install_state = "missing"
        if install_state == "installed" and not self._installed_game_ready(folder):
            install_state = "missing"
        sync_state = install_state
        active = bool(status.get("active", False))
        progress_percent = int(status.get("progress_percent", 0) or 0)
        sync_only_mode = bool(
            self._state.user_settings is not None
            and self._state.user_settings.sync_only_mode
        )
        if active and install_state != "installing":
            if progress_percent < 100:
                # Installed games keep installed precedence so they remain startable while
                # Resilio indexes or updates content in the background.
                sync_state = (
                    "syncing" if install_state == "installed" else "downloading"
                )
            elif sync_only_mode and install_state != "installed":
                # In sync-only mode a completed archive is ready for optional manual
                # extraction, but it is not considered installed yet.
                sync_state = "ready_to_install"
        installed = install_state == "installed"
        needs_update = (
            bool(game.get("needs_update", False)) and install_state != "installing"
        )
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "game_sync_state_resolved game_id=%s db_install_state=%s resolved_install_state=%s resolved_sync_state=%s active=%s progress=%s needs_update=%s",
                game_id,
                str(game.get("install_state", "") or "missing").lower(),
                install_state,
                sync_state,
                bool(status.get("active", False)),
                int(status.get("progress_percent", 0) or 0),
                needs_update,
            )
        install_console_lines = self._install_console_snapshot(game_id)
        return {
            "ok": True,
            "message": "ok",
            "install_state": install_state,
            "sync_state": sync_state,
            "installed": installed,
            "needs_update": needs_update,
            "installed_version": str(game.get("installed_version", "") or ""),
            "version": str(game.get("version", "") or ""),
            "install_console_lines": install_console_lines,
            **status,
        }

    def _installed_game_ready(self, game_dir: Path) -> bool:
        local_dir = game_dir / "local"
        if not (local_dir.exists() and local_dir.is_dir()):
            return False
        metadata = self._game_metadata(game_dir.name)
        if metadata is not None:
            start_file = str(metadata.game_start_file or "").strip()
            if start_file:
                candidate = game_dir / Path(start_file.replace("\\", "/"))
                if candidate.exists() and candidate.is_file():
                    return True
        return any(
            (game_dir / script_name).exists()
            for script_name in ("game_start.cmd", "game_start.sh")
        )

    def _game_sync_status(self, game_id: str) -> dict:
        return self._game_sync_status_payload(game_id)

    def _game_sync_start(self, game_id: str) -> dict:
        if self._is_game_disabled(game_id):
            return {
                "ok": False,
                "message": "game_disabled_by_launcher_ini",
                "active": False,
                "progress_percent": 0,
            }
        if self._state.repository is None:
            return {
                "ok": False,
                "message": "repository_unavailable",
                "active": False,
                "progress_percent": 0,
            }
        if self._state.sync_provider is None:
            return {
                "ok": False,
                "message": "sync_provider_unavailable",
                "active": False,
                "progress_percent": 0,
            }
        game = self._state.repository.get_game(game_id, locale="en")
        if game is None:
            return {
                "ok": False,
                "message": "game_not_found",
                "active": False,
                "progress_percent": 0,
            }
        if str(game.get("game_provider_type", "") or "").strip().lower() == "local":
            return {
                "ok": False,
                "message": "local_game_no_sync",
                "active": False,
                "progress_percent": 0,
            }
        available_lookup = getattr(self._state.repository, "lan_game_available", None)
        if (
            self._lan_mode() == "client"
            and callable(available_lookup)
            and available_lookup(game_id) is False
        ):
            return {
                "ok": False,
                "message": "lan_game_unavailable",
                "active": False,
                "progress_percent": 0,
            }
        key = str(game.get("key", "") or "").strip()
        provider_type = self._resolve_game_provider_type(game_id)
        if provider_type == "ouisync":
            access = self._ouisync_game_access(game_id)
            provider = self._sync_provider_for_game(game_id)
            start_materialization = getattr(
                provider, "start_game_materialization", None
            )
            if access is None or not callable(start_materialization):
                return {
                    "ok": False,
                    "message": "ouisync_catalog_access_unavailable",
                    "active": False,
                    "progress_percent": 0,
                }
            folder = Path(self._effective_library_path()) / game_id
            folder.mkdir(parents=True, exist_ok=True)
            try:
                repository_path = self._ouisync_game_repository_path(game_id)
            except ValueError as exc:
                return {
                    "ok": False,
                    "message": str(exc),
                    "active": False,
                    "progress_percent": 0,
                }
            ok, detail = start_materialization(
                access, str(folder), str(repository_path)
            )
            if (
                ok
                and self._state.repository.current_install_state(game_id) != "installed"
            ):
                self._state.repository.set_install_state(
                    game_id, "downloading", str(game.get("installed_version", "") or "")
                )
            status = self._game_sync_status_payload(game_id)
            if ok:
                status.update(active=True, sync_state="downloading")
            return {
                **status,
                "ok": ok,
                "message": detail if not ok else "started",
            }
        if not key:
            return {
                "ok": False,
                "message": "game_key_missing",
                "active": False,
                "progress_percent": 0,
            }

        folder = Path(self._effective_library_path()) / game_id
        folder.mkdir(parents=True, exist_ok=True)
        provider_type = self._resolve_game_provider_type(game_id)
        provider = self._sync_provider_for_game(game_id)
        if provider is None:
            return {
                "ok": False,
                "message": "sync_provider_unavailable",
                "active": False,
                "progress_percent": 0,
            }
        lan_game = (
            provider_type == "ouisync"
            and self._lan_mode() == "client"
            and self._is_lan_catalog_game(game_id)
        )
        if lan_game:
            activate = getattr(provider, "ensure_lan_game_synced", None)
            ok, detail = (
                activate(str(folder), key)
                if callable(activate)
                else (False, "sync_provider_unavailable")
            )
        else:
            if provider_type and hasattr(
                self._state.sync_provider, "ensure_folder_synced_for_game"
            ):
                ok, detail = self._state.sync_provider.ensure_folder_synced_for_game(
                    game_id, str(folder), key, provider_type
                )
            else:
                ok, detail = provider.ensure_folder_synced(str(folder), key)
        if ok:
            current_state = self._state.repository.current_install_state(game_id)
            if current_state != "installed":
                self._state.repository.set_install_state(
                    game_id, "downloading", str(game.get("installed_version", "") or "")
                )
        status = self._game_sync_status_payload(game_id)
        if ok:
            status["active"] = True
        return {"ok": ok, "message": detail if not ok else "started", **status}

    def _game_sync_stop(self, game_id: str) -> dict:
        if self._is_game_disabled(game_id):
            return {
                "ok": False,
                "message": "game_disabled_by_launcher_ini",
                "active": False,
                "progress_percent": 0,
            }
        if self._state.sync_provider is None or self._state.repository is None:
            return {
                "ok": False,
                "message": "sync_provider_unavailable",
                "active": False,
                "progress_percent": 0,
            }
        game = self._state.repository.get_game(game_id, locale="en")
        if (
            game is not None
            and str(game.get("game_provider_type", "") or "").strip().lower() == "local"
        ):
            return {
                "ok": False,
                "message": "local_game_no_sync",
                "active": False,
                "progress_percent": 0,
            }
        was_installed = (
            str(game.get("install_state", "")).lower() == "installed"
            if game is not None
            else False
        )
        previous_version = (
            str(game.get("installed_version", "") or "") if game is not None else ""
        )
        folder = Path(self._effective_library_path()) / game_id
        provider_type = self._resolve_game_provider_type(game_id)
        provider = self._sync_provider_for_game(game_id)
        if provider is None:
            return {
                "ok": False,
                "message": "sync_provider_unavailable",
                "active": False,
                "progress_percent": 0,
            }
        if provider_type == "ouisync":
            cancel_materialization = getattr(
                provider, "cancel_game_materialization", None
            )
            if callable(cancel_materialization):
                cancel_materialization(game_id)
            try:
                repository_path = self._ouisync_game_repository_path(game_id)
            except ValueError as exc:
                return {
                    "ok": False,
                    "message": str(exc),
                    "active": False,
                    "progress_percent": 0,
                }
            ok, detail = provider.remove_folder_sync(str(repository_path))
        elif provider_type and hasattr(
            self._state.sync_provider, "remove_folder_sync_for_game"
        ):
            ok, detail = self._state.sync_provider.remove_folder_sync_for_game(
                game_id, str(folder), provider_type
            )
        else:
            ok, detail = provider.remove_folder_sync(str(folder))
        if not ok:
            status = self._folder_sync_status(folder, 0)
            return {"ok": False, "message": detail, **status}

        if provider_type == "ouisync":
            if was_installed:
                self._state.repository.set_install_state(
                    game_id, "installed", previous_version
                )
            else:
                self._state.repository.set_install_state(game_id, "missing", "")
            status = self._game_sync_status_payload(game_id)
            status["active"] = False
            return {"ok": True, "message": "stopped", **status}

        game_manager = self._state.game_manager
        archive_file = (
            game_manager.archive_path(game_id)
            if game_manager is not None
            else folder / f"{game_id}.eti"
        )
        try:
            archive_file.unlink(missing_ok=True)
        except OSError as exc:
            return {
                "ok": False,
                "message": str(exc),
                **self._folder_sync_status(folder, 0),
            }
        if was_installed:
            self._state.repository.set_install_state(
                game_id, "installed", previous_version
            )
        else:
            self._state.repository.set_install_state(game_id, "missing", "")
        status = self._game_sync_status_payload(game_id)
        status["active"] = False
        return {"ok": True, "message": "stopped", **status}

    def _effective_library_path(self) -> str:
        if self._state.platform_adapter is None or self._state.user_settings is None:
            return self._config.library_path
        if self._state.platform_adapter.platform_name() == "windows":
            return f"{self._state.user_settings.windows_game_drive_letter}:/{self._config.windows_lan_root}"
        return self._state.user_settings.linux_install_path

    def _provider_root_path(self) -> Path:
        return Path(self._effective_library_path()) / "ng_provider"

    def _set_game_index_provider_path(self, library_path: str | Path) -> None:
        store = self._state.game_index_store
        if store is None:
            return
        store.set_local_index_path(
            Path(library_path) / "ng_provider" / "update" / "index.json"
        )

    def _provider_tools_root_path(self) -> Path:
        return self._provider_root_path() / "tools"

    def _resolve_provider_winetricks_path(self) -> str:
        # Hand the canonical provider path to the adapter even before sync has
        # populated it; the Linux adapter validates the file before executing it.
        return str(self._provider_tools_root_path() / "winetricks" / "winetricks")

    def _resolve_provider_winetricks_cache_path(self) -> str:
        return str(self._provider_tools_root_path() / "winetricks" / "cache")

    def _extra_sync_items_read(self) -> dict:
        if self._state.database is None:
            return {"items": []}
        rows = self._state.database.connection.execute(
            """
            SELECT
                game_id,
                game_key,
                title_en,
                title_de,
                release_year,
                publisher,
                size_gb,
                readme_en,
                readme_de,
                max_players,
                master_required,
                version,
                visible_in_gamelist,
                sync_enabled,
                is_game_provider,
                game_provider_type,
                has_game_db,
                packed_image_path,
                packed_image_password,
                is_seeded_default
            FROM extra_sync_items
            ORDER BY game_id
            """
        ).fetchall()
        items = []
        for row in rows:
            items.append(
                {
                    "game_id": str(row[0]),
                    "game_key": str(row[1]),
                    "title_en": str(row[2]),
                    "title_de": str(row[3]),
                    "release_year": str(row[4]),
                    "publisher": str(row[5]),
                    "size_gb": float(row[6]),
                    "readme_en": str(row[7]),
                    "readme_de": str(row[8]),
                    "max_players": str(row[9]),
                    "master_required": bool(row[10]),
                    "version": str(row[11]),
                    "visible_in_gamelist": bool(row[12]),
                    "sync_enabled": bool(row[13]),
                    "is_game_provider": bool(row[14]),
                    "game_provider_type": str(row[15]),
                    "has_game_db": bool(row[16]),
                    "packed_image_path": str(row[17]),
                    "packed_image_password": str(row[18]),
                    "is_seeded_default": bool(row[19]),
                }
            )
        return {"items": items}

    def _normalize_extra_sync_item_payload(self, payload: dict) -> dict:
        game_id = str(payload.get("game_id", "")).strip()
        if not game_id:
            raise ValueError("extra_sync_game_id_required")
        if "/" in game_id or "\\" in game_id or ":" in game_id:
            raise ValueError("extra_sync_game_id_invalid")
        # The ID becomes <library>/<game_id>; dot-only names ("." / "..") would
        # resolve to the library root or its parent.
        if set(game_id) <= {"."} or any(ord(char) < 32 for char in game_id):
            raise ValueError("extra_sync_game_id_invalid")
        if len(game_id) > 128:
            raise ValueError("extra_sync_game_id_too_long")

        game_key = str(payload.get("game_key", "")).strip()
        if not game_key:
            raise ValueError("extra_sync_game_key_required")

        title_en = str(payload.get("title_en", "")).strip()
        title_de = str(payload.get("title_de", "")).strip()
        if not title_en:
            raise ValueError("extra_sync_title_en_required")
        if not title_de:
            title_de = title_en

        release_year = str(payload.get("release_year", "")).strip()
        publisher = str(payload.get("publisher", "")).strip()
        readme_en = str(payload.get("readme_en", "")).strip()
        readme_de = str(payload.get("readme_de", "")).strip() or readme_en
        max_players = str(payload.get("max_players", "")).strip()
        version = str(payload.get("version", "")).strip()

        try:
            size_gb = float(payload.get("size_gb", 0))
        except (TypeError, ValueError):
            raise ValueError("extra_sync_size_invalid") from None
        if size_gb < 0:
            raise ValueError("extra_sync_size_invalid")

        visible = bool(payload.get("visible_in_gamelist", True))
        sync_enabled = bool(payload.get("sync_enabled", True))
        master_required = bool(payload.get("master_required", False))
        is_game_provider = bool(payload.get("is_game_provider", False))
        game_provider_type = _coerce_game_provider_type(
            payload.get("game_provider_type", "resilio")
        )
        has_game_db = bool(payload.get("has_game_db", False))
        packed_image_path = str(payload.get("packed_image_path", "")).strip()
        if packed_image_path:
            packed_candidate = self._safe_relative_provider_path(packed_image_path)
            if packed_candidate is None:
                raise ValueError("extra_sync_packed_image_path_invalid")
            packed_image_path = packed_candidate.as_posix()
        packed_image_password = str(payload.get("packed_image_password", "")).strip()

        return {
            "game_id": game_id,
            "game_key": game_key,
            "title_en": title_en,
            "title_de": title_de,
            "release_year": release_year,
            "publisher": publisher,
            "size_gb": size_gb,
            "readme_en": readme_en,
            "readme_de": readme_de,
            "max_players": max_players,
            "master_required": master_required,
            "version": version,
            "visible_in_gamelist": visible,
            "sync_enabled": sync_enabled,
            "is_game_provider": is_game_provider,
            "game_provider_type": game_provider_type,
            "has_game_db": has_game_db,
            "packed_image_path": packed_image_path,
            "packed_image_password": packed_image_password,
        }

    def _extra_item_folder_path(self, game_id: str) -> Path:
        return Path(self._effective_library_path()) / game_id

    def _is_extra_sync_item_locked(self, game_id: str) -> bool:
        if self._state.database is None:
            return False
        try:
            row = self._state.database.connection.execute(
                "SELECT is_seeded_default FROM extra_sync_items WHERE game_id = ?",
                (game_id,),
            ).fetchone()
        except sqlite3.OperationalError:
            return False
        if row is None:
            return False
        value = row[0] if not isinstance(row, sqlite3.Row) else row["is_seeded_default"]
        return bool(value)

    def _extra_sync_apply_item(self, item: dict) -> tuple[bool, str]:
        provider = self._state.sync_provider
        if provider is None:
            return False, "sync_provider_unavailable"
        game_id = str(item.get("game_id", ""))
        folder = self._extra_item_folder_path(game_id)
        provider_type = _coerce_game_provider_type(item.get("game_provider_type", ""))
        logger = logging.getLogger(__name__)
        if bool(item.get("sync_enabled", False)):
            folder.mkdir(parents=True, exist_ok=True)
            if provider_type and hasattr(provider, "ensure_folder_synced_for_game"):
                result = provider.ensure_folder_synced_for_game(
                    game_id,
                    str(folder),
                    str(item.get("game_key", "")),
                    provider_type,
                )
            elif provider_type and hasattr(provider, "provider_for_type"):
                selected = provider.provider_for_type(provider_type)
                result = selected.ensure_folder_synced(
                    str(folder), str(item.get("game_key", ""))
                )
            else:
                result = provider.ensure_folder_synced(
                    str(folder), str(item.get("game_key", ""))
                )
            logger.info(
                "extra_sync_apply_result game_id=%s provider=%s enabled=true ok=%s detail=%s path=%s",
                game_id,
                provider_type or "default",
                bool(result[0]),
                result[1],
                folder,
            )
            return result
        if provider_type and hasattr(provider, "remove_folder_sync_for_game"):
            return provider.remove_folder_sync_for_game(
                game_id, str(folder), provider_type
            )
        if provider_type and hasattr(provider, "provider_for_type"):
            selected = provider.provider_for_type(provider_type)
            return selected.remove_folder_sync(str(folder))
        return provider.remove_folder_sync(str(folder))

    def _apply_all_extra_sync_items(self) -> tuple[bool, str]:
        payload = self._extra_sync_items_read()
        last_error = ""
        for item in payload.get("items", []):
            ok, detail = self._extra_sync_apply_item(item)
            if not ok:
                last_error = detail
                logging.getLogger(__name__).warning(
                    "extra_sync_apply_failed game_id=%s detail=%s",
                    item.get("game_id", ""),
                    detail,
                )
        return (last_error == ""), last_error

    def _reconcile_ng_provider_repository(self) -> None:
        """Verify the built-in seed is attached and retry attachment with backoff."""
        now = time.monotonic()
        if now < self._state.ouisync_seed_reconcile_next_at:
            return
        logger = logging.getLogger(__name__)
        self._state.ouisync_seed_reconcile_next_at = now + 30.0

        item = next(
            (
                entry
                for entry in self._extra_sync_items_read().get("items", [])
                if str(entry.get("game_id", "")).casefold() == "ng_provider"
            ),
            None,
        )
        if item is None or not item.get("sync_enabled"):
            logger.warning(
                "ng_provider_repository_reconcile_skipped reason=%s",
                "seed_missing" if item is None else "sync_disabled",
            )
            self._state.ouisync_seed_reconcile_next_at = now + 300.0
            return

        provider = self._sync_provider_for_type("ouisync")
        if provider is None or not bool(getattr(provider.status(), "running", False)):
            return
        token = str(item.get("game_key", "") or "").strip()
        ensure = getattr(provider, "ensure_folder_synced", None)
        if not token or not callable(ensure):
            logger.warning("ng_provider_repository_reconcile_unavailable")
            return

        token_status_fn = getattr(provider, "repository_token_status", None)
        try:
            token_status = (
                token_status_fn(token) if callable(token_status_fn) else {}
            )
        except Exception as exc:  # noqa: BLE001
            token_status = {}
            logger.warning("ng_provider_repository_status_failed error=%s", exc)
        if token_status.get("available") and token_status.get("attached"):
            self._queue_ng_provider_materialization(
                provider, token, token_status, self._extra_item_folder_path("ng_provider")
            )
            self._state.ouisync_seed_reconcile_next_at = now + 60.0
            logger.debug("ng_provider_repository_reconcile_attached=true")
            return

        folder = self._extra_item_folder_path("ng_provider")
        try:
            ok, detail = ensure(str(folder), token)
        except Exception as exc:  # noqa: BLE001
            ok, detail = False, str(exc)
        try:
            verified_status = (
                token_status_fn(token) if callable(token_status_fn) else {}
            )
        except Exception as exc:  # noqa: BLE001
            verified_status = {}
            logger.warning("ng_provider_repository_verify_failed error=%s", exc)
        attached = bool(
            verified_status.get("attached")
            if verified_status.get("available")
            else ok
        )
        self._state.ouisync_seed_reconcile_next_at = (
            now + 60.0 if attached else now + 30.0
        )
        log = logger.info if attached else logger.warning
        log(
            "ng_provider_repository_reconcile_result attached=%s ensure_ok=%s detail=%s path=%s",
            attached,
            bool(ok),
            detail,
            folder,
        )
        if attached and verified_status.get("available"):
            self._queue_ng_provider_materialization(
                provider, token, verified_status, folder
            )

    @staticmethod
    def _queue_ng_provider_materialization(
        provider: object, token: str, token_status: dict, folder: Path
    ) -> None:
        start = getattr(provider, "start_repository_materialization", None)
        info_hash = str(token_status.get("info_hash", "") or "").strip()
        if not callable(start) or not info_hash:
            return
        access = OuisyncRepositoryAccess(
            game_id="ng_provider",
            read_token=token,
            expected_info_hash=info_hash,
        )
        try:
            ok, detail = start(
                access,
                str(folder),
                materialized_directory=str(folder),
                marker_paths=(
                    "update/index.json",
                    "update/update-manifest.json",
                    "update/trusted-publishers.json",
                ),
            )
        except Exception as exc:  # noqa: BLE001
            logging.getLogger(__name__).warning(
                "ng_provider_materialization_queue_failed error=%s",
                type(exc).__name__,
            )
            return
        log = logging.getLogger(__name__).info if ok else logging.getLogger(__name__).warning
        log("ng_provider_materialization_queued ok=%s detail=%s", bool(ok), detail)

    def _extra_sync_item_upsert(self, payload: dict) -> dict:
        if self._state.database is None:
            return {"ok": False, "message": "database_unavailable", "items": []}
        body = payload if isinstance(payload, dict) else {}
        original_game_id = str(body.get("original_game_id", "")).strip()
        if original_game_id and self._is_extra_sync_item_locked(original_game_id):
            return {
                "ok": False,
                "message": "extra_sync_item_locked",
                **self._extra_sync_items_read(),
            }
        try:
            item = self._normalize_extra_sync_item_payload(body.get("item", body))
        except ValueError as exc:
            return {"ok": False, "message": str(exc), **self._extra_sync_items_read()}

        conn = self._state.database.connection
        with conn:
            existing = conn.execute(
                "SELECT game_id FROM extra_sync_items WHERE game_id = ?",
                (item["game_id"],),
            ).fetchone()
            if (
                original_game_id
                and original_game_id != item["game_id"]
                and existing is not None
            ):
                return {
                    "ok": False,
                    "message": "extra_sync_game_id_not_unique",
                    **self._extra_sync_items_read(),
                }
            if not original_game_id and existing is not None:
                return {
                    "ok": False,
                    "message": "extra_sync_game_id_not_unique",
                    **self._extra_sync_items_read(),
                }

            duplicate_catalog = conn.execute(
                "SELECT id FROM game_catalog WHERE id = ?",
                (item["game_id"],),
            ).fetchone()
            if duplicate_catalog is not None and original_game_id != item["game_id"]:
                return {
                    "ok": False,
                    "message": "extra_sync_game_id_not_unique",
                    **self._extra_sync_items_read(),
                }

            if original_game_id and original_game_id != item["game_id"]:
                conn.execute(
                    "DELETE FROM extra_sync_items WHERE game_id = ?",
                    (original_game_id,),
                )

            conn.execute(
                """
                INSERT INTO extra_sync_items(
                    game_id, game_key, title_en, title_de, release_year, publisher, size_gb,
                    readme_en, readme_de, max_players, master_required, version,
                    visible_in_gamelist, sync_enabled, is_game_provider, game_provider_type,
                    has_game_db, packed_image_path, packed_image_password, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(game_id) DO UPDATE SET
                    game_key = excluded.game_key,
                    title_en = excluded.title_en,
                    title_de = excluded.title_de,
                    release_year = excluded.release_year,
                    publisher = excluded.publisher,
                    size_gb = excluded.size_gb,
                    readme_en = excluded.readme_en,
                    readme_de = excluded.readme_de,
                    max_players = excluded.max_players,
                    master_required = excluded.master_required,
                    version = excluded.version,
                    visible_in_gamelist = excluded.visible_in_gamelist,
                    sync_enabled = excluded.sync_enabled,
                    is_game_provider = excluded.is_game_provider,
                    game_provider_type = excluded.game_provider_type,
                    has_game_db = excluded.has_game_db,
                    packed_image_path = excluded.packed_image_path,
                    packed_image_password = excluded.packed_image_password,
                    updated_at = datetime('now')
                """,
                (
                    item["game_id"],
                    item["game_key"],
                    item["title_en"],
                    item["title_de"],
                    item["release_year"],
                    item["publisher"],
                    item["size_gb"],
                    item["readme_en"],
                    item["readme_de"],
                    item["max_players"],
                    1 if item["master_required"] else 0,
                    item["version"],
                    1 if item["visible_in_gamelist"] else 0,
                    1 if item["sync_enabled"] else 0,
                    1 if item["is_game_provider"] else 0,
                    _coerce_game_provider_type(
                        item.get("game_provider_type", "resilio")
                    ),
                    1 if item["has_game_db"] else 0,
                    item["packed_image_path"],
                    item["packed_image_password"],
                ),
            )

        ok, detail = self._apply_all_extra_sync_items()
        if not ok:
            return {
                "ok": False,
                "message": detail or "extra_sync_apply_failed",
                **self._extra_sync_items_read(),
            }
        return {"ok": True, "message": "saved", **self._extra_sync_items_read()}

    def _extra_sync_items_import_bootstrap(self, payload: dict) -> dict:
        if self._state.database is None:
            return {"ok": False, "message": "database_unavailable", "items": []}
        source_items = payload.get("items") if isinstance(payload, dict) else None
        if not isinstance(source_items, list) or len(source_items) > 200:
            return {
                "ok": False,
                "message": "extra_sync_bootstrap_invalid",
                **self._extra_sync_items_read(),
            }
        if any(not isinstance(item, dict) for item in source_items):
            return {
                "ok": False,
                "message": "extra_sync_bootstrap_invalid",
                **self._extra_sync_items_read(),
            }

        provider_items = [
            item for item in source_items if item.get("is_game_provider") is True
        ]
        if not provider_items:
            return {
                "ok": False,
                "message": "extra_sync_bootstrap_no_providers",
                **self._extra_sync_items_read(),
            }
        try:
            normalized_items = [
                self._normalize_extra_sync_item_payload(item)
                for item in provider_items
            ]
        except ValueError:
            return {
                "ok": False,
                "message": "extra_sync_bootstrap_invalid_item",
                **self._extra_sync_items_read(),
            }
        if any(
            item["game_provider_type"] not in {"resilio", "ouisync"}
            for item in normalized_items
        ):
            return {
                "ok": False,
                "message": "extra_sync_bootstrap_invalid_item",
                **self._extra_sync_items_read(),
            }

        conn = self._state.database.connection
        ids = [item["game_id"].casefold() for item in normalized_items]
        if len(set(ids)) != len(ids):
            return {
                "ok": False,
                "message": "extra_sync_bootstrap_duplicate",
                **self._extra_sync_items_read(),
            }
        existing_ids = {
            str(row[0]).casefold()
            for row in conn.execute("SELECT game_id FROM extra_sync_items")
        }
        catalog_ids = {
            str(row[0]).casefold() for row in conn.execute("SELECT id FROM game_catalog")
        }
        if any(game_id in existing_ids or game_id in catalog_ids for game_id in ids):
            return {
                "ok": False,
                "message": "extra_sync_bootstrap_duplicate",
                **self._extra_sync_items_read(),
            }

        with conn:
            conn.executemany(
                """
                INSERT INTO extra_sync_items(
                    game_id, game_key, title_en, title_de, release_year, publisher,
                    size_gb, readme_en, readme_de, max_players, master_required,
                    version, visible_in_gamelist, sync_enabled, is_game_provider,
                    game_provider_type, has_game_db, packed_image_path,
                    packed_image_password, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                """,
                [
                    (
                        item["game_id"],
                        item["game_key"],
                        item["title_en"],
                        item["title_de"],
                        item["release_year"],
                        item["publisher"],
                        item["size_gb"],
                        item["readme_en"],
                        item["readme_de"],
                        item["max_players"],
                        1 if item["master_required"] else 0,
                        item["version"],
                        1 if item["visible_in_gamelist"] else 0,
                        1 if item["sync_enabled"] else 0,
                        1,
                        item["game_provider_type"],
                        1 if item["has_game_db"] else 0,
                        item["packed_image_path"],
                        item["packed_image_password"],
                    )
                    for item in normalized_items
                ],
            )

        failure = ""
        for item in normalized_items:
            try:
                ok, detail = self._extra_sync_apply_item(item)
            except Exception as exc:  # noqa: BLE001 - roll back on any provider failure
                ok, detail = False, ""
                logging.getLogger(__name__).warning(
                    "extra_sync_bootstrap_apply_error game_id=%s error=%s",
                    item["game_id"],
                    exc,
                )
            if not ok:
                failure = detail or "extra_sync_apply_failed"
                break
        if failure:
            # Keep the import atomic: a failed apply must not leave rows behind,
            # otherwise every retry would be rejected as a duplicate.
            for item in normalized_items:
                try:
                    self._extra_sync_apply_item({**item, "sync_enabled": False})
                except Exception as exc:  # noqa: BLE001 - best-effort detach
                    logging.getLogger(__name__).warning(
                        "extra_sync_bootstrap_rollback_error game_id=%s error=%s",
                        item["game_id"],
                        exc,
                    )
            with conn:
                conn.executemany(
                    "DELETE FROM extra_sync_items WHERE game_id = ?",
                    [(item["game_id"],) for item in normalized_items],
                )
            return {
                "ok": False,
                "message": failure,
                "imported": 0,
                **self._extra_sync_items_read(),
            }
        return {
            "ok": True,
            "message": "imported",
            "imported": len(normalized_items),
            **self._extra_sync_items_read(),
        }

    def _extra_sync_item_toggle(self, payload: dict) -> dict:
        if self._state.database is None:
            return {"ok": False, "message": "database_unavailable", "items": []}
        body = payload if isinstance(payload, dict) else {}
        game_id = str(body.get("game_id", "")).strip()
        if not game_id:
            return {
                "ok": False,
                "message": "extra_sync_game_id_required",
                **self._extra_sync_items_read(),
            }
        sync_enabled = bool(body.get("sync_enabled", False))
        conn = self._state.database.connection
        with conn:
            updated = conn.execute(
                "UPDATE extra_sync_items SET sync_enabled = ?, updated_at = datetime('now') WHERE game_id = ?",
                (1 if sync_enabled else 0, game_id),
            ).rowcount
        if updated == 0:
            return {
                "ok": False,
                "message": "extra_sync_item_not_found",
                **self._extra_sync_items_read(),
            }
        item = next(
            (
                entry
                for entry in self._extra_sync_items_read()["items"]
                if entry["game_id"] == game_id
            ),
            None,
        )
        if item is None:
            return {
                "ok": False,
                "message": "extra_sync_item_not_found",
                **self._extra_sync_items_read(),
            }
        _ = item
        ok, detail = self._apply_all_extra_sync_items()
        if not ok:
            return {
                "ok": False,
                "message": detail or "extra_sync_apply_failed",
                **self._extra_sync_items_read(),
            }
        return {"ok": True, "message": "saved", **self._extra_sync_items_read()}

    def _extra_sync_item_refresh_images(self, payload: dict) -> dict:
        if self._state.database is None:
            return {"ok": False, "message": "database_unavailable", "items": []}
        body = payload if isinstance(payload, dict) else {}
        game_id = str(body.get("game_id", "")).strip()
        if not game_id:
            return {
                "ok": False,
                "message": "extra_sync_game_id_required",
                **self._extra_sync_items_read(),
            }
        item = next(
            (
                entry
                for entry in self._extra_sync_items_read()["items"]
                if entry["game_id"] == game_id
            ),
            None,
        )
        if item is None:
            return {
                "ok": False,
                "message": "extra_sync_item_not_found",
                **self._extra_sync_items_read(),
            }
        if not bool(item.get("is_game_provider", False)):
            return {
                "ok": False,
                "message": "extra_sync_item_not_provider",
                **self._extra_sync_items_read(),
            }
        result = self._refresh_provider_image_archives(game_id)
        if not result.get("ok", False):
            return {
                "ok": False,
                "message": str(
                    result.get("message", "extra_sync_image_refresh_failed")
                ),
                **self._extra_sync_items_read(),
            }
        return {
            "ok": True,
            "message": "refreshed",
            "refreshed": result.get("refreshed", 0),
            **self._extra_sync_items_read(),
        }

    def _extra_sync_item_delete(self, payload: dict) -> dict:
        return self._extra_sync_item_remove(payload, delete_data=False, wipe=False)

    def _extra_sync_item_delete_data(self, payload: dict) -> dict:
        return self._extra_sync_item_remove(payload, delete_data=True, wipe=False)

    def _extra_sync_item_wipe(self, payload: dict) -> dict:
        return self._extra_sync_item_remove(payload, delete_data=True, wipe=True)

    def _extra_sync_item_remove(
        self, payload: dict, delete_data: bool, wipe: bool
    ) -> dict:
        if self._state.database is None:
            return {"ok": False, "message": "database_unavailable", "items": []}
        body = payload if isinstance(payload, dict) else {}
        game_id = str(body.get("game_id", "")).strip()
        if not game_id:
            return {
                "ok": False,
                "message": "extra_sync_game_id_required",
                **self._extra_sync_items_read(),
            }
        if self._is_extra_sync_item_locked(game_id):
            return {
                "ok": False,
                "message": "extra_sync_item_locked",
                **self._extra_sync_items_read(),
            }

        folder = self._extra_item_folder_path(game_id)
        provider = self._state.sync_provider
        if provider is not None:
            ok, detail = provider.remove_folder_sync(str(folder))
            if not ok:
                return {"ok": False, "message": detail, **self._extra_sync_items_read()}

        if delete_data and folder.exists():
            try:
                if folder.is_dir():
                    shutil.rmtree(folder)
                else:
                    folder.unlink()
            except OSError as exc:
                return {
                    "ok": False,
                    "message": str(exc),
                    **self._extra_sync_items_read(),
                }

        if wipe or not delete_data:
            with self._state.database.connection:
                deleted = self._state.database.connection.execute(
                    "DELETE FROM extra_sync_items WHERE game_id = ?",
                    (game_id,),
                ).rowcount
            if deleted == 0:
                return {
                    "ok": False,
                    "message": "extra_sync_item_not_found",
                    **self._extra_sync_items_read(),
                }
        else:
            with self._state.database.connection:
                updated = self._state.database.connection.execute(
                    "UPDATE extra_sync_items SET sync_enabled = 0, updated_at = datetime('now') WHERE game_id = ?",
                    (game_id,),
                ).rowcount
            if updated == 0:
                return {
                    "ok": False,
                    "message": "extra_sync_item_not_found",
                    **self._extra_sync_items_read(),
                }

        return {"ok": True, "message": "saved", **self._extra_sync_items_read()}

    def _ensure_default_extra_sync_item(self) -> None:
        if self._state.database is None:
            return
        defaults = self._load_default_extra_sync_items()
        if not defaults:
            return
        logger = logging.getLogger(__name__)
        with self._state.database.connection:
            default_ids = {item["game_id"].casefold() for item in defaults}
            seeded_rows = self._state.database.connection.execute(
                "SELECT game_id FROM extra_sync_items WHERE is_seeded_default = 1"
            ).fetchall()
            for row in seeded_rows:
                if row[0].casefold() not in default_ids:
                    self._state.database.connection.execute(
                        "DELETE FROM extra_sync_items WHERE game_id = ?",
                        (row[0],),
                    )
            for item in defaults:
                existing = self._state.database.connection.execute(
                    "SELECT 1 FROM extra_sync_items WHERE game_id = ?",
                    (item["game_id"],),
                ).fetchone()
                self._state.database.connection.execute(
                    "DELETE FROM extra_sync_items WHERE game_id = ?",
                    (item["game_id"],),
                )
                # Keep the shipped defaults authoritative so startup repairs
                # stale local rows instead of leaving older values in place.
                self._state.database.connection.execute(
                    """
                    INSERT INTO extra_sync_items(
                        game_id, game_key, title_en, title_de, release_year, publisher, size_gb,
                        readme_en, readme_de, max_players, master_required, version,
                        visible_in_gamelist, sync_enabled, is_game_provider, game_provider_type,
                        has_game_db, packed_image_path, packed_image_password, is_seeded_default, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                    """,
                    (
                        item["game_id"],
                        item["game_key"],
                        item["title_en"],
                        item["title_de"],
                        item["release_year"],
                        item["publisher"],
                        item["size_gb"],
                        item["readme_en"],
                        item["readme_de"],
                        item["max_players"],
                        1 if item["master_required"] else 0,
                        item["version"],
                        1 if item["visible_in_gamelist"] else 0,
                        1 if item["sync_enabled"] else 0,
                        1 if item["is_game_provider"] else 0,
                        _coerce_game_provider_type(
                            item.get("game_provider_type", "resilio")
                        ),
                        1 if item["has_game_db"] else 0,
                        item["packed_image_path"],
                        item["packed_image_password"],
                        1,
                    ),
                )
                logger.info(
                    "default_extra_sync_item_%s game_id=%s title=%s",
                    "updated" if existing is not None else "added",
                    item["game_id"],
                    item["title_en"],
                )

    def _load_default_extra_sync_items(self) -> list[dict]:
        candidates = [
            Path(self._config.default_extra_sync_items_path).expanduser(),
            Path(self._config.optional_extra_sync_items_path).expanduser(),
        ]
        legacy_candidate = Path("config/default-extra-sync-items.json")
        if legacy_candidate not in candidates:
            candidates.append(legacy_candidate)
        resolved_candidates: list[Path] = []
        runtime_root = self._runtime_root_path()
        for candidate in candidates:
            if candidate.is_absolute():
                resolved_candidates.append(candidate)
                continue
            runtime_candidate = (runtime_root / candidate).resolve(strict=False)
            if runtime_candidate.exists():
                resolved_candidates.append(runtime_candidate)
                continue
            cwd_candidate = (Path.cwd() / candidate).resolve(strict=False)
            if cwd_candidate.exists():
                resolved_candidates.append(cwd_candidate)
        existing_paths = list(
            dict.fromkeys(path for path in resolved_candidates if path.exists())
        )
        if not existing_paths:
            logging.getLogger(__name__).warning(
                "default_extra_sync_items_missing path=%s",
                self._config.default_extra_sync_items_path,
            )
            return []
        normalized: list[dict] = []
        normalized_ids: set[str] = set()
        for raw_path in existing_paths:
            try:
                data = json.loads(raw_path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                logging.getLogger(__name__).warning(
                    "default_extra_sync_items_load_failed path=%s error=%s",
                    raw_path,
                    exc,
                )
                continue
            rows = data.get("items", []) if isinstance(data, dict) else data
            if not isinstance(rows, list):
                logging.getLogger(__name__).warning(
                    "default_extra_sync_items_invalid_format path=%s",
                    raw_path,
                )
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                try:
                    item = self._normalize_extra_sync_item_payload(row)
                except ValueError as exc:
                    logging.getLogger(__name__).warning(
                        "default_extra_sync_item_invalid path=%s game_id=%s error=%s",
                        raw_path,
                        str(row.get("game_id", "")).strip(),
                        exc,
                    )
                    continue
                item_id = item["game_id"].casefold()
                if item_id in normalized_ids:
                    logging.getLogger(__name__).warning(
                        "default_extra_sync_item_duplicate_ignored path=%s game_id=%s",
                        raw_path,
                        item["game_id"],
                    )
                    continue
                normalized_ids.add(item_id)
                normalized.append(item)
        return normalized

    def _launcher_site_lock(self) -> Lock:
        if self._state.launcher_site_lock is None:
            self._state.launcher_site_lock = Lock()
        return self._state.launcher_site_lock

    def _launcher_site_state_path(self) -> Path:
        return Path("data") / "launcher-site-state.json"

    def _current_launcher_site_snapshot(self) -> LauncherSiteSnapshot:
        with self._launcher_site_lock():
            if self._state.launcher_site_snapshot is None:
                self._state.launcher_site_snapshot = default_snapshot(
                    source_url=self._config.launcher_ini_url or DEFAULT_LAUNCHER_INI_URL
                )
            return self._state.launcher_site_snapshot

    def _set_launcher_site_snapshot(self, snapshot: LauncherSiteSnapshot) -> None:
        with self._launcher_site_lock():
            self._state.launcher_site_snapshot = snapshot

    def _load_launcher_site_snapshot_from_cache(self) -> None:
        path = self._launcher_site_state_path()
        if not path.exists() or not path.is_file():
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(payload, dict):
            return
        try:
            snapshot = LauncherSiteSnapshot.from_dict(payload)
        except Exception:  # noqa: BLE001
            return
        self._set_launcher_site_snapshot(snapshot)

    def _save_launcher_site_snapshot_to_cache(
        self, snapshot: LauncherSiteSnapshot
    ) -> None:
        path = self._launcher_site_state_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(snapshot.to_dict(), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError as exc:
            logging.getLogger(__name__).warning(
                "launcher_site_cache_write_failed path=%s error=%s",
                path,
                exc,
            )

    def _disabled_game_ids(self) -> list[str]:
        if isinstance(self._state.lan_settings_snapshot, dict):
            return []
        snapshot = self._current_launcher_site_snapshot()
        return list(snapshot.disable_games)

    def _lan_disabled_game_ids(self) -> list[str]:
        if not isinstance(self._state.lan_settings_snapshot, dict):
            return []
        return list(self._state.lan_settings_snapshot.get("disable_games", []))

    def _is_game_disabled(self, game_id: str) -> bool:
        normalized = str(game_id or "").strip().lower()
        if not normalized:
            return False
        return normalized in set(self._disabled_game_ids())

    def _launcher_site_read(self) -> dict:
        payload = self._current_launcher_site_snapshot().to_dict()
        lan_settings = self._state.lan_settings_snapshot
        has_server_settings = isinstance(lan_settings, dict)
        if has_server_settings:
            payload.update(
                {
                    "lan_title": lan_settings.get("lan_title", ""),
                    "lan_url": lan_settings.get("lan_url", ""),
                    "stats_url": lan_settings.get("stats_url", ""),
                    "discord_url": lan_settings.get("discord_url", ""),
                    "ts3_server": lan_settings.get("ts3_server", ""),
                    "links": lan_settings_display_links(lan_settings),
                    "disable_games": lan_settings.get("disable_games", []),
                    "managed_by_lan_server": True,
                }
            )
        else:
            payload["managed_by_lan_server"] = False
        return payload

    def _lan_server_settings_path(self) -> Path:
        return (
            Path(self._effective_library_path())
            / "locallansync"
            / ".ouisync"
            / "settings.json"
        )

    def _lan_settings_lock(self) -> Lock:
        if self._state.lan_settings_lock is None:
            self._state.lan_settings_lock = Lock()
        return self._state.lan_settings_lock

    def _lan_settings_from_site_snapshot(self) -> dict:
        site = self._current_launcher_site_snapshot()
        custom_links = [
            item for item in site.links if str(item.get("key", "")).startswith("link_")
        ]
        return new_lan_settings(
            disable_games=site.disable_games,
            lan_title=site.lan_title,
            lan_url=site.lan_url,
            stats_url=site.stats_url,
            discord_url=site.discord_url,
            ts3_server=site.ts3_server,
            links=custom_links,
        )

    def _ensure_lan_server_settings(self) -> None:
        if self._lan_mode() != "server":
            return
        path = self._lan_server_settings_path()
        if path.exists():
            self._try_import_lan_settings()
            return
        with self._lan_settings_lock():
            if path.exists():
                return
            try:
                snapshot = self._lan_settings_from_site_snapshot()
                publish_lan_settings(path, snapshot)
            except (OSError, InvalidLanSettings) as exc:
                logging.getLogger(__name__).warning(
                    "lan_settings_initial_publish_failed error=%s", exc
                )
                return
            self._state.lan_settings_snapshot = snapshot
            self._state.lan_settings_last_signature = (
                self._runtime_update_db_signature_for_path(path)
            )

    def _lan_server_assets_read(self) -> list[dict[str, str]]:
        repo = self._state.repository
        if repo is None:
            return []
        assets: dict[str, dict[str, str]] = {}
        for locale in ("en", "de"):
            for visibility in ("visible", "hidden"):
                try:
                    result = repo.list_games(
                        ListQuery(locale=locale, page_size=0, visibility=visibility)
                    )
                except (OSError, ValueError, sqlite3.Error, RuntimeError):
                    logging.getLogger(__name__).warning("lan_server_assets_read_failed")
                    return []
                for item in result.get("items", []):
                    if not isinstance(item, dict):
                        continue
                    game_id = str(item.get("id", "") or "").strip()
                    if not game_id:
                        continue
                    entry = assets.setdefault(
                        game_id.casefold(),
                        {"game_id": game_id, "title_en": game_id, "title_de": game_id},
                    )
                    entry[f"title_{locale}"] = str(item.get("title", "") or game_id)
        return sorted(assets.values(), key=lambda item: item["title_en"].casefold())

    def _lan_server_settings_update(self, payload: dict) -> dict:
        if self._lan_mode() != "server":
            return {"ok": False, "message": "lan_server_mode_required"}
        if not isinstance(payload, dict):
            return {"ok": False, "message": "lan_settings_invalid"}
        try:
            value = new_lan_settings(
                disable_games=payload.get("disable_games", []),
                lan_title=payload.get("lan_title", ""),
                lan_url=payload.get("lan_url", ""),
                stats_url=payload.get("stats_url", ""),
                discord_url=payload.get("discord_url", ""),
                ts3_server=payload.get("ts3_server", ""),
                links=payload.get("links", []),
            )
            path = self._lan_server_settings_path()
            with self._lan_settings_lock():
                publish_lan_settings(path, value)
                self._state.lan_settings_snapshot = value
                self._state.lan_settings_last_signature = (
                    self._runtime_update_db_signature_for_path(path)
                )
        except (OSError, InvalidLanSettings, TypeError, ValueError) as exc:
            message = (
                str(exc)
                if isinstance(exc, InvalidLanSettings)
                else "lan_settings_save_failed"
            )
            return {"ok": False, "message": message}
        return {"ok": True, "message": "saved", "settings": value}

    def _lan_server_settings_read(self) -> dict:
        if self._lan_mode() != "server":
            return {"ok": False, "message": "lan_server_mode_required"}
        settings = self._state.lan_settings_snapshot
        if not isinstance(settings, dict):
            settings = self._lan_settings_from_site_snapshot()
        return {
            "ok": True,
            "settings": settings,
            "assets": self._lan_server_assets_read(),
        }

    def _try_import_lan_settings(self) -> bool:
        path = self._lan_server_settings_path()
        signature = self._runtime_update_db_signature_for_path(path)
        if signature is None:
            return False
        with self._lan_settings_lock():
            if signature in {
                self._state.lan_settings_last_signature,
                self._state.lan_settings_failed_signature,
            }:
                return False
            try:
                snapshot = read_lan_settings(path)
            except (OSError, InvalidLanSettings) as exc:
                self._state.lan_settings_failed_signature = signature
                logging.getLogger(__name__).warning(
                    "lan_settings_import_failed error=%s", exc
                )
                return False
            self._state.lan_settings_snapshot = snapshot
            self._state.lan_settings_last_signature = signature
            self._state.lan_settings_failed_signature = None
            return True

    def _resolve_launcher_ini_url(self) -> str:
        snapshot = self._current_launcher_site_snapshot()
        return derive_launcher_ini_url(
            configured_url=self._config.launcher_ini_url,
            lan_url=snapshot.lan_url,
            fallback_url=snapshot.source_url or DEFAULT_LAUNCHER_INI_URL,
        )

    def _refresh_launcher_site_snapshot(self) -> None:
        logger = logging.getLogger(__name__)
        previous = self._current_launcher_site_snapshot()
        source_url = self._resolve_launcher_ini_url()
        timeout = max(0.5, float(self._config.launcher_request_timeout_seconds))
        try:
            with urlopen(source_url, timeout=timeout) as response:  # noqa: S310 URL is operator-controlled LAN endpoint
                body = response.read().decode("utf-8", errors="replace")
            snapshot = build_snapshot_from_ini(
                launcher_ini_text=body,
                source_url=source_url,
                fetched_at=time.time(),
            )
            self._set_launcher_site_snapshot(snapshot)
            self._save_launcher_site_snapshot_to_cache(snapshot)
        except Exception as exc:  # noqa: BLE001
            # Keep the last successful values; only mark endpoint as temporarily unreachable.
            snapshot = LauncherSiteSnapshot(
                source_url=source_url,
                reachable=False,
                last_success_at=previous.last_success_at,
                last_error=str(exc),
                lan_title=previous.lan_title,
                lan_url=previous.lan_url,
                stats_url=previous.stats_url,
                discord_url=previous.discord_url,
                ts3_server=previous.ts3_server,
                links=previous.links,
                disable_games=previous.disable_games,
            )
            self._set_launcher_site_snapshot(snapshot)
            logger.debug("launcher_ini_refresh_failed url=%s error=%s", source_url, exc)

    def _format_mac_address(self) -> str:
        node = uuid.getnode()
        return ":".join(f"{(node >> shift) & 0xFF:02x}" for shift in range(40, -1, -8))

    def _stats_payload(self) -> dict[str, str]:
        nickname = ""
        if self._state.user_settings is not None:
            nickname = str(self._state.user_settings.nickname or "").strip()
        cpu = str(platform.processor() or "").strip() or str(platform.machine() or "")
        return {
            "hostname": str(platform.node() or "").strip(),
            "macaddr1": self._format_mac_address(),
            "macaddr2": "",
            "board_manufacturer": str(platform.system() or "").strip(),
            "baseboard": str(platform.machine() or "").strip(),
            "system_product_name": str(platform.platform() or "").strip(),
            "bios_release": str(platform.version() or "").strip(),
            "cpu": cpu,
            "gpu": "",
            "windows_edition": str(platform.platform() or "").strip(),
            "player_name": nickname,
            "current_game": str(self._state.current_game_id or "").strip(),
        }

    def _send_stats_report(self) -> None:
        logger = logging.getLogger(__name__)
        try:
            snapshot = self._current_launcher_site_snapshot()
            if isinstance(self._state.lan_settings_snapshot, dict):
                stats_url = str(
                    self._state.lan_settings_snapshot.get("stats_url", "") or ""
                ).strip()
                if not stats_url:
                    return
            else:
                stats_url = derive_stats_url(snapshot)
            query = urlencode(self._stats_payload())
            separator = "&" if "?" in stats_url else "?"
            target = f"{stats_url}{separator}{query}"
            timeout = max(0.5, float(self._config.launcher_request_timeout_seconds))
            with urlopen(target, timeout=timeout) as response:  # noqa: S310 URL is operator-controlled LAN endpoint
                _ = response.read(64)
        except Exception as exc:  # noqa: BLE001
            logger.debug("launcher_stats_report_failed error=%s", exc)
        finally:
            with self._launcher_site_lock():
                self._state.stats_report_inflight = False

    def _schedule_stats_report(self, force: bool = False) -> None:
        now = time.time()
        interval = max(5.0, float(self._config.launcher_stats_interval_seconds))
        with self._launcher_site_lock():
            if self._state.stats_report_inflight:
                return
            if not force and (now - self._state.stats_report_last_sent_at) < interval:
                return
            self._state.stats_report_inflight = True
            self._state.stats_report_last_sent_at = now
        Thread(target=self._send_stats_report, daemon=True).start()

    def _run_launcher_site_watchdog(self) -> None:
        while True:
            if (
                self._state.launcher_site_stop is not None
                and self._state.launcher_site_stop.is_set()
            ):
                return
            try:
                if not isinstance(self._state.lan_settings_snapshot, dict):
                    self._refresh_launcher_site_snapshot()
                self._schedule_stats_report(force=False)
            except Exception as exc:  # noqa: BLE001
                logging.getLogger(__name__).warning(
                    "launcher_site_watchdog_error: %s", exc
                )
            poll_seconds = max(5.0, float(self._config.launcher_ini_poll_seconds))
            time.sleep(poll_seconds)

    def _provider_interfaces_payload(self) -> list[dict]:
        provider = self._state.sync_provider
        interfaces: list[dict] = []
        for provider_type, title in (
            ("ouisync", "Ouisync"),
            ("resilio", "Resilio"),
        ):
            selected = None
            if provider is not None:
                provider_for_type = getattr(provider, "provider_for_type", None)
                if callable(provider_for_type):
                    try:
                        selected = provider_for_type(provider_type)
                    except Exception as exc:  # noqa: BLE001
                        logging.getLogger(__name__).warning(
                            "provider_interface_resolve_failed provider=%s error=%s",
                            provider_type,
                            exc,
                        )
                elif provider_type == self._config.sync_provider.lower():
                    selected = provider

            url = ""
            iframe_url = ""
            running = False
            state = "stopped"
            pid: int | None = None
            last_error = ""
            if selected is not None:
                web_ui_url = getattr(selected, "web_ui_url", None)
                if callable(web_ui_url):
                    try:
                        url = str(web_ui_url() or "").strip()
                    except Exception as exc:  # noqa: BLE001
                        logging.getLogger(__name__).warning(
                            "provider_interface_url_failed provider=%s error=%s",
                            provider_type,
                            exc,
                        )
                iframe_url = url
                status_for_type_fn = getattr(provider, "status_for_type", None)
                status_fn = (
                    status_for_type_fn
                    if callable(status_for_type_fn)
                    else getattr(selected, "status", None)
                )
                if callable(status_fn):
                    try:
                        if callable(status_for_type_fn):
                            status = status_fn(provider_type)
                        else:
                            status = status_fn()
                        running = bool(getattr(status, "running", False))
                        state = str(getattr(status, "state", "stopped") or "stopped")
                        pid = getattr(status, "pid", None)
                        if pid is not None:
                            pid = int(pid)
                        last_error = str(
                            getattr(status, "last_error", "") or ""
                        ).strip()
                    except Exception as exc:  # noqa: BLE001
                        logging.getLogger(__name__).warning(
                            "provider_interface_status_failed provider=%s error=%s",
                            provider_type,
                            exc,
                        )

            interfaces.append(
                {
                    "provider_type": provider_type,
                    "title": title,
                    "iframe_url": iframe_url or url,
                    "open_url": url,
                    "available": running if provider_type == "ouisync" else bool(url),
                    "running": running,
                    "state": state,
                    "pid": pid,
                    "last_error": last_error,
                }
            )
        return interfaces

    def _extra_sync_ids_by_info_hash(self, provider: object) -> dict[str, str]:
        """Map Ouisync info hashes to extra-sync game IDs with one token lookup each."""
        tokens_by_game: dict[str, str] = {}
        for item in self._extra_sync_items_read().get("items", []):
            game_id = str(item.get("game_id", "")).strip()
            token = str(item.get("game_key", "")).strip()
            if game_id and token:
                tokens_by_game.setdefault(game_id, token)
        if not tokens_by_game:
            return {}
        resolve = getattr(provider, "share_token_info_hashes", None)
        hashes = resolve(list(tokens_by_game.values())) if callable(resolve) else None
        if isinstance(hashes, dict):
            token_hash = lambda token: str(hashes.get(token, "") or "")  # noqa: E731
        else:
            status_fn = getattr(provider, "repository_token_status", None)
            if not callable(status_fn):
                return {}

            def token_hash(token: str) -> str:
                status = status_fn(token)
                return str(status.get("info_hash", "")) if status.get("available") else ""

        mapping: dict[str, str] = {}
        for game_id, token in tokens_by_game.items():
            info_hash = str(token_hash(token) or "").lower()
            if info_hash:
                mapping.setdefault(info_hash, game_id)
        return mapping

    def _ouisync_repository_inventory_read(
        self, info_hash: str = "", directory_path: str = "/", locale: str = "en"
    ) -> dict:
        provider = self._sync_provider_for_type("ouisync")
        read_inventory = getattr(provider, "repository_inventory", None)
        if not callable(read_inventory):
            return {
                "available": False,
                "error": "ouisync_session_unavailable",
                "repositories": [],
                "catalog": [],
                "network": {},
            }
        result = read_inventory(info_hash, directory_path)
        store = self._state.game_index_store
        catalog_entries = (
            store.ouisync_catalog_entries(locale) if store is not None else []
        )
        titles_by_hash = {
            str(item["info_hash"]).lower(): item
            for item in catalog_entries
            if item.get("info_hash")
        }
        extra_ids_by_hash: dict[str, str] | None = None
        for repository in result.get("repositories", []):
            catalog_entry = titles_by_hash.get(
                str(repository.get("info_hash", "")).lower()
            )
            if catalog_entry is not None:
                repository["game_id"] = catalog_entry["game_id"]
                repository["label"] = catalog_entry["title"] or repository["label"]
                continue
            if str(repository.get("label", "")).strip().casefold() not in {
                "",
                "repository",
            }:
                continue
            if extra_ids_by_hash is None:
                extra_ids_by_hash = self._extra_sync_ids_by_info_hash(provider)
            game_id = extra_ids_by_hash.get(
                str(repository.get("info_hash", "")).lower()
            )
            if game_id:
                repository["game_id"] = game_id
                repository["label"] = game_id
        result["catalog"] = catalog_entries
        try:
            status = provider.status()
            result["provider"] = {
                "running": bool(status.running),
                "state": str(status.state),
                "pid": status.pid,
                "last_error": str(status.last_error or ""),
            }
        except Exception as exc:  # noqa: BLE001
            result["provider"] = {"running": False, "state": "failed", "last_error": type(exc).__name__}
        return result

    def _ouisync_repository_settings_update(
        self, info_hash: str, settings: dict
    ) -> dict:
        provider = self._sync_provider_for_type("ouisync")
        update_settings = getattr(provider, "update_repository_settings", None)
        if not callable(update_settings):
            return {"ok": False, "message": "sync_provider_unavailable"}
        return update_settings(info_hash, settings)

    def _ouisync_repository_game_id(self, info_hash: str) -> str:
        target_hash = str(info_hash or "").strip().lower()
        store = self._state.game_index_store
        if store is not None:
            for entry in store.ouisync_catalog_entries("en"):
                if str(entry.get("info_hash", "")).lower() == target_hash:
                    return str(entry.get("game_id", ""))
        provider = self._sync_provider_for_type("ouisync")
        return self._extra_sync_ids_by_info_hash(provider).get(target_hash, "")

    def _ouisync_repository_action(self, action: str, info_hash: str) -> dict:
        provider = self._sync_provider_for_type("ouisync")
        game_id = self._ouisync_repository_game_id(info_hash)
        if action == "mount":
            if (
                not game_id
                or Path(game_id).name != game_id
                or game_id in {".", ".."}
                or any(separator in game_id for separator in ("/", "\\", ":"))
            ):
                return {"ok": False, "message": "ouisync_repository_game_id_unknown"}
            method = getattr(provider, "mount_readonly_repository", None)
            if not callable(method):
                return {"ok": False, "message": "sync_provider_unavailable"}
            library_root = Path(self._effective_library_path()).expanduser().resolve(strict=False)
            game_directory = (library_root / game_id).resolve(strict=False)
            if not game_directory.is_relative_to(library_root):
                return {"ok": False, "message": "ouisync_repository_game_id_unknown"}
            return method(info_hash, str(game_directory))
        if action == "nudge":
            method = getattr(provider, "nudge_repository_sync", None)
        elif action == "unmount":
            method = getattr(provider, "unmount_repository", None)
        elif action == "force-unmount":
            method = getattr(provider, "force_unmount_repository", None)
        else:
            return {"ok": False, "message": "ouisync_mount_action_invalid"}
        if not callable(method):
            return {"ok": False, "message": "sync_provider_unavailable"}
        return method(info_hash)

    def _ouisync_peer_action(self, action: str, address: str) -> dict:
        provider = self._sync_provider_for_type("ouisync")
        method = getattr(provider, "update_user_provided_peer", None)
        if not callable(method):
            return {"ok": False, "message": "sync_provider_unavailable"}
        return method(str(action or "").strip().lower(), str(address or ""))

    def _ouisync_repository_entry_copy(
        self, info_hash: str, entry_path: str, destination_directory: str
    ) -> dict:
        game_id = self._ouisync_repository_game_id(info_hash)
        if (
            not game_id
            or Path(game_id).name != game_id
            or game_id in {".", ".."}
            or any(separator in game_id for separator in ("/", "\\", ":"))
        ):
            return {"ok": False, "message": "ouisync_repository_game_id_unknown"}
        provider = self._sync_provider_for_type("ouisync")
        copy_entry = getattr(provider, "copy_repository_entry_to_disk", None)
        if not callable(copy_entry):
            return {"ok": False, "message": "sync_provider_unavailable"}
        library_root = Path(self._effective_library_path()).expanduser().resolve(strict=False)
        game_directory = (library_root / game_id).resolve(strict=False)
        if not game_directory.is_relative_to(library_root):
            return {"ok": False, "message": "ouisync_repository_game_id_unknown"}
        return copy_entry(
            info_hash, entry_path, str(game_directory), destination_directory
        )

    def _ouisync_debug_action(self, action: str) -> dict:
        """Run a bounded Ouisync check or reattach the trusted provider seed."""
        mode = str(action or "").strip().lower()
        if mode not in {"health", "ng-provider", "reset-ng-provider"}:
            return {"ok": False, "message": "ouisync_debug_action_invalid", "lines": []}

        lines: list[dict[str, str]] = []

        def record(key: str, value: object = "", state: str = "") -> None:
            # Values are raw data (paths, counts) or "ui.*" locale keys; the
            # frontend translates keys and optional state words.
            line = {"key": key, "value": str(value)}
            if state:
                line["state"] = state
            lines.append(line)

        provider = self._sync_provider_for_type("ouisync")
        if provider is None:
            return {"ok": False, "message": "sync_provider_unavailable", "lines": []}
        try:
            status = provider.status()
        except Exception as exc:  # noqa: BLE001
            record("ui.ouisync_debug_provider_status_error", type(exc).__name__)
            return {"ok": False, "message": "ouisync_session_unavailable", "lines": lines}

        running = bool(getattr(status, "running", False))
        record(
            "ui.ouisync_debug_provider_status",
            getattr(status, "state", "unknown"),
        )
        if mode == "health":
            config_dir = Path(self._config.ouisync_config_dir).expanduser()
            if not config_dir.is_absolute():
                config_dir = Path(self._runtime_root_path()) / config_dir
            store_dir = config_dir / "repositories"
            record("ui.ouisync_debug_config_dir", config_dir)
            directories = getattr(provider, "store_directories", lambda: [str(store_dir)])()
            for path in directories:
                record(
                    "ui.ouisync_debug_store_dir",
                    path,
                    "present" if Path(path).is_dir() else "missing",
                )
            inventory = provider.repository_inventory()
            record("ui.ouisync_debug_session", "connected" if inventory.get("available") else inventory.get("error", "unavailable"))
            record("ui.ouisync_debug_repository_count", len(inventory.get("repositories", [])))
            record("ui.ouisync_debug_peer_count", inventory.get("peer_count", 0))
            logs = provider.debug_logs(limit=12) if hasattr(provider, "debug_logs") else []
            for entry in logs[-12:]:
                if isinstance(entry, dict):
                    record("ui.ouisync_debug_provider_log", entry.get("msg", entry))
            return {"ok": running and bool(inventory.get("available")), "message": "completed", "lines": lines}

        items = self._extra_sync_items_read().get("items", [])
        item = next((entry for entry in items if entry.get("game_id") == "ng_provider"), None)
        if item is None:
            record("ui.ouisync_debug_seed_missing")
            return {"ok": False, "message": "ng_provider_seed_missing", "lines": lines}
        configured_root = Path(self._effective_library_path()).expanduser() / "ng_provider"
        root_is_symlink = configured_root.is_symlink()
        root = configured_root.resolve(strict=False)
        repository_dir = root / ".ouisync"
        database_path = repository_dir / "repository.ouisyncdb"
        record("ui.ouisync_debug_seed_enabled", item.get("sync_enabled"))
        record("ui.ouisync_debug_provider_path", root)
        record("ui.ouisync_debug_repository_data", "present" if database_path.exists() else "missing")
        token_status = getattr(provider, "repository_token_status", lambda _token: {"available": False, "attached": False})(item.get("game_key", ""))
        record("ui.ouisync_debug_token", "available" if token_status.get("available") else token_status.get("error", "unavailable"))
        record("ui.ouisync_debug_repository_attached", token_status.get("attached", False))
        if mode == "ng-provider":
            return {
                "ok": bool(running and item.get("sync_enabled") and token_status.get("available") and token_status.get("attached")),
                "message": "completed",
                "lines": lines,
            }

        if not running:
            record("ui.ouisync_debug_reset_skipped", "ui.ouisync_debug_reason_not_running")
            return {"ok": False, "message": "ouisync_session_unavailable", "lines": lines}
        if not item.get("game_key"):
            record("ui.ouisync_debug_reset_skipped", "ui.ouisync_debug_reason_token_missing")
            return {"ok": False, "message": "ng_provider_seed_token_missing", "lines": lines}
        if root_is_symlink:
            record("ui.ouisync_debug_reset_skipped", "ui.ouisync_debug_reason_path_symlink")
            return {"ok": False, "message": "ng_provider_path_unsafe", "lines": lines}

        remove = getattr(provider, "remove_folder_sync", None)
        if callable(remove):
            removed, detail = remove(str(root))
            record("ui.ouisync_debug_repository_closed", detail)
            if not removed and detail != "ouisync_repository_not_found":
                return {"ok": False, "message": detail, "lines": lines}
        try:
            if root.exists():
                shutil.rmtree(root)
            root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            record("ui.ouisync_debug_reset_failed", f"{type(exc).__name__}: {exc}")
            return {"ok": False, "message": "ng_provider_reset_failed", "lines": lines}
        record("ui.ouisync_debug_local_cache_cleared", root)
        ensure = getattr(provider, "ensure_folder_synced", None)
        if not callable(ensure):
            return {"ok": False, "message": "sync_provider_unavailable", "lines": lines}
        attached, detail = ensure(str(root), str(item["game_key"]))
        record("ui.ouisync_debug_repository_reattach", detail)
        return {"ok": bool(attached), "message": detail, "lines": lines}

    def _settings_payload(self) -> dict:
        if self._state.user_settings is None or self._state.platform_adapter is None:
            return {
                "nickname": "",
                "theme": "dark",
                "log_level": "WARNING",
                "auto_start_sync": True,
                "sync_only_mode": False,
                "library_path_initialized": False,
                "windows_game_drive_letter": self._config.windows_game_drive_letter,
                "linux_install_path": default_linux_install_path(
                    "unknown", self._config.library_path
                ),
                "linux_windows_runtime": "wine",
                "linux_proton_path": "",
                "linux_proton_ge_path": "",
                "lan_mode": "client",
                "ouisync_storage_path": "",
                "platform": "unknown",
                "effective_library_path": self._config.library_path,
                "local_docs_file_url": local_docs_file_url(),
                "local_docs_file_path": local_docs_file_path(),
                "provider_interfaces": self._provider_interfaces_payload(),
            }
        settings = self._state.user_settings
        return {
            "nickname": settings.nickname,
            "theme": settings.theme,
            "log_level": settings.log_level,
            "auto_start_sync": settings.auto_start_sync,
            "sync_only_mode": settings.sync_only_mode,
            "library_path_initialized": settings.library_path_initialized,
            "windows_game_drive_letter": settings.windows_game_drive_letter,
            "linux_install_path": settings.linux_install_path,
            "linux_windows_runtime": settings.linux_windows_runtime,
            "linux_proton_path": settings.linux_proton_path,
            "linux_proton_ge_path": settings.linux_proton_ge_path,
            "lan_mode": settings.lan_mode,
            "ouisync_storage_path": settings.ouisync_storage_path,
            "platform": self._state.platform_adapter.platform_name(),
            "effective_library_path": self._effective_library_path(),
            "local_docs_file_url": local_docs_file_url(),
            "local_docs_file_path": local_docs_file_path(),
            "provider_interfaces": self._provider_interfaces_payload(),
        }

    def _validate_linux_runtime_settings(self, settings: UserSettings) -> str:
        if self._state.platform_adapter is None:
            return "platform_adapter_unavailable"
        if self._state.platform_adapter.platform_name() != "linux":
            return ""

        runtime = settings.linux_windows_runtime

        def _validate_binary(path: str, error_key: str, allow_path_lookup: bool) -> str:
            value = str(path or "").strip()
            if not value:
                if allow_path_lookup and shutil.which("proton"):
                    return ""
                return error_key
            if "/" in value:
                binary = Path(value)
                if not binary.exists():
                    return error_key
                if not binary.is_file():
                    return error_key
                return ""
            if shutil.which(value):
                return ""
            return error_key

        if runtime == "proton":
            return _validate_binary(
                settings.linux_proton_path,
                "linux_proton_path_invalid",
                allow_path_lookup=True,
            )
        if runtime == "proton-ge":
            return _validate_binary(
                settings.linux_proton_ge_path,
                "linux_proton_ge_path_invalid",
                allow_path_lookup=False,
            )
        return ""

    def _settings_read(self) -> dict:
        return self._settings_payload()

    def _settings_update(self, payload: dict) -> dict:
        if self._state.settings_store is None or self._state.user_settings is None:
            return {
                "ok": False,
                "message": "settings_unavailable",
                "settings": self._settings_payload(),
            }

        try:
            merged = self._state.settings_store.merge_and_validate(
                self._state.user_settings, payload
            )
            storage_text = str(merged.ouisync_storage_path or "").strip()
            if storage_text:
                storage_path = Path(storage_text).expanduser().resolve(strict=False)
                if storage_path.exists() and not storage_path.is_dir():
                    raise ValueError("ouisync_storage_path_invalid")
                storage_path.mkdir(parents=True, exist_ok=True)
                probe = storage_path / f".llng-write-check-{uuid.uuid4().hex}"
                descriptor = None
                try:
                    descriptor = os.open(
                        probe, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600
                    )
                except OSError as exc:
                    raise ValueError("ouisync_storage_path_invalid") from exc
                finally:
                    if descriptor is not None:
                        os.close(descriptor)
                        probe.unlink(missing_ok=True)
                merged = replace(merged, ouisync_storage_path=str(storage_path))
            current_storage = str(
                self._state.user_settings.ouisync_storage_path or ""
            ).strip()
            next_storage = str(merged.ouisync_storage_path or "").strip()
            retained_roots = list(
                self._state.user_settings.ouisync_storage_fallback_paths or []
            )
            if current_storage and current_storage != next_storage:
                old_root = str(Path(current_storage).expanduser().resolve(strict=False))
                retained_roots = [
                    value
                    for value in retained_roots
                    if str(Path(value).expanduser().resolve(strict=False)) != old_root
                ]
                retained_roots.append(old_root)
            merged = replace(
                merged,
                ouisync_storage_fallback_paths=retained_roots[-16:],
            )
            self._state.settings_store.save(merged)
        except ValueError as exc:
            return {
                "ok": False,
                "message": str(exc),
                "settings": self._settings_payload(),
            }
        except OSError as exc:
            return {
                "ok": False,
                "message": str(exc),
                "settings": self._settings_payload(),
            }

        self._state.user_settings = merged
        validation_error = self._validate_linux_runtime_settings(merged)
        if validation_error:
            return {
                "ok": False,
                "message": validation_error,
                "settings": self._settings_payload(),
            }
        set_log_level(merged.log_level)

        effective_path = self._effective_library_path()
        self._set_game_index_provider_path(effective_path)
        if self._state.platform_adapter is not None:
            validation = self._state.platform_adapter.validate_storage_path(
                effective_path
            )
            if not validation.ok:
                return {
                    "ok": False,
                    "message": validation.message,
                    "settings": self._settings_payload(),
                }
        if not self._persist_resilio_library_path(effective_path):
            return {
                "ok": False,
                "message": "sync_config_update_failed",
                "settings": self._settings_payload(),
            }

        merged = replace(merged, library_path_initialized=True)
        self._state.user_settings = merged
        if self._state.sync_watchdog_paused:
            self._state.desired_sync_running = False
        else:
            self._state.desired_sync_running = merged.auto_start_sync

        if self._state.scanner is not None:
            self._state.scanner.set_library_path(effective_path)
            self._state.scanner.scan(force=True)
        if self._state.game_manager is not None:
            self._state.game_manager.set_library_path(effective_path)
            self._state.game_manager.set_windows_drive_letter(
                merged.windows_game_drive_letter
            )
            self._state.game_manager.set_linux_runtime_settings(
                merged.linux_windows_runtime,
                merged.linux_proton_path,
                merged.linux_proton_ge_path,
            )
        logging.getLogger(__name__).info(
            "settings_updated nickname=%s theme=%s log_level=%s auto_start_sync=%s sync_only_mode=%s path=%s",
            merged.nickname,
            merged.theme,
            merged.log_level,
            merged.auto_start_sync,
            merged.sync_only_mode,
            effective_path,
        )

        return {"ok": True, "message": "saved", "settings": self._settings_payload()}

    def _app_log_level_update(self, payload: dict) -> dict:
        if self._state.settings_store is None or self._state.user_settings is None:
            return {
                "ok": False,
                "message": "settings_unavailable",
                "settings": self._settings_payload(),
            }
        candidate = str((payload or {}).get("level", "")).strip().upper()
        if candidate not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            return {
                "ok": False,
                "message": "invalid_log_level",
                "settings": self._settings_payload(),
            }
        merged = replace(self._state.user_settings, log_level=candidate)
        try:
            self._state.settings_store.save(merged)
        except OSError as exc:
            return {
                "ok": False,
                "message": str(exc),
                "settings": self._settings_payload(),
            }
        self._state.user_settings = merged
        set_log_level(candidate)
        logging.getLogger(__name__).info(
            "runtime_log_level_updated level=%s", candidate
        )
        return {"ok": True, "message": "saved", "settings": self._settings_payload()}

    def _log_timeline_lock(self) -> Lock:
        if self._state.log_timeline_lock is None:
            self._state.log_timeline_lock = Lock()
        return self._state.log_timeline_lock

    def _log_entry_source_order(self, source: str) -> int:
        normalized = str(source or "").strip().lower()
        if normalized == "lanlauncherng":
            return 0
        if normalized == "resilio":
            return 1
        if normalized == "ouisync":
            return 2
        return 3

    def _log_entry_timestamp(self, raw: object) -> float:
        text = str(raw or "").strip()
        if not text:
            return time.time()
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return time.time()
        if parsed.tzinfo is None:
            # Provider log files commonly use local wall-clock timestamps without
            # a timezone, while LLNG JSON logs are UTC. Treat naive timestamps as
            # local time so provider lines do not sort hours ahead of app logs.
            parsed = parsed.astimezone()
        return parsed.timestamp()

    def _log_cache_limit_key(self, limit: int) -> int:
        return max(1, min(2000, int(limit)))

    def _infer_log_source(self, raw: object, fallback: str) -> str:
        if isinstance(raw, dict):
            explicit = (
                str(raw.get("source", "") or raw.get("provider", "")).strip().lower()
            )
            if explicit in {"lanlauncherng", "resilio", "ouisync"}:
                return explicit
            logger = str(raw.get("logger", "")).strip().lower()
            if "resilio" in logger:
                return "resilio"
            if "ouisync" in logger:
                return "ouisync"
            if logger.startswith("src.core.") or logger.startswith("src."):
                return "lanlauncherng"
        fallback_source = str(fallback or "").strip().lower()
        return fallback_source or "lanlauncherng"

    def _normalize_timeline_entry(
        self, source: str, raw: object, default_level: str = ""
    ) -> dict | None:
        if isinstance(raw, str):
            msg = raw.strip()
            if not msg:
                return None
            return {
                "source": str(source or "").strip() or "unknown",
                "ts": datetime.now(timezone.utc).isoformat(),
                "level": default_level,
                "msg": msg,
            }
        if not isinstance(raw, dict):
            msg = str(raw or "").strip()
            if not msg:
                return None
            return {
                "source": str(source or "").strip() or "unknown",
                "ts": datetime.now(timezone.utc).isoformat(),
                "level": default_level,
                "msg": msg,
            }

        msg = str(
            raw.get("msg", "")
            or raw.get("message", "")
            or raw.get("line", "")
            or raw.get("text", "")
        ).strip()
        if not msg:
            return None
        ts = str(
            raw.get("ts", "") or raw.get("time", "") or raw.get("date", "")
        ).strip()
        level = str(raw.get("level", "") or default_level).strip()
        entry_source = self._infer_log_source(raw, source)
        if not ts and entry_source == "ouisync":
            match = re.match(
                r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2}))\s+(TRACE|DEBUG|INFO|WARN|ERROR)\s+(.*)$",
                msg,
                re.IGNORECASE,
            )
            if match:
                ts = match.group(1)
                level = str(raw.get("level", "") or match.group(2)).upper()
                msg = match.group(3).strip()
        if not ts:
            ts = datetime.now(timezone.utc).isoformat()
        return {
            "source": entry_source,
            "ts": ts,
            "level": level,
            "msg": msg,
        }

    def _log_dedupe_signature(self, entry: dict) -> tuple[str, str, str, str]:
        source = str(entry.get("source", "")).strip().lower()
        level = str(entry.get("level", "")).strip()
        msg = str(entry.get("msg", "")).strip()
        timestamp_bucket = f"{self._log_entry_timestamp(entry.get('ts')):.3f}"
        return (source, timestamp_bucket, level, msg)

    def _log_process_output_signature(self, entry: dict) -> tuple[str, str] | None:
        msg = str(entry.get("msg", "")).strip()
        if msg.startswith("sync_process_stdout="):
            return ("stdout", msg.removeprefix("sync_process_stdout=").strip())
        if msg.startswith("sync_process_stderr="):
            return ("stderr", msg.removeprefix("sync_process_stderr=").strip())
        if msg.startswith("[stdout] "):
            return ("stdout", msg.removeprefix("[stdout] ").strip())
        if msg.startswith("[stderr] "):
            return ("stderr", msg.removeprefix("[stderr] ").strip())
        return None

    def _dedupe_log_timeline_entries(self, entries: list[dict]) -> list[dict]:
        deduped: list[dict] = []
        seen_exact: set[tuple[str, str, str, str]] = set()
        process_output_index: dict[tuple[str, str, int], int] = {}
        for entry in entries:
            exact_signature = self._log_dedupe_signature(entry)
            if exact_signature in seen_exact:
                continue
            source = str(entry.get("source", "")).strip().lower()
            msg = str(entry.get("msg", "")).strip()
            process_signature = self._log_process_output_signature(entry)
            if process_signature is not None:
                process_key = (
                    process_signature[0],
                    process_signature[1],
                    int(self._log_entry_timestamp(entry.get("ts"))),
                )
                existing_index = process_output_index.get(process_key)
                if existing_index is not None:
                    existing = deduped[existing_index]
                    existing_source = str(existing.get("source", "")).strip().lower()
                    existing_msg = str(existing.get("msg", "")).strip()
                    # Prefer provider-owned rows over LLNG mirror rows for the same
                    # process output, otherwise Resilio startup stderr/stdout appears
                    # once as LANLauncherNG and once as Resilio in the UI.
                    existing_is_mirror = existing_msg.startswith(
                        ("sync_process_stdout=", "sync_process_stderr=")
                    )
                    current_is_mirror = msg.startswith(
                        ("sync_process_stdout=", "sync_process_stderr=")
                    )
                    if (
                        existing_source == "lanlauncherng" and source != "lanlauncherng"
                    ) or (existing_is_mirror and not current_is_mirror):
                        seen_exact.discard(self._log_dedupe_signature(existing))
                        deduped[existing_index] = entry
                        seen_exact.add(exact_signature)
                    continue
                process_output_index[process_key] = len(deduped)
            seen_exact.add(exact_signature)
            deduped.append(entry)
        return deduped

    def _app_log_file_entries(self, limit: int) -> list[dict]:
        log_path = Path(self._config.log_path)
        if not log_path.exists() or not log_path.is_file():
            return []
        try:
            lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return []
        entries: list[dict] = []
        for line in lines[-max(1, min(2000, int(limit))) :]:
            text = line.strip()
            if not text:
                continue
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                payload = {"msg": text}
            if isinstance(payload, dict):
                entries.append(payload)
        return entries

    def _collect_log_timeline(self, limit: int) -> list[dict]:
        safe_limit = self._log_cache_limit_key(limit)
        now = time.time()
        with self._log_timeline_lock():
            cached = self._state.log_timeline_cache
            cached_limit = self._state.log_timeline_cache_limit
            cached_at = self._state.log_timeline_cache_updated_at
            if (
                cached is not None
                and cached_limit >= safe_limit
                and (now - cached_at) < 1.0
            ):
                return list(cached[-safe_limit:])

            merged: list[dict] = []
            for raw in self._app_log_file_entries(safe_limit):
                entry = self._normalize_timeline_entry("", raw)
                if entry is not None:
                    merged.append(entry)
            for raw in get_recent_logs(limit=safe_limit):
                entry = self._normalize_timeline_entry("", raw)
                if entry is not None:
                    merged.append(entry)

            provider = self._state.sync_provider
            provider_sources: list[tuple[str, object]] = []
            if provider is not None:
                if hasattr(provider, "provider_for_type"):
                    try:
                        resilio_provider = provider.provider_for_type("resilio")
                    except Exception as exc:  # noqa: BLE001
                        logging.getLogger(__name__).debug(
                            "timeline_provider_lookup_failed provider=resilio error=%s",
                            exc,
                        )
                        resilio_provider = None
                    try:
                        ouisync_provider = provider.provider_for_type("ouisync")
                    except Exception as exc:  # noqa: BLE001
                        logging.getLogger(__name__).debug(
                            "timeline_provider_lookup_failed provider=ouisync error=%s",
                            exc,
                        )
                        ouisync_provider = None
                    if resilio_provider is not None:
                        provider_sources.append(("resilio", resilio_provider))
                    if ouisync_provider is not None:
                        provider_sources.append(("ouisync", ouisync_provider))
                elif hasattr(provider, "debug_logs"):
                    provider_sources.append(("resilio", provider))

            for provider_name, provider_impl in provider_sources:
                try:
                    provider_logs = provider_impl.debug_logs(limit=safe_limit)
                except Exception as exc:  # noqa: BLE001
                    logging.getLogger(__name__).debug(
                        "timeline_provider_logs_failed provider=%s error=%s",
                        provider_name,
                        exc,
                    )
                    continue
                for raw in provider_logs:
                    entry = self._normalize_timeline_entry(provider_name, raw)
                    if entry is not None:
                        merged.append(entry)

            deduped = self._dedupe_log_timeline_entries(merged)

            deduped.sort(
                key=lambda entry: (
                    self._log_entry_timestamp(entry.get("ts")),
                    self._log_entry_source_order(str(entry.get("source", ""))),
                    str(entry.get("level", "")),
                    str(entry.get("msg", "")),
                )
            )
            cached_entries = deduped[-safe_limit:]
            self._state.log_timeline_cache = list(cached_entries)
            self._state.log_timeline_cache_limit = safe_limit
            self._state.log_timeline_cache_updated_at = now
            return list(cached_entries)

    def _logs_read(self, limit: int = 200) -> dict:
        entries = self._collect_log_timeline(limit=limit)
        return {
            "entries": entries,
            "cached_at": self._state.log_timeline_cache_updated_at,
        }

    def _debug_logs_read(self, limit: int = 200) -> dict:
        provider = self._state.sync_provider
        if provider is None:
            return {"sync": [], "providers": []}
        try:
            provider_logs = provider.debug_logs(limit=limit)
            return {"sync": provider_logs, "providers": provider_logs}
        except Exception as exc:  # noqa: BLE001
            logging.getLogger(__name__).debug("debug_logs_read_failed error=%s", exc)
            return {"sync": [], "providers": []}

    def _app_shutdown_request(self) -> dict:
        logging.getLogger(__name__).warning("shutdown_requested_from_ui")
        Thread(target=self.stop, daemon=True).start()
        return {"accepted": True}

    def _app_shutdown_prepare(self) -> dict:
        with self._shutdown_update_lock():
            state = self._state.shutdown_update_state
            if state is not None and str(state.get("phase", "")).lower() in {
                "ready",
                "running",
            }:
                return dict(state)

            session_id = str(int(time.time() * 1000))
            prepared = {
                "accepted": True,
                "session_id": session_id,
                "phase": "checking",
                "update_available": False,
                "will_apply_update": False,
                "current_version": APP_VERSION,
                "target_version": "",
                "manifest_path": "",
                "payload_path": "",
                "payload_sha256": "",
                "install_mode": "noop",
                "install_target_path": "",
                "preserve_paths": [],
                "health_check_type": "none",
                "health_check_path": "",
                "updater_phase": "",
                "updater_status": "",
                "updater_detail": "",
                "rollback_performed": False,
                "updater_journal_path": "",
                "updater_result_code": "",
                "updater_exit_code": -1,
                "recovery_required": False,
                "recovery_session_id": "",
                "recovery_action": "",
                "message": "shutdown_update_check_started",
                "console_lines": ["checking update manifest..."],
            }
            self._state.shutdown_update_state = prepared

        candidate = self._resolve_shutdown_update_candidate()
        interrupted_journal = self._load_last_shutdown_update_journal()
        if self._feature_flags.is_enabled(
            "shutdown_update_recovery"
        ) and self._should_require_shutdown_update_recovery(
            interrupted_journal, candidate
        ):
            interrupted_session = str(
                interrupted_journal.get("session_id", "") or ""
            ).strip()
            interrupted_phase = str(interrupted_journal.get("phase", "") or "").strip()
            interrupted_status = str(
                interrupted_journal.get("status", "") or ""
            ).strip()
            interrupted_detail = str(
                interrupted_journal.get("detail", "") or ""
            ).strip()
            recovery_note = (
                f"interrupted update session detected: {interrupted_session} "
                f"({interrupted_phase}/{interrupted_status}/{interrupted_detail})"
            )
            self._append_shutdown_update_console_line(recovery_note)
            self._set_shutdown_update_state(
                phase="recovery_required",
                update_available=True,
                will_apply_update=True,
                recovery_required=True,
                recovery_session_id=interrupted_session,
                recovery_action="pending",
                session_id=interrupted_session,
                manifest_path=str(interrupted_journal.get("manifest_path", "") or ""),
                payload_path=str(interrupted_journal.get("payload_path", "") or ""),
                payload_sha256=str(interrupted_journal.get("payload_sha256", "") or ""),
                install_mode=str(
                    interrupted_journal.get("install_mode", "noop") or "noop"
                ),
                install_target_path=str(
                    interrupted_journal.get("install_target_path", "") or ""
                ),
                preserve_paths=self._parse_preserve_paths_csv(
                    str(interrupted_journal.get("preserve_paths_csv", "") or "")
                ),
                health_check_type=str(
                    interrupted_journal.get("health_check_type", "none") or "none"
                ),
                health_check_path=str(
                    interrupted_journal.get("health_check_path", "") or ""
                ),
                target_version=str(interrupted_journal.get("target_version", "") or ""),
                updater_phase=str(interrupted_phase).lower(),
                updater_status=str(interrupted_status).lower(),
                updater_detail=interrupted_detail,
                updater_journal_path=str(self._shutdown_update_last_journal_path()),
                message="shutdown_update_recovery_required",
            )
            current = self._state.shutdown_update_state or prepared
            return dict(current)
        if self._feature_flags.is_enabled(
            "shutdown_update_recovery"
        ) and self._is_shutdown_update_journal_interrupted(interrupted_journal):
            interrupted_session = str(
                interrupted_journal.get("session_id", "") or ""
            ).strip()
            interrupted_target = str(
                interrupted_journal.get("target_version", "") or ""
            ).strip()
            self._append_shutdown_update_console_line(
                "ignoring stale interrupted update session "
                f"{interrupted_session} (target={interrupted_target})"
            )
            self._clear_last_shutdown_update_journal()

        if not candidate["ok"]:
            self._append_shutdown_update_console_line(
                f"update check failed: {candidate['message']}"
            )
            self._set_shutdown_update_state(phase="error", message=candidate["message"])
            Thread(target=self.stop, daemon=True).start()
            current = self._state.shutdown_update_state or prepared
            return dict(current)

        if not candidate["update_available"]:
            self._append_shutdown_update_console_line(
                "no newer version found, stopping app"
            )
            self._set_shutdown_update_state(
                phase="no_update",
                message="shutdown_update_not_available",
            )
            Thread(target=self.stop, daemon=True).start()
            current = self._state.shutdown_update_state or prepared
            return dict(current)

        self._append_shutdown_update_console_line(
            f"update available: {candidate['target_version']}"
        )
        if str(candidate.get("install_target_note", "")).strip():
            self._append_shutdown_update_console_line(
                str(candidate.get("install_target_note", "")).strip()
            )
        self._set_shutdown_update_state(
            phase="ready",
            update_available=True,
            will_apply_update=True,
            target_version=candidate["target_version"],
            manifest_path=candidate["manifest_path"],
            payload_path=candidate["payload_path"],
            payload_sha256=candidate["payload_sha256"],
            install_mode=candidate.get("install_mode", "noop"),
            install_target_path=candidate.get("install_target_path", ""),
            preserve_paths=candidate.get("preserve_paths", []),
            health_check_type=candidate.get("health_check_type", "none"),
            health_check_path=candidate.get("health_check_path", ""),
            message="shutdown_update_ready",
        )
        current = self._state.shutdown_update_state or prepared
        return dict(current)

    def _app_shutdown_apply(self, session_id: str, action: str = "start") -> dict:
        action_key = str(action or "start").strip().lower()
        if action_key not in {"start", "resume", "abort"}:
            action_key = "start"
        with self._shutdown_update_lock():
            state = self._state.shutdown_update_state
            if state is None:
                return {
                    "accepted": False,
                    "phase": "idle",
                    "message": "shutdown_update_session_missing",
                    "session_id": "",
                }
            if session_id and session_id != str(state.get("session_id", "")):
                return {
                    "accepted": False,
                    "phase": str(state.get("phase", "idle")),
                    "message": "shutdown_update_session_mismatch",
                    "session_id": str(state.get("session_id", "")),
                }
            phase = str(state.get("phase", "idle")).lower()
            if phase == "running":
                return dict(state)
            if phase not in {"ready", "no_update", "error", "recovery_required"}:
                return dict(state)
            if phase in {"no_update", "error"}:
                Thread(target=self.stop, daemon=True).start()
                return dict(state)
            if phase == "recovery_required":
                if action_key == "abort":
                    recovery_session = str(
                        state.get("recovery_session_id", state.get("session_id", ""))
                    ).strip()
                    recovery_journal = (
                        self._load_shutdown_update_journal(recovery_session)
                        or self._load_last_shutdown_update_journal()
                    )
                    rollback = self._abort_shutdown_update_recovery(
                        recovery_session,
                        recovery_journal or {},
                    )
                    phase_name = "aborted" if rollback.get("ok", False) else "failed"
                    self._state.shutdown_update_state = {
                        **state,
                        "accepted": True,
                        "phase": phase_name,
                        "recovery_required": False,
                        "recovery_action": "abort",
                        "rollback_performed": bool(rollback.get("ok", False)),
                        "message": (
                            "shutdown_update_recovery_aborted"
                            if rollback.get("ok", False)
                            else "shutdown_update_recovery_abort_failed"
                        ),
                    }
                    Thread(target=self.stop, daemon=True).start()
                    return dict(self._state.shutdown_update_state)
                if action_key != "resume":
                    return {
                        **state,
                        "accepted": False,
                        "message": "shutdown_update_recovery_action_required",
                    }

            self._state.shutdown_update_state = {
                **state,
                "phase": "running",
                "recovery_required": False,
                "recovery_action": "resume" if phase == "recovery_required" else "",
                "detached_handoff_pending": (
                    self._state.platform_adapter is not None
                    and self._state.platform_adapter.platform_name().lower()
                    == "windows"
                    and self._windows_directory_swap_requires_handoff(
                        str(state.get("install_target_path", "") or "").strip()
                    )
                ),
                "frontend_auto_close_seconds": (
                    5
                    if (
                        self._state.platform_adapter is not None
                        and self._state.platform_adapter.platform_name().lower()
                        == "windows"
                        and self._windows_directory_swap_requires_handoff(
                            str(state.get("install_target_path", "") or "").strip()
                        )
                    )
                    else 0
                ),
                "message": "shutdown_update_running",
            }
            self._state.shutdown_update_thread = Thread(
                target=self._run_shutdown_update_apply, daemon=True
            )
            self._state.shutdown_update_thread.start()
            return dict(self._state.shutdown_update_state)

    def _app_shutdown_status(self, session_id: str) -> dict:
        with self._shutdown_update_lock():
            state = self._state.shutdown_update_state
            if state is None:
                return {
                    "accepted": False,
                    "phase": "idle",
                    "message": "shutdown_update_session_missing",
                    "session_id": "",
                    "console_lines": [],
                }
            if session_id and session_id != str(state.get("session_id", "")):
                return {
                    "accepted": False,
                    "phase": str(state.get("phase", "idle")),
                    "message": "shutdown_update_session_mismatch",
                    "session_id": str(state.get("session_id", "")),
                    "console_lines": state.get("console_lines", []),
                }
            return dict(state)

    def _app_shutdown_finalize(self, session_id: str) -> dict:
        with self._shutdown_update_lock():
            state = self._state.shutdown_update_state
            if state is None:
                return {
                    "accepted": False,
                    "phase": "idle",
                    "message": "shutdown_update_session_missing",
                    "session_id": "",
                }
            current_session = str(state.get("session_id", ""))
            if session_id and session_id != current_session:
                return {
                    "accepted": False,
                    "phase": str(state.get("phase", "idle")),
                    "message": "shutdown_update_session_mismatch",
                    "session_id": current_session,
                }
            phase = str(state.get("phase", "idle")).strip().lower()
            if phase in {"running", "ready", "checking"}:
                return {
                    **state,
                    "accepted": False,
                    "message": "shutdown_update_finalize_not_ready",
                }
        Thread(target=self.stop, daemon=True).start()
        with self._shutdown_update_lock():
            state = self._state.shutdown_update_state or {}
            self._state.shutdown_update_state = {
                **state,
                "accepted": True,
                "message": "shutdown_finalize_requested",
            }
            return dict(self._state.shutdown_update_state)

    def _app_update_check(self) -> dict:
        candidate = self._resolve_shutdown_update_candidate()
        if not candidate.get("ok", False):
            return {
                "ok": False,
                "update_available": False,
                "current_version": APP_VERSION,
                "target_version": str(candidate.get("target_version", "") or ""),
                "message": str(
                    candidate.get("message", "shutdown_update_check_failed")
                ),
            }
        return {
            "ok": True,
            "update_available": bool(candidate.get("update_available", False)),
            "current_version": APP_VERSION,
            "target_version": str(candidate.get("target_version", "") or ""),
            "message": str(candidate.get("message", "shutdown_update_checked")),
        }

    def _app_feature_flags_read(self) -> dict:
        return self._feature_flags.payload()

    def _shutdown_update_lock(self) -> Lock:
        if self._state.shutdown_update_lock is None:
            self._state.shutdown_update_lock = Lock()
        return self._state.shutdown_update_lock

    def _append_shutdown_update_console_line(self, line: str) -> None:
        message = str(line or "").strip()
        if not message:
            return
        logging.getLogger(__name__).info("shutdown_update_console %s", message)
        with self._shutdown_update_lock():
            if self._state.shutdown_update_state is None:
                return
            lines = list(self._state.shutdown_update_state.get("console_lines", []))
            lines.append(message)
            self._state.shutdown_update_state["console_lines"] = lines[-80:]

    def _set_shutdown_update_state(self, **changes: object) -> None:
        with self._shutdown_update_lock():
            if self._state.shutdown_update_state is None:
                return
            self._state.shutdown_update_state = {
                **self._state.shutdown_update_state,
                **changes,
            }

    def _resolve_shutdown_update_candidate(self) -> dict:
        manifest_path = self._resolve_shutdown_update_manifest_path()
        if not manifest_path.exists() or not manifest_path.is_file():
            return {
                "ok": True,
                "update_available": False,
                "target_version": "",
                "manifest_path": str(manifest_path),
                "payload_path": "",
                "payload_sha256": "",
                "message": "shutdown_update_manifest_missing",
            }

        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {
                "ok": False,
                "update_available": False,
                "target_version": "",
                "manifest_path": str(manifest_path),
                "payload_path": "",
                "payload_sha256": "",
                "message": "shutdown_update_manifest_invalid",
            }
        if not isinstance(payload, dict):
            return {
                "ok": False,
                "update_available": False,
                "target_version": "",
                "manifest_path": str(manifest_path),
                "payload_path": "",
                "payload_sha256": "",
                "message": "shutdown_update_manifest_invalid",
            }
        signature_ok, signature_message = self._verify_update_manifest_signature(
            payload
        )
        if not signature_ok:
            return {
                "ok": False,
                "update_available": False,
                "target_version": "",
                "manifest_path": str(manifest_path),
                "payload_path": "",
                "payload_sha256": "",
                "message": signature_message,
            }
        target = str(payload.get("version", "")).strip()
        if not target:
            return {
                "ok": False,
                "update_available": False,
                "target_version": "",
                "manifest_path": str(manifest_path),
                "payload_path": "",
                "payload_sha256": "",
                "message": "shutdown_update_manifest_version_missing",
            }

        package_payload = payload.get("payload")
        if not isinstance(package_payload, dict):
            return {
                "ok": False,
                "update_available": False,
                "target_version": "",
                "manifest_path": str(manifest_path),
                "payload_path": "",
                "payload_sha256": "",
                "message": "shutdown_update_manifest_payload_missing",
            }
        payload_rel_path = str(package_payload.get("path", "")).strip()
        payload_sha256 = str(package_payload.get("sha256", "")).strip().lower()
        if not payload_rel_path:
            return {
                "ok": False,
                "update_available": False,
                "target_version": "",
                "manifest_path": str(manifest_path),
                "payload_path": "",
                "payload_sha256": "",
                "message": "shutdown_update_manifest_payload_path_missing",
            }
        if len(payload_sha256) != 64 or any(
            ch not in "0123456789abcdef" for ch in payload_sha256
        ):
            return {
                "ok": False,
                "update_available": False,
                "target_version": "",
                "manifest_path": str(manifest_path),
                "payload_path": "",
                "payload_sha256": "",
                "message": "shutdown_update_manifest_payload_checksum_invalid",
            }

        payload_path = Path(payload_rel_path)
        if not payload_path.is_absolute():
            payload_path = manifest_path.parent / payload_path
        if not payload_path.exists() or not payload_path.is_file():
            return {
                "ok": False,
                "update_available": False,
                "target_version": "",
                "manifest_path": str(manifest_path),
                "payload_path": str(payload_path),
                "payload_sha256": payload_sha256,
                "message": "shutdown_update_payload_missing",
            }
        try:
            actual_sha256 = self._sha256_for_path(payload_path)
        except OSError:
            return {
                "ok": False,
                "update_available": False,
                "target_version": "",
                "manifest_path": str(manifest_path),
                "payload_path": str(payload_path),
                "payload_sha256": payload_sha256,
                "message": "shutdown_update_payload_read_failed",
            }
        if actual_sha256 != payload_sha256:
            return {
                "ok": False,
                "update_available": False,
                "target_version": "",
                "manifest_path": str(manifest_path),
                "payload_path": str(payload_path),
                "payload_sha256": payload_sha256,
                "message": "shutdown_update_payload_checksum_mismatch",
            }

        install_payload = payload.get("install")
        install_mode = "noop"
        install_target_path = ""
        preserve_paths: list[str] = ["data"]
        if isinstance(install_payload, dict):
            install_mode = str(install_payload.get("mode", "noop")).strip().lower()
            install_target_path = str(install_payload.get("target_path", "")).strip()
            raw_preserve = install_payload.get("preserve_paths", preserve_paths)
            if isinstance(raw_preserve, list):
                cleaned: list[str] = []
                for item in raw_preserve:
                    text = str(item or "").strip().replace("\\", "/")
                    if not text:
                        continue
                    if text.startswith("/") or ".." in text:
                        continue
                    cleaned.append(text)
                if cleaned:
                    preserve_paths = cleaned
        if install_mode not in {"noop", "directory_swap"}:
            return {
                "ok": False,
                "update_available": False,
                "target_version": "",
                "manifest_path": str(manifest_path),
                "payload_path": str(payload_path),
                "payload_sha256": payload_sha256,
                "message": "shutdown_update_manifest_install_mode_invalid",
            }
        if install_mode == "directory_swap" and not install_target_path:
            return {
                "ok": False,
                "update_available": False,
                "target_version": "",
                "manifest_path": str(manifest_path),
                "payload_path": str(payload_path),
                "payload_sha256": payload_sha256,
                "message": "shutdown_update_manifest_install_target_missing",
            }
        install_target_note = ""
        if install_mode == "directory_swap":
            resolved_target, target_adjusted = (
                self._resolve_install_target_path_with_info(install_target_path)
            )
            if resolved_target is None:
                return {
                    "ok": False,
                    "update_available": False,
                    "target_version": "",
                    "manifest_path": str(manifest_path),
                    "payload_path": str(payload_path),
                    "payload_sha256": payload_sha256,
                    "message": "shutdown_update_manifest_install_target_missing",
                }
            if target_adjusted:
                install_target_note = (
                    "install target app/current not found; using install root instead"
                )
            install_target_path = str(resolved_target)

        health_payload = payload.get("health_check")
        health_check_type = "none"
        health_check_path = ""
        if isinstance(health_payload, dict):
            health_check_type = str(health_payload.get("type", "none")).strip().lower()
            health_check_path = str(health_payload.get("path", "")).strip()
        if health_check_type not in {"none", "file_exists"}:
            return {
                "ok": False,
                "update_available": False,
                "target_version": "",
                "manifest_path": str(manifest_path),
                "payload_path": str(payload_path),
                "payload_sha256": payload_sha256,
                "message": "shutdown_update_manifest_health_check_invalid",
            }
        if health_check_type == "file_exists" and not health_check_path:
            return {
                "ok": False,
                "update_available": False,
                "target_version": "",
                "manifest_path": str(manifest_path),
                "payload_path": str(payload_path),
                "payload_sha256": payload_sha256,
                "message": "shutdown_update_manifest_health_check_path_missing",
            }

        return {
            "ok": True,
            "update_available": self._version_rank(target)
            > self._version_rank(APP_VERSION),
            "target_version": target,
            "manifest_path": str(manifest_path),
            "payload_path": str(payload_path),
            "payload_sha256": payload_sha256,
            "install_mode": install_mode,
            "install_target_path": install_target_path,
            "install_target_note": install_target_note,
            "preserve_paths": preserve_paths,
            "health_check_type": health_check_type,
            "health_check_path": health_check_path,
            "message": "shutdown_update_checked",
        }

    def _sha256_for_path(self, target: Path) -> str:
        digest = hashlib.sha256()
        with target.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                if not chunk:
                    break
                digest.update(chunk)
        return digest.hexdigest()

    def _shutdown_update_journal_path(self, session_id: str) -> Path:
        safe_session = str(session_id or "").strip()
        return Path.cwd() / "data" / "update" / f"session-{safe_session}.json"

    def _shutdown_update_last_journal_path(self) -> Path:
        return Path.cwd() / "data" / "update" / "last-run.json"

    def _load_shutdown_update_journal(self, session_id: str) -> dict | None:
        if not session_id:
            return None
        journal_path = self._shutdown_update_journal_path(session_id)
        try:
            if not journal_path.exists() or not journal_path.is_file():
                return None
            payload = json.loads(journal_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                return None
            return payload
        except (OSError, json.JSONDecodeError):
            return None

    def _load_last_shutdown_update_journal(self) -> dict | None:
        journal_path = self._shutdown_update_last_journal_path()
        try:
            if not journal_path.exists() or not journal_path.is_file():
                return None
            payload = json.loads(journal_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                return None
            return payload
        except (OSError, json.JSONDecodeError):
            return None

    def _clear_last_shutdown_update_journal(self) -> None:
        journal_path = self._shutdown_update_last_journal_path()
        try:
            journal_path.unlink(missing_ok=True)
        except OSError:
            return

    def _parse_preserve_paths_csv(self, preserve_paths_csv: str) -> list[str]:
        parsed: list[str] = []
        for item in str(preserve_paths_csv or "").split(","):
            normalized = str(item or "").strip()
            if (
                not normalized
                or normalized.startswith("/")
                or normalized.startswith("\\")
                or ".." in normalized
            ):
                continue
            parsed.append(normalized)
        return parsed

    def _is_shutdown_update_journal_interrupted(self, journal: dict | None) -> bool:
        if not isinstance(journal, dict):
            return False
        if not str(journal.get("session_id", "") or "").strip():
            return False
        if (
            str(journal.get("install_mode", "") or "").strip().lower()
            != "directory_swap"
        ):
            return False
        phase = str(journal.get("phase", "") or "").strip().lower()
        status = str(journal.get("status", "") or "").strip().lower()
        if not phase:
            return False
        # Early phases are safe to restart and should not block shutdown with recovery mode.
        if phase in {"lock", "verify", "stage"}:
            return False
        # `apply/ok` and completed rollback are terminal, everything else is resumable/abortable.
        if phase == "apply" and status == "ok":
            return False
        if phase == "rollback" and status == "ok":
            return False
        return True

    def _should_require_shutdown_update_recovery(
        self, journal: dict | None, candidate: dict
    ) -> bool:
        if not self._is_shutdown_update_journal_interrupted(journal):
            return False
        assert journal is not None
        interrupted_target = str(journal.get("target_version", "") or "").strip()
        if not interrupted_target:
            return False
        interrupted_rank = self._version_rank(interrupted_target)
        if interrupted_rank <= self._version_rank(APP_VERSION):
            # Never offer recovery that would replay an older or equal version.
            return False
        if bool(candidate.get("ok", False)) and bool(
            candidate.get("update_available", False)
        ):
            candidate_target = str(candidate.get("target_version", "") or "").strip()
            if (
                candidate_target
                and self._version_rank(candidate_target) > interrupted_rank
            ):
                # Prefer the latest valid manifest update over stale interrupted recovery.
                return False
        return True

    def _abort_shutdown_update_recovery(
        self, session_id: str, journal: dict
    ) -> dict[str, object]:
        install_mode = str(journal.get("install_mode", "") or "").strip().lower()
        install_target_path = str(journal.get("install_target_path", "") or "").strip()
        if install_mode != "directory_swap" or not install_target_path:
            return {
                "ok": False,
                "message": "shutdown_update_recovery_abort_unavailable",
            }
        target_path = self._resolve_install_target_path(install_target_path)
        if target_path is None:
            return {
                "ok": False,
                "message": "shutdown_update_recovery_abort_unavailable",
            }

        backup_candidates = [
            Path.cwd() / "data" / "update" / "backup" / session_id / "current",
            target_path.parent / ".llng-update-backup" / session_id / "current",
            target_path / "data" / "update" / "backup" / session_id / "current",
        ]
        backup_current: Path | None = None
        for candidate in backup_candidates:
            if candidate.exists() and candidate.is_dir():
                backup_current = candidate
                break
        if backup_current is None:
            return {
                "ok": False,
                "message": "shutdown_update_recovery_abort_unavailable",
            }

        replaced_path = (
            backup_current.parent
            / f"aborted-current-{int(time.time())}-{uuid.uuid4().hex[:8]}"
        )
        try:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            if target_path.exists():
                shutil.move(str(target_path), str(replaced_path))
            shutil.move(str(backup_current), str(target_path))
        except OSError as exc:
            return {
                "ok": False,
                "message": "shutdown_update_recovery_abort_failed",
                "detail": str(exc),
            }
        return {
            "ok": True,
            "message": "shutdown_update_recovery_aborted",
            "target_path": str(target_path),
        }

    def _map_updater_result_code(
        self, phase: str, status: str, detail: str, rollback_performed: bool
    ) -> str:
        phase_key = str(phase or "").strip().lower()
        status_key = str(status or "").strip().lower()
        detail_key = str(detail or "").strip().lower()
        if rollback_performed:
            if status_key == "ok":
                return "rolled_back"
            return "rollback_failed"
        if phase_key == "health" and status_key == "failed":
            return "health_failed"
        if phase_key == "swap" and status_key == "planned":
            if detail_key == "swap_guard_disabled":
                return "swap_guard_disabled"
            return "swap_planned"
        if phase_key == "elevate" and status_key == "failed":
            return "elevation_failed"
        if status_key == "ok":
            return "ok"
        if status_key == "failed":
            return "failed"
        return "unknown"

    def _fallback_updater_result_code(self, exit_code: int, platform_name: str) -> str:
        if exit_code == 0:
            return "ok"
        if platform_name == "linux" and exit_code == 12:
            # Linux updater uses 12 when elevation is required but denied/unavailable.
            return "elevation_failed"
        return "failed"

    def _verify_update_manifest_signature(self, payload: dict) -> tuple[bool, str]:
        signature = payload.get("signature")
        if not isinstance(signature, dict):
            return False, "shutdown_update_manifest_signature_missing"
        key_id = str(signature.get("key_id", "")).strip()
        signature_value = str(signature.get("value", "")).strip()
        if not key_id or not signature_value:
            return False, "shutdown_update_manifest_signature_missing"
        key_pair = UPDATE_MANIFEST_PUBLIC_KEYS.get(key_id)
        if key_pair is None:
            return False, "shutdown_update_manifest_signature_key_unknown"
        try:
            signature_bytes = base64.b64decode(signature_value, validate=True)
        except ValueError:
            return False, "shutdown_update_manifest_signature_invalid"
        signed_bytes = self._canonical_manifest_bytes(payload)
        if not self._verify_rsa_sha256_signature(
            signed_bytes=signed_bytes,
            signature=signature_bytes,
            modulus=key_pair[0],
            exponent=key_pair[1],
        ):
            return False, "shutdown_update_manifest_signature_invalid"
        return True, "shutdown_update_manifest_signature_valid"

    def _canonical_manifest_bytes(self, payload: dict) -> bytes:
        # Signature covers the manifest except the signature object itself.
        unsigned_payload = {
            key: value for key, value in payload.items() if key != "signature"
        }
        return json.dumps(
            unsigned_payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")

    def _verify_rsa_sha256_signature(
        self, signed_bytes: bytes, signature: bytes, modulus: int, exponent: int
    ) -> bool:
        key_size = (modulus.bit_length() + 7) // 8
        if len(signature) != key_size:
            return False
        digest = hashlib.sha256(signed_bytes).digest()
        digest_info = _SHA256_DIGEST_INFO_PREFIX + digest
        padding_size = key_size - len(digest_info) - 3
        if padding_size < 8:
            return False
        expected = b"\x00\x01" + (b"\xff" * padding_size) + b"\x00" + digest_info
        signature_value = int.from_bytes(signature, byteorder="big")
        decoded = pow(signature_value, exponent, modulus).to_bytes(
            key_size, byteorder="big"
        )
        return decoded == expected

    def _resolve_shutdown_update_manifest_path(self) -> Path:
        configured = Path(self._config.update_manifest_path)
        if configured.is_absolute():
            return configured
        return Path(self._effective_library_path()) / configured

    def _resolve_shutdown_updater_script_path(self) -> Path:
        platform_name = ""
        if self._state.platform_adapter is not None:
            platform_name = self._state.platform_adapter.platform_name().lower()
        script_raw = (
            self._config.windows_updater_script_path
            if platform_name == "windows"
            else self._config.linux_updater_script_path
        )
        candidate = Path(script_raw)
        if candidate.is_absolute():
            return candidate
        return Path.cwd() / candidate

    def _windows_directory_swap_requires_handoff(
        self, install_target_path: str
    ) -> bool:
        target_path = self._resolve_install_target_path(install_target_path)
        if target_path is None:
            return False
        runtime_root = Path.cwd().resolve(strict=False)
        target_root = target_path.resolve(strict=False)
        try:
            runtime_root.relative_to(target_root)
            return True
        except ValueError:
            return False

    def _stage_windows_updater_script(self, script_path: Path, session_id: str) -> Path:
        staged_root = (
            Path(tempfile.gettempdir())
            / "llng-updater-runtime"
            / str(session_id).strip()
        )
        staged_root.mkdir(parents=True, exist_ok=True)
        staged_script = staged_root / script_path.name
        shutil.copy2(script_path, staged_script)
        return staged_script

    def _run_shutdown_update_apply(self) -> None:
        logger = logging.getLogger(__name__)
        state = self._state.shutdown_update_state or {}
        session_id = str(state.get("session_id", "") or "").strip()
        manifest_path = str(state.get("manifest_path", "") or "").strip()
        payload_path = str(state.get("payload_path", "") or "").strip()
        payload_sha256 = str(state.get("payload_sha256", "") or "").strip()
        install_mode = str(state.get("install_mode", "noop") or "noop").strip().lower()
        install_target_path = str(state.get("install_target_path", "") or "").strip()
        preserve_paths = state.get("preserve_paths", ["data"])
        if not isinstance(preserve_paths, list):
            preserve_paths = ["data"]
        preserve_csv = ",".join(
            str(item or "").strip()
            for item in preserve_paths
            if str(item or "").strip()
        )
        health_check_type = (
            str(state.get("health_check_type", "none") or "none").strip().lower()
        )
        health_check_path = str(state.get("health_check_path", "") or "").strip()
        target_version = str(state.get("target_version", "") or "").strip()
        script_path = self._resolve_shutdown_updater_script_path()
        if not script_path.exists():
            self._append_shutdown_update_console_line(
                f"updater script missing: {script_path}"
            )
            self._set_shutdown_update_state(
                phase="failed",
                updater_result_code="launch_failed",
                updater_exit_code=-2,
                message="shutdown_updater_script_missing",
            )
            return

        provider = self._state.sync_provider
        if provider is not None:
            self._append_shutdown_update_console_line(
                "stopping sync service before update..."
            )
            # Prevent watchdog relaunch while updater needs exclusive file access.
            self._state.sync_watchdog_paused = True
            self._state.desired_sync_running = False
            try:
                provider.stop()
            except Exception as exc:  # noqa: BLE001
                self._append_shutdown_update_console_line(f"sync stop warning: {exc}")
            # Give file handles a short grace period to close.
            time.sleep(0.5)

        self._append_shutdown_update_console_line(
            f"launching updater: {script_path.name}"
        )
        platform_name = ""
        if self._state.platform_adapter is not None:
            platform_name = self._state.platform_adapter.platform_name().lower()
        detached_windows_swap = False
        if platform_name == "windows":
            if install_mode == "directory_swap":
                detached_windows_swap = self._windows_directory_swap_requires_handoff(
                    install_target_path
                )
                if detached_windows_swap:
                    script_path = self._stage_windows_updater_script(
                        script_path, session_id
                    )
            command = [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script_path),
                "-ManifestPath",
                manifest_path,
                "-CurrentVersion",
                APP_VERSION,
                "-TargetVersion",
                target_version,
                "-SessionId",
                session_id,
                "-PayloadPath",
                payload_path,
                "-PayloadSha256",
                payload_sha256,
                "-InstallMode",
                install_mode,
                "-InstallTargetPath",
                install_target_path,
                "-PreservePathsCsv",
                preserve_csv,
                "-HealthCheckType",
                health_check_type,
                "-HealthCheckPath",
                health_check_path,
                "-RepoRoot",
                str(Path.cwd()),
            ]
            if detached_windows_swap:
                command.extend(["-ParentProcessId", str(os.getpid())])
        else:
            command = [
                "sh",
                str(script_path),
                "--manifest-path",
                manifest_path,
                "--current-version",
                APP_VERSION,
                "--target-version",
                target_version,
                "--session-id",
                session_id,
                "--payload-path",
                payload_path,
                "--payload-sha256",
                payload_sha256,
                "--install-mode",
                install_mode,
                "--install-target-path",
                install_target_path,
                "--preserve-paths-csv",
                preserve_csv,
                "--health-check-type",
                health_check_type,
                "--health-check-path",
                health_check_path,
                "--repo-root",
                str(Path.cwd()),
            ]

        try:
            if detached_windows_swap:
                # Windows cannot rename the install root while this process is
                # still running from inside it, so hand off to an external copy.
                subprocess.Popen(  # noqa: S603 updater wrapper path is controlled by local config
                    command,
                    cwd=str(script_path.parent),
                    creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
                )
                self._append_shutdown_update_console_line(
                    "detached updater launched; stopping app for Windows file swap"
                )
                self._set_shutdown_update_state(
                    phase="handoff",
                    detached_handoff_pending=True,
                    frontend_auto_close_seconds=5,
                    message="shutdown_update_handoff_started",
                )
                Thread(target=self.stop, daemon=True).start()
                return
            process = subprocess.Popen(  # noqa: S603 updater wrapper path is controlled by local config
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            if process.stdout is not None:
                for line in process.stdout:
                    self._append_shutdown_update_console_line(line.rstrip())
            # System-wide update may need user-confirmed privilege elevation.
            exit_code = process.wait(timeout=600)
            journal = self._load_shutdown_update_journal(session_id)
            rollback_performed = False
            updater_phase = ""
            updater_status = ""
            updater_detail = ""
            if journal is not None:
                updater_phase = str(journal.get("phase", "") or "").strip().lower()
                updater_status = str(journal.get("status", "") or "").strip().lower()
                updater_detail = str(journal.get("detail", "") or "").strip()
                rollback_performed = (
                    updater_phase == "rollback" or "rollback" in updater_detail.lower()
                )
                self._set_shutdown_update_state(
                    updater_phase=updater_phase,
                    updater_status=updater_status,
                    updater_detail=updater_detail,
                    rollback_performed=rollback_performed,
                    updater_journal_path=str(
                        self._shutdown_update_journal_path(session_id)
                    ),
                )
            if journal is not None:
                updater_result_code = self._map_updater_result_code(
                    updater_phase,
                    updater_status,
                    updater_detail,
                    rollback_performed,
                )
            else:
                updater_result_code = self._fallback_updater_result_code(
                    exit_code, platform_name
                )
            if exit_code == 0:
                self._append_shutdown_update_console_line("update apply finished")
                self._set_shutdown_update_state(
                    phase="done",
                    updater_result_code=updater_result_code,
                    updater_exit_code=exit_code,
                    message="shutdown_update_apply_done_wait_finalize",
                )
            else:
                self._append_shutdown_update_console_line(
                    f"updater exited with code {exit_code}"
                )
                self._set_shutdown_update_state(
                    phase="failed",
                    updater_result_code=updater_result_code,
                    updater_exit_code=exit_code,
                    message=(
                        "shutdown_update_apply_failed_rolled_back"
                        if rollback_performed
                        else "shutdown_update_apply_failed"
                    ),
                )
        except subprocess.TimeoutExpired:
            self._append_shutdown_update_console_line("updater timed out")
            self._set_shutdown_update_state(
                phase="failed",
                updater_result_code="timeout",
                updater_exit_code=-3,
                message="shutdown_update_apply_timeout",
            )
        except OSError as exc:
            logger.warning("shutdown_update_apply_failed: %s", exc)
            self._append_shutdown_update_console_line(f"updater start failed: {exc}")
            self._set_shutdown_update_state(
                phase="failed",
                updater_result_code="launch_failed",
                updater_exit_code=-4,
                message="shutdown_update_apply_failed",
            )

    def _resolve_install_target_path_with_info(
        self, install_target_path: str
    ) -> tuple[Path | None, bool]:
        raw_path = str(install_target_path or "").strip()
        if not raw_path:
            return None, False
        candidate = Path(raw_path)
        if not candidate.is_absolute():
            candidate = Path.cwd() / candidate
        resolved = candidate.resolve(strict=False)
        anchor = str(resolved.anchor or "").rstrip("\\/")
        normalized = str(resolved).rstrip("\\/")
        if not normalized or normalized == anchor:
            return None, False

        normalized_raw = raw_path.replace("\\", "/").strip("/").lower()
        if (
            normalized_raw == "app/current"
            and not resolved.exists()
            and (Path.cwd() / "run.bat").exists()
            and (Path.cwd() / "app").exists()
        ):
            # Compatibility fallback for packaged layout where runtime root is the install
            # directory and not app/current yet.
            return Path.cwd().resolve(strict=False), True
        return resolved, False

    def _resolve_install_target_path(self, install_target_path: str) -> Path | None:
        resolved, _ = self._resolve_install_target_path_with_info(install_target_path)
        return resolved

    def _app_update_rollback(self) -> dict:
        backup_root = Path.cwd() / "data" / "update" / "backup"
        if not backup_root.exists() or not backup_root.is_dir():
            return {
                "ok": False,
                "message": "update_rollback_backup_missing",
                "session_id": "",
                "target_path": "",
            }

        candidates = sorted(
            [entry for entry in backup_root.iterdir() if entry.is_dir()],
            key=lambda entry: entry.stat().st_mtime,
            reverse=True,
        )
        for session_dir in candidates:
            backup_current = session_dir / "current"
            if not backup_current.exists() or not backup_current.is_dir():
                continue
            session_id = str(session_dir.name)
            journal = self._load_shutdown_update_journal(session_id) or {}
            install_mode = str(journal.get("install_mode", "") or "").strip().lower()
            install_target_path = str(
                journal.get("install_target_path", "") or ""
            ).strip()
            if install_mode != "directory_swap":
                continue
            target_path = self._resolve_install_target_path(install_target_path)
            if target_path is None:
                continue
            replaced_path = session_dir / "replaced-current"
            try:
                target_path.parent.mkdir(parents=True, exist_ok=True)
                if replaced_path.exists():
                    shutil.rmtree(replaced_path, ignore_errors=True)
                if target_path.exists():
                    shutil.move(str(target_path), str(replaced_path))
                shutil.move(str(backup_current), str(target_path))
            except OSError as exc:
                return {
                    "ok": False,
                    "message": "update_rollback_apply_failed",
                    "session_id": session_id,
                    "target_path": str(target_path),
                    "detail": str(exc),
                }
            return {
                "ok": True,
                "message": "update_rollback_applied",
                "session_id": session_id,
                "target_path": str(target_path),
            }

        return {
            "ok": False,
            "message": "update_rollback_not_available",
            "session_id": "",
            "target_path": "",
        }

    def _tail_sync_log_lines(self, limit: int = 200) -> list[dict]:
        log_path = Path(self._config.sync_log_path)
        if not log_path.exists():
            return []
        try:
            lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return []
        tail = lines[-max(1, min(1000, limit)) :]
        return [{"msg": line} for line in tail]

    def _run_sync_watchdog(self) -> None:
        logger = logging.getLogger(__name__)
        while True:
            if (
                self._state.sync_watchdog_stop is not None
                and self._state.sync_watchdog_stop.is_set()
            ):
                return
            try:
                self._refresh_lan_discovery()
                self._try_import_lan_settings()
                self._try_import_lan_catalog()
            except (OSError, ValueError, sqlite3.Error) as exc:
                logger.warning("lan_catalog_import_failed error=%s", exc)
            provider = self._state.sync_provider
            if (
                provider is not None
                and self._state.desired_sync_running
                and not self._state.sync_watchdog_paused
                and self._state.user_settings is not None
            ):
                library_ready = bool(
                    self._state.user_settings.library_path_initialized
                )
                try:
                    if self._run_sync_watchdog_provider_cycle(
                        provider,
                        logger,
                        allow_resilio=library_ready,
                        run_game_tasks=library_ready,
                    ):
                        time.sleep(2.0)
                        continue
                    if not library_ready:
                        time.sleep(2.0)
                        continue
                    status = provider.status()
                    if str(status.state or "").strip().lower() in {
                        "blocked",
                        "starting",
                        "stopping",
                    }:
                        time.sleep(2.0)
                        continue
                    now = time.monotonic()
                    if (
                        self._state.sync_watchdog_last_restart_at > 0
                        and now - self._state.sync_watchdog_last_restart_at < 20.0
                    ):
                        time.sleep(2.0)
                        continue
                    if not status.running:
                        self._persist_resilio_library_path(
                            self._effective_library_path()
                        )
                        logger.warning("sync_watchdog_restart_triggered")
                        self._state.sync_watchdog_last_restart_at = now
                        try:
                            restart_status = provider.start()
                        except Exception as exc:  # noqa: BLE001
                            logger.warning("sync_watchdog_error: %s", exc)
                            continue
                        if restart_status.running:
                            self._state.sync_watchdog_last_restart_at = 0.0
                        elif restart_status.last_error:
                            logger.warning(
                                "sync_watchdog_restart_failed provider=%s state=%s pid=%s last_error=%s",
                                restart_status.provider,
                                restart_status.state,
                                restart_status.pid,
                                restart_status.last_error,
                            )
                    if status.running:
                        self._ouisync_manage_lan_cycle()
                        self._run_auto_install_watchdog_cycle()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("sync_watchdog_error: %s", exc)
            time.sleep(2.0)

    def _run_sync_watchdog_provider_cycle(
        self,
        provider: object,
        logger: logging.Logger,
        *,
        allow_resilio: bool = True,
        run_game_tasks: bool = True,
    ) -> bool:
        provider_for_type = getattr(provider, "provider_for_type", None)
        status_for_type = getattr(provider, "status_for_type", None)
        if not callable(provider_for_type):
            return False

        any_running = False
        any_started = False
        now = time.monotonic()
        provider_types = ("resilio", "ouisync") if allow_resilio else ("ouisync",)
        for provider_type in provider_types:
            try:
                selected = provider_for_type(provider_type)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "sync_watchdog_provider_lookup_failed provider=%s error=%s",
                    provider_type,
                    exc,
                )
                continue
            try:
                status = (
                    status_for_type(provider_type)
                    if callable(status_for_type)
                    else selected.status()
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "sync_watchdog_provider_status_failed provider=%s error=%s",
                    provider_type,
                    exc,
                )
                continue
            state = str(status.state or "").strip().lower()
            if status.running:
                any_running = True
                if provider_type == "ouisync" and run_game_tasks:
                    self._reconcile_ng_provider_repository()
                continue
            if state in {"blocked", "starting", "stopping"}:
                continue
            if (
                self._state.sync_watchdog_last_restart_at > 0
                and now - self._state.sync_watchdog_last_restart_at < 20.0
            ):
                continue

            if provider_type == "resilio":
                self._persist_resilio_library_path(self._effective_library_path())
            logger.warning(
                "sync_watchdog_provider_restart_triggered provider=%s", provider_type
            )
            self._state.sync_watchdog_last_restart_at = now
            try:
                recover = getattr(selected, "recover_if_unhealthy", None)
                if provider_type == "resilio" and state == "failed" and callable(recover):
                    restart_status = recover()
                else:
                    restart_status = selected.start()
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "sync_watchdog_provider_error provider=%s error=%s",
                    provider_type,
                    exc,
                )
                continue
            any_started = True
            if restart_status.running:
                any_running = True
                self._state.sync_watchdog_last_restart_at = 0.0
                if run_game_tasks and provider_type in {"resilio", "ouisync"}:
                    self._apply_all_extra_sync_items()
            elif restart_status.last_error:
                logger.warning(
                    "sync_watchdog_provider_restart_failed provider=%s state=%s pid=%s last_error=%s",
                    provider_type,
                    restart_status.state,
                    restart_status.pid,
                    restart_status.last_error,
                )

        if any_running and run_game_tasks:
            self._ouisync_manage_lan_cycle()
            self._run_auto_install_watchdog_cycle()
        return True if any_started or any_running else False

    def _installed_version_after_auto_install(
        self, game_id: str, fallback_version: str
    ) -> str:
        manager = self._state.game_manager
        if manager is None:
            return str(fallback_version or "")
        try:
            status = manager.check_status(game_id)
        except Exception:  # noqa: BLE001
            return str(fallback_version or "")
        installed_version = str(
            status.details.get("installed_version", "") or ""
        ).strip()
        if installed_version:
            return installed_version
        return str(fallback_version or "")

    def _append_install_console_line(self, game_id: str, line: str) -> None:
        safe_game_id = str(game_id or "").strip()
        text = str(line or "").strip()
        if not safe_game_id or not text:
            return
        if self._state.install_console_lock is None:
            self._state.install_console_lock = Lock()
        if self._state.install_console_lines is None:
            self._state.install_console_lines = {}
        with self._state.install_console_lock:
            rows = self._state.install_console_lines.setdefault(safe_game_id, [])
            rows.append(text)
            # Keep only the latest lines to prevent unbounded memory growth.
            if len(rows) > 400:
                del rows[: len(rows) - 400]

    def _append_install_console_line_once(self, game_id: str, line: str) -> None:
        safe_game_id = str(game_id or "").strip()
        text = str(line or "").strip()
        if not safe_game_id or not text:
            return
        last_line = ""
        if (
            self._state.install_console_lock is not None
            and self._state.install_console_lines is not None
        ):
            with self._state.install_console_lock:
                rows = self._state.install_console_lines.get(safe_game_id, [])
                last_line = str(rows[-1]) if rows else ""
        if last_line == text:
            return
        self._append_install_console_line(safe_game_id, text)

    def _install_console_snapshot(self, game_id: str) -> list[str]:
        safe_game_id = str(game_id or "").strip()
        if not safe_game_id:
            return []
        if (
            self._state.install_console_lock is None
            or self._state.install_console_lines is None
        ):
            return []
        with self._state.install_console_lock:
            return list(self._state.install_console_lines.get(safe_game_id, []))

    @staticmethod
    def _format_auto_install_failure_reason(details: object) -> str:
        if not isinstance(details, dict) or not details:
            return ""
        fields = (
            "error",
            "code",
            "script",
            "task",
            "runtime",
            "wrapper",
            "archive",
            "target",
            "unrar",
        )
        parts: list[str] = []
        for key in fields:
            value = details.get(key)
            text = str(value).strip() if value is not None else ""
            if text:
                parts.append(f"{key}={text}")
        if parts:
            return " ".join(parts)
        # Fallback for unknown error payload shapes: include a compact scalar slice.
        for key, value in details.items():
            if isinstance(value, (str, int, float, bool)):
                text = str(value).strip()
                if not text:
                    continue
                parts.append(f"{key}={text}")
            if len(parts) >= 4:
                break
        return " ".join(parts)

    def _run_auto_install_watchdog_cycle(self) -> None:
        repo = self._state.repository
        manager = self._state.game_manager
        provider = self._state.sync_provider
        if repo is None or manager is None or provider is None:
            return

        failed_archive_signatures = self._state.install_failed_archive_signatures
        if failed_archive_signatures is None:
            failed_archive_signatures = {}
            self._state.install_failed_archive_signatures = failed_archive_signatures
        base = Path(self._effective_library_path())
        logger = logging.getLogger(__name__)

        for target in repo.list_sync_targets():
            game_id = str(target.get("id", "") or "").strip()
            if not game_id:
                continue
            if self._is_game_disabled(game_id):
                continue
            game = repo.get_game(game_id, locale="en")
            if game is None:
                continue

            installed = str(game.get("install_state", "")).lower() == "installed"
            needs_update = bool(game.get("needs_update", False))
            provider_type = (
                str(game.get("game_provider_type", "") or "").strip().lower()
            )
            is_ouisync = provider_type == "ouisync"
            folder = base / game_id
            local_folder = folder / "local"
            local_folder_ready = local_folder.exists() and local_folder.is_dir()
            if installed and not needs_update and local_folder_ready:
                continue

            archive_file = None
            if is_ouisync:
                access = self._ouisync_game_access(game_id)
                archive_signature = (
                    str(access.expected_info_hash).lower() if access else None
                )
            else:
                archive_path = getattr(manager, "archive_path", None)
                archive_file = (
                    Path(archive_path(game_id))
                    if callable(archive_path)
                    else folder / f"{game_id}.eti"
                )
                archive_signature = self._runtime_update_db_signature_for_path(
                    archive_file
                )
            blocked_signature = failed_archive_signatures.get(game_id)
            if blocked_signature is not None:
                if (
                    archive_signature is not None
                    and blocked_signature == archive_signature
                ):
                    # Never auto-retry the same failed archive payload; otherwise the
                    # watchdog can loop forever on broken game_setup/unrar runs.
                    continue
                # Archive payload changed (or disappeared), so clear previous failure lock.
                failed_archive_signatures.pop(game_id, None)
            if not is_ouisync and (
                archive_file is None
                or not archive_file.exists()
                or not archive_file.is_file()
            ):
                continue

            if is_ouisync:
                if not self._ouisync_download_ready(game_id, game, base / game_id):
                    continue
            else:
                sync_status = self._folder_sync_status(
                    folder, float(game.get("size_gb", 0) or 0)
                )
                if not bool(sync_status.get("active", False)):
                    continue
                progress_percent = int(sync_status.get("progress_percent", 0) or 0)
            if not is_ouisync and progress_percent < 100:
                if not installed:
                    repo.set_install_state(
                        game_id,
                        "downloading",
                        str(game.get("installed_version", "") or ""),
                    )
                self._append_install_console_line(
                    game_id,
                    f"downloading archive: {progress_percent}%",
                )
                continue
            if (
                self._state.user_settings is not None
                and self._state.user_settings.sync_only_mode
            ):
                self._append_install_console_line_once(
                    game_id,
                    "sync-only mode enabled, skipping archive extraction",
                )
                if not installed:
                    repo.set_install_state(game_id, "missing", "")
                continue
            if installed and not needs_update and not local_folder_ready:
                # Only emit recovery warning once archive sync has actually completed.
                logger.warning(
                    "auto_install_local_missing_retry game_id=%s local_folder=%s",
                    game_id,
                    local_folder,
                )

            self._append_install_console_line(
                game_id, "download completed (100%), starting extraction"
            )
            previous_state = str(game.get("install_state", "") or "missing").lower()
            previous_version = str(game.get("installed_version", "") or "")
            repo.set_install_state(game_id, "installing", previous_version)
            if installed and needs_update:
                self._append_install_console_line(game_id, "running update extraction")
                action = "update"
            else:
                self._append_install_console_line(game_id, "running install extraction")
                action = "install"
            if is_ouisync:
                result_payload = self._game_action(game_id, action)
                result = GameActionResult(
                    bool(result_payload.get("ok")),
                    action,
                    game_id,
                    str(result_payload.get("message", "")),
                    result_payload.get("details", {})
                    if isinstance(result_payload.get("details"), dict)
                    else {},
                )
            elif action == "update":
                result = manager.update(
                    game_id,
                    output_callback=lambda line, gid=game_id: (
                        self._append_install_console_line(gid, line)
                    ),
                )
            else:
                result = manager.install(
                    game_id,
                    output_callback=lambda line, gid=game_id: (
                        self._append_install_console_line(gid, line)
                    ),
                )

            if not result.ok and result.message == OUISYNC_INSTALL_INTERRUPTED:
                self._append_install_console_line(
                    game_id, f"{action} interrupted, resuming after restart"
                )
                repo.set_install_state(
                    game_id,
                    "installed" if previous_state == "installed" else "downloading",
                    previous_version if previous_state == "installed" else "",
                )
                logger.info(
                    "auto_install_watchdog_interrupted game_id=%s action=%s",
                    game_id,
                    action,
                )
                continue
            if not result.ok:
                self._append_install_console_line(
                    game_id,
                    f"{action} failed: {result.message}",
                )
                for line in (
                    result.details.get("console_lines", [])
                    if isinstance(result.details, dict)
                    else []
                ):
                    self._append_install_console_line(game_id, str(line))
                rollback_state = (
                    "installed" if previous_state == "installed" else "missing"
                )
                rollback_version = (
                    previous_version if rollback_state == "installed" else ""
                )
                repo.set_install_state(game_id, rollback_state, rollback_version)
                if archive_signature is not None:
                    failed_archive_signatures[game_id] = archive_signature
                reason = self._format_auto_install_failure_reason(result.details)
                logger.warning(
                    "auto_install_watchdog_failed game_id=%s action=%s message=%s reason=%s",
                    game_id,
                    action,
                    result.message,
                    reason or "-",
                )
                continue

            installed_version = self._installed_version_after_auto_install(
                game_id,
                str(game.get("version", "") or ""),
            )
            repo.set_install_state(game_id, "installed", installed_version)
            failed_archive_signatures.pop(game_id, None)
            self._append_install_console_line(
                game_id,
                f"{action} completed, installed version: {installed_version or '-'}",
            )
            logger.info(
                "auto_install_watchdog_completed game_id=%s action=%s installed_version=%s",
                game_id,
                action,
                installed_version,
            )

    def _ouisync_download_ready(self, game_id: str, game: dict, folder: Path) -> bool:
        """Return True once a requested Ouisync download has a complete snapshot.

        Ouisync reports 0/0 blocks before the first index arrives, and it reopens
        every repository paused after a restart. Neither block counts nor the sync
        flag therefore tell whether a download is finished or still wanted. The
        persisted install state carries the download intent; the materialization
        job (including the stalled-counter read verification) signals completion.
        """
        install_state = str(game.get("install_state", "") or "missing").lower()
        installed = install_state == "installed"
        resumable = install_state in {"downloading", "installing"}
        if not (resumable or (installed and bool(game.get("needs_update", False)))):
            return False
        provider = self._sync_provider_for_game(game_id)
        status_reader = getattr(provider, "game_materialization_status", None)
        starter = getattr(provider, "start_game_materialization", None)
        if not callable(status_reader):
            return False
        status = status_reader(game_id)
        phase = str(status.get("phase", "idle")) if isinstance(status, dict) else "idle"
        if phase == "complete":
            self._ouisync_download_resume.pop(game_id, None)
            return True
        if phase in {"queued", "syncing"}:
            if not installed and install_state != "downloading":
                self._state.repository.set_install_state(game_id, "downloading", "")
            self._append_install_console_line_once(
                game_id,
                f"downloading archive: {int(status.get('progress_percent', 0) or 0)}%",
            )
            return False
        # The job is idle after a restart, or it was cancelled or failed while the
        # download is still wanted: start it again, with bounded backoff.
        if not resumable or not callable(starter):
            return False
        now = time.monotonic()
        next_attempt, delay = self._ouisync_download_resume.get(
            game_id, (0.0, OUISYNC_DOWNLOAD_RESUME_RETRY_SECONDS / 2)
        )
        if now < next_attempt:
            return False
        delay = min(OUISYNC_DOWNLOAD_RESUME_RETRY_MAX_SECONDS, delay * 2)
        self._ouisync_download_resume[game_id] = (now + delay, delay)
        access = self._ouisync_game_access(game_id)
        if access is None:
            return False
        try:
            repository_path = self._ouisync_game_repository_path(game_id)
            folder.mkdir(parents=True, exist_ok=True)
        except (OSError, ValueError):
            return False
        ok, detail = starter(access, str(folder), str(repository_path))
        if ok and install_state != "downloading":
            self._state.repository.set_install_state(game_id, "downloading", "")
        logging.getLogger(__name__).info(
            "ouisync_download_resumed game_id=%s phase=%s ok=%s detail=%s",
            game_id,
            phase,
            bool(ok),
            detail,
        )
        return False

    def _persist_resilio_library_path(self, library_path: str) -> bool:
        if self._config.sync_provider.lower() != "resilio":
            # Ouisync uses per-repository paths and does not use the Resilio config file.
            return True
        try:
            persist_resilio_runtime_paths(
                Path(self._config.sync_config_path), self._runtime_root_path()
            )
            return True
        except OSError as exc:
            logging.getLogger(__name__).warning("sync_config_update_failed: %s", exc)
            return False
        except ValueError as exc:
            logging.getLogger(__name__).warning("sync_config_parse_failed: %s", exc)
            return False

    def _runtime_root_path(self) -> Path:
        repo_root_raw = str(self._config.repo_root or "").strip()
        module_runtime_root = Path(__file__).resolve().parents[4]
        if repo_root_raw and repo_root_raw not in {".", "./"}:
            repo_root = Path(repo_root_raw).expanduser()
            if not repo_root.is_absolute():
                repo_root = (module_runtime_root / repo_root).resolve(strict=False)
            return repo_root.resolve(strict=False)

        sync_config_path = Path(self._config.sync_config_path).expanduser()
        if sync_config_path.is_absolute():
            # Expected packaged layout: <root>/config/resilio/config.json
            if (
                sync_config_path.name.lower() == "config.json"
                and sync_config_path.parent.name.lower() == "resilio"
                and sync_config_path.parent.parent.name.lower() == "config"
            ):
                return sync_config_path.parent.parent.parent.resolve(strict=False)
            return sync_config_path.parent.resolve(strict=False)

        return module_runtime_root

    def _metadata_root_path(self) -> Path:
        # Keep metadata files in app runtime root to support bundled metadata overrides.
        return self._runtime_root_path() / "metadata"

    def _parse_json_with_comments(self, raw: str) -> dict:
        return parse_json_with_comments(raw)

    def _resolve_legacy_db_path(self) -> str:
        configured = Path(self._config.legacy_db_path)
        if configured.exists():
            return str(configured)
        dev_fallback = Path("old/game.db")
        if dev_fallback.exists():
            return str(dev_fallback)
        return str(configured)

    def _resolve_runtime_update_db_path(self) -> Path:
        return (
            Path(self._effective_library_path()) / "eti_launcher" / "update" / "game.db"
        )

    def _resolve_provider_runtime_update_db_paths(self) -> list[tuple[str, Path]]:
        base = Path(self._effective_library_path())
        sources: list[tuple[str, Path]] = []
        for item in self._provider_items(only_enabled=True):
            provider_game_id = str(item.get("game_id", "") or "").strip()
            if not provider_game_id or not bool(item.get("has_game_db", False)):
                continue
            sources.append(
                (
                    provider_game_id,
                    base / provider_game_id / "update" / "game.db",
                )
            )
        return sources

    def _resolve_runtime_update_db_sources(self) -> list[tuple[str, Path]]:
        # ETI source remains the primary default source.
        sources: list[tuple[str, Path]] = [
            ("eti_launcher", self._resolve_runtime_update_db_path())
        ]
        for source in self._resolve_provider_runtime_update_db_paths():
            if source[0] == "eti_launcher":
                continue
            sources.append(source)
        return sources

    def _runtime_update_db_signature_for_path(
        self, path: Path
    ) -> tuple[str, int, int] | None:
        try:
            stat = path.stat()
        except OSError:
            return None
        return (str(path.resolve()), int(stat.st_mtime_ns), int(stat.st_size))

    def _version_rank(self, raw: str) -> int:
        text = str(raw or "").strip()
        if not text:
            return 0
        # Compare dotted release versions component-wise; concatenating digits
        # makes 0.7.842 incorrectly newer than 9.9.9.
        dotted = text.split(".")
        if len(dotted) > 1 and all(part.isdigit() for part in dotted):
            rank = 0
            for part in dotted[:4]:
                rank = (rank * 1_000_000) + int(part)
            return rank
        digits = "".join(ch for ch in text if ch.isdigit())
        if not digits:
            return 0
        try:
            return int(digits)
        except ValueError:
            return 0

    def _legacy_db_game_versions(self, db_path: str) -> dict[str, str]:
        versions: dict[str, str] = {}
        conn = sqlite3.connect(db_path)
        try:
            rows = conn.execute("SELECT game_id, game_version FROM games").fetchall()
            for row in rows:
                game_id = str(row[0] or "").strip()
                if not game_id:
                    continue
                versions[game_id] = str(row[1] or "").strip()
        finally:
            conn.close()
        return versions

    def _legacy_db_discarded_games(self, db_path: str) -> list[tuple[str, str]]:
        discarded: list[tuple[str, str]] = []
        conn = sqlite3.connect(db_path)
        try:
            rows = conn.execute("SELECT game_id, game_key FROM discarded").fetchall()
        except sqlite3.OperationalError:
            return discarded
        finally:
            conn.close()

        seen_ids: set[str] = set()
        for row in rows:
            game_id = str(row[0] if len(row) > 0 else "").strip()
            if not game_id or game_id in seen_ids:
                continue
            seen_ids.add(game_id)
            discarded.append((game_id, str(row[1] if len(row) > 1 else "").strip()))
        return discarded

    def _apply_runtime_db_discarded_games(
        self, source_game_id: str, db_path: str
    ) -> tuple[int, int, bool]:
        if self._state.repository is None:
            return 0, 0, False

        logger = logging.getLogger(__name__)
        scanned = 0
        applied = 0
        failed = False
        for game_id, game_key in self._legacy_db_discarded_games(db_path):
            scanned += 1
            local_game_id = self._state.repository.resolve_catalog_game_id(game_id)
            if not local_game_id:
                continue
            delete_result = self._delete_game_action(
                local_game_id, ignore_sync_errors=True
            )
            if not bool(delete_result.get("ok", False)):
                failed = True
                logger.warning(
                    "runtime_update_db_discard_delete_failed source=%s game_id=%s game_key=%s message=%s",
                    source_game_id,
                    local_game_id,
                    game_key,
                    delete_result.get("message", ""),
                )
                continue
            # Runtime DB ingestion is upsert-only, so discarded rows are the explicit
            # authoritative signal to purge local catalog state for removed games.
            removed_rows = self._state.repository.remove_catalog_game(local_game_id)
            if removed_rows > 0:
                applied += 1
                logger.warning(
                    "runtime_update_db_discard_applied source=%s game_id=%s game_key=%s",
                    source_game_id,
                    local_game_id,
                    game_key,
                )
        return scanned, applied, failed

    def _try_import_runtime_update_dbs(self) -> bool:
        if self._state.database is None:
            return False

        logger = logging.getLogger(__name__)
        imported_signatures = self._state.runtime_db_last_imported_signatures or {}
        failed_signatures = self._state.runtime_db_last_failed_signatures or {}
        imported_any = False
        provider_game_versions: dict[str, tuple[int, str, str]] = {}

        for source_game_id, source_path in self._resolve_runtime_update_db_sources():
            signature = self._runtime_update_db_signature_for_path(source_path)
            source_key = str(source_path.resolve())
            if signature is None:
                failed_signatures.pop(source_key, None)
                continue
            if signature == imported_signatures.get(source_key):
                continue

            is_provider_source = source_game_id not in {"", "eti_launcher"}
            if is_provider_source:
                try:
                    source_versions = self._legacy_db_game_versions(signature[0])
                    for game_id, raw_version in source_versions.items():
                        rank = self._version_rank(raw_version)
                        seen = provider_game_versions.get(game_id)
                        if seen is None:
                            provider_game_versions[game_id] = (
                                rank,
                                raw_version,
                                source_game_id,
                            )
                            continue
                        if seen[2] == source_game_id:
                            continue
                        if rank > seen[0]:
                            logger.warning(
                                "provider_game_conflict game_id=%s providers=%s,%s versions=%s,%s preferred_provider=%s",
                                game_id,
                                seen[2],
                                source_game_id,
                                seen[1],
                                raw_version,
                                source_game_id,
                            )
                            provider_game_versions[game_id] = (
                                rank,
                                raw_version,
                                source_game_id,
                            )
                        else:
                            logger.warning(
                                "provider_game_conflict game_id=%s providers=%s,%s versions=%s,%s preferred_provider=%s",
                                game_id,
                                seen[2],
                                source_game_id,
                                seen[1],
                                raw_version,
                                seen[2],
                            )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "provider_versions_read_failed path=%s error=%s",
                        signature[0],
                        exc,
                    )

            try:
                summary = import_legacy_catalog(
                    self._state.database.connection, signature[0]
                )
            except Exception as exc:  # noqa: BLE001
                if signature != failed_signatures.get(source_key):
                    logger.warning(
                        "runtime_update_db_import_failed path=%s source=%s error=%s",
                        signature[0],
                        source_game_id,
                        exc,
                    )
                    failed_signatures[source_key] = signature
                continue

            discarded_scanned, discarded_count, discarded_failed = (
                self._apply_runtime_db_discarded_games(source_game_id, signature[0])
            )
            if discarded_failed:
                if signature != failed_signatures.get(source_key):
                    logger.warning(
                        "runtime_update_db_discard_retry_pending path=%s source=%s",
                        signature[0],
                        source_game_id,
                    )
                    failed_signatures[source_key] = signature
                continue

            imported_signatures[source_key] = signature
            failed_signatures.pop(source_key, None)
            imported_any = True
            logger.info(
                "runtime_update_db_imported path=%s source=%s genres=%s games=%s tools=%s revoked_games=%s discarded_rows=%s",
                signature[0],
                source_game_id,
                summary.get("genres", 0),
                summary.get("games", 0),
                summary.get("tools", 0),
                discarded_count,
                discarded_scanned,
            )

        self._state.runtime_db_last_imported_signatures = imported_signatures
        self._state.runtime_db_last_failed_signatures = failed_signatures
        if imported_any and self._state.scanner is not None:
            self._state.scanner.scan(force=True)
        return imported_any

    def _run_legacy_db_watchdog(self) -> None:
        while True:
            if (
                self._state.legacy_db_watchdog_stop is not None
                and self._state.legacy_db_watchdog_stop.is_set()
            ):
                return
            try:
                self._try_import_runtime_update_dbs()
            except Exception as exc:  # noqa: BLE001
                logging.getLogger(__name__).warning(
                    "runtime_update_db_watchdog_error: %s", exc
                )
            try:
                self._refresh_game_index_if_changed()
            except Exception as exc:  # noqa: BLE001
                logging.getLogger(__name__).warning(
                    "game_index_watchdog_error: %s", exc
                )
            try:
                self._refresh_provider_image_archives()
            except Exception as exc:  # noqa: BLE001
                logging.getLogger(__name__).warning(
                    "provider_image_watchdog_error: %s", exc
                )
            time.sleep(300.0)

    def _refresh_game_index_if_changed(self) -> bool:
        store = self._state.game_index_store
        if store is None:
            return False
        refreshed = store.refresh_if_changed()
        indexed_game_entries = store.managed_game_entries()
        indexed_game_ids = (
            {metadata.game_id for metadata in indexed_game_entries}
            if indexed_game_entries is not None
            else None
        )
        repo = self._state.repository
        if repo is not None:
            if indexed_game_entries is not None:
                repo.reconcile_game_index_membership(indexed_game_ids or set())
                repo.reconcile_game_index_catalog(indexed_game_entries)
                pending_removal = repo.pending_game_index_removals()
            else:
                pending_removal = repo.pending_game_index_removals()
            for game_id in pending_removal:
                install_state = repo.current_install_state(game_id)
                local_install = Path(self._effective_library_path()) / game_id / "local"
                if install_state == "installing" or (
                    install_state == "installed" and local_install.is_dir()
                ):
                    continue
                removed = repo.remove_catalog_game(game_id)
                repo.clear_game_index_membership(game_id)
                if removed:
                    logging.getLogger(__name__).info(
                        "game_index_entry_retired game_id=%s", game_id
                    )
        if refreshed:
            logging.getLogger(__name__).info("game_index_provider_refreshed")
        return refreshed

    def _try_import_lan_catalog(self) -> bool:
        repo = self._state.repository
        if repo is None:
            return False
        root = Path(self._effective_library_path()) / "locallansync"
        ouisync_path = root / ".ouisync" / "index.json"
        path = ouisync_path if ouisync_path.is_file() else root / "index.json"
        signature = self._runtime_update_db_signature_for_path(path)
        if signature is None or signature == self._state.lan_index_last_signature:
            return False
        result = repo.reconcile_lan_snapshot(path)
        self._state.lan_index_last_signature = signature
        if result["conflicts"]:
            logging.getLogger(__name__).warning(
                "lan_catalog_conflicts count=%s", result["conflicts"]
            )
        if self._state.scanner is not None:
            self._state.scanner.scan(force=True)
        return True

    def bootstrap(self) -> None:
        bundle_check = run_bundle_checks(
            manifest_path=self._config.tool_manifest_path,
            repo_root=self._config.repo_root,
        )
        for warning in bundle_check.warnings:
            logging.getLogger(__name__).warning("bundle_warning:%s", warning)
        if not bundle_check.ok:
            raise RuntimeError(
                f"required_bundle_tools_invalid:{';'.join(bundle_check.errors)}"
            )

        self._state.database = open_database(self._config.db_path)
        conn = self._state.database.connection
        self._state.repository = CatalogRepository(
            conn,
            metadata_root=self._state.metadata_root,
            metadata_lookup=self._game_metadata,
        )
        self._ensure_default_extra_sync_item()
        self._state.sync_provider = create_dual_sync_provider(
            self._config,
            resolve_game_provider_type=self._resolve_game_provider_type,
            resolve_catalog_provider_types=self._state.repository.list_game_provider_types,
        )
        self._state.platform_adapter = create_platform_adapter(
            force_platform=self._config.platform_override or None
        )
        platform_name = self._state.platform_adapter.platform_name()
        logging.getLogger(__name__).warning(runtime_requirements_hint(platform_name))
        self._state.settings_store = SettingsStore(self._config.settings_path)
        self._set_launcher_site_snapshot(
            default_snapshot(
                source_url=self._config.launcher_ini_url or DEFAULT_LAUNCHER_INI_URL
            )
        )
        self._load_launcher_site_snapshot_from_cache()
        self._refresh_launcher_site_snapshot()
        default_settings = UserSettings(
            nickname="",
            theme="dark",
            log_level="WARNING",
            auto_start_sync=True,
            sync_only_mode=False,
            library_path_initialized=False,
            windows_game_drive_letter=self._config.windows_game_drive_letter,
            linux_install_path=default_linux_install_path(
                platform_name, self._config.library_path
            ),
            linux_windows_runtime="wine",
            linux_proton_path="",
            linux_proton_ge_path="",
            lan_mode="client",
            ouisync_storage_path="",
        )
        self._state.user_settings = self._state.settings_store.load(default_settings)
        self._set_game_index_provider_path(self._effective_library_path())
        set_log_level(self._state.user_settings.log_level)
        if (
            self._state.settings_store is not None
            and self._state.settings_store.exists()
        ):
            self._state.user_settings = replace(
                self._state.user_settings, library_path_initialized=True
            )
        autodiscovered = False
        self._state.user_settings, autodiscovered = apply_linux_proton_autodiscovery(
            self._state.user_settings,
            platform_name,
        )
        if autodiscovered and self._state.settings_store is not None:
            try:
                self._state.settings_store.save(self._state.user_settings)
                logging.getLogger(__name__).info(
                    "linux_proton_paths_autodiscovered proton=%s proton_ge=%s",
                    self._state.user_settings.linux_proton_path,
                    self._state.user_settings.linux_proton_ge_path,
                )
            except OSError as exc:
                logging.getLogger(__name__).warning(
                    "linux_proton_paths_autodiscovery_save_failed error=%s", exc
                )
        self._state.desired_sync_running = self._state.user_settings.auto_start_sync
        self._state.sync_watchdog_paused = False
        effective_library_path = self._effective_library_path()
        self._state.install_support = InstallSupport(
            scripts_root=self._config.install_scripts_root,
            checks_path=self._config.install_checks_path,
        )
        self._state.scanner = InstallStateScanner(
            self._state.repository,
            library_path=effective_library_path,
            install_support=self._state.install_support,
        )
        self._state.game_manager = GameLifecycleManager(
            repo=self._state.repository,
            platform_adapter=self._state.platform_adapter,
            install_support=self._state.install_support,
            library_path=effective_library_path,
            unrar_path="vendor/bin/windows-amd64/unrar.exe",
            windows_drive_letter=self._state.user_settings.windows_game_drive_letter,
            windows_lan_root=self._config.windows_lan_root,
            linux_cmd_wrapper_path=self._config.linux_cmd_wrapper_path,
            metadata_store=self._state.metadata_store,
            metadata_lookup=self._game_metadata,
        )
        self._state.game_manager.set_linux_runtime_settings(
            self._state.user_settings.linux_windows_runtime,
            self._state.user_settings.linux_proton_path,
            self._state.user_settings.linux_proton_ge_path,
        )

        imported = import_legacy_catalog(conn, self._resolve_legacy_db_path())
        if any(imported.values()):
            logging.getLogger(__name__).info("legacy_import_complete", extra=imported)
        self._try_import_runtime_update_dbs()
        self._try_import_lan_settings()
        try:
            self._try_import_lan_catalog()
        except (OSError, ValueError, sqlite3.Error) as exc:
            logging.getLogger(__name__).warning(
                "lan_catalog_import_failed error=%s", exc
            )
        try:
            self._refresh_provider_image_archives()
        except Exception as exc:  # noqa: BLE001
            logging.getLogger(__name__).warning(
                "provider_image_bootstrap_error: %s", exc
            )

        self._state.scanner.scan(force=True)
        try:
            self._refresh_game_index_if_changed()
        except Exception as exc:  # noqa: BLE001
            logging.getLogger(__name__).warning(
                "game_index_bootstrap_reconcile_failed error=%s", exc
            )

        self._state.sync_watchdog_stop = Event()
        self._state.sync_watchdog_thread = Thread(
            target=self._run_sync_watchdog, daemon=True
        )
        self._state.sync_watchdog_thread.start()
        self._state.legacy_db_watchdog_stop = Event()
        self._state.legacy_db_watchdog_thread = Thread(
            target=self._run_legacy_db_watchdog, daemon=True
        )
        self._state.legacy_db_watchdog_thread.start()
        self._state.launcher_site_stop = Event()
        self._state.launcher_site_thread = Thread(
            target=self._run_launcher_site_watchdog, daemon=True
        )
        self._state.launcher_site_thread.start()

        self._state.started = True
        logging.getLogger(__name__).info("bootstrap_complete")

    def run(self) -> None:
        logging.getLogger(__name__).info(
            "service_listening",
            extra={
                "bind_host": self._config.bind_host,
                "bind_port": self._config.bind_port,
            },
        )
        self._server.serve_forever(poll_interval=0.5)

    def stop(self) -> None:
        with self._stop_lock:
            if self._stopped:
                return
            self._stopped = True
        # Prevent watchdog restart races during shutdown.
        self._state.sync_watchdog_paused = True
        self._state.desired_sync_running = False
        if self._state.sync_watchdog_stop is not None:
            self._state.sync_watchdog_stop.set()
        if self._state.sync_watchdog_thread is not None:
            self._state.sync_watchdog_thread.join(timeout=3)
        if self._lan_discovery is not None:
            self._lan_discovery.close()
            self._lan_discovery = None
        if self._state.legacy_db_watchdog_stop is not None:
            self._state.legacy_db_watchdog_stop.set()
        if self._state.legacy_db_watchdog_thread is not None:
            self._state.legacy_db_watchdog_thread.join(timeout=3)
        if self._state.launcher_site_stop is not None:
            self._state.launcher_site_stop.set()
        if self._state.launcher_site_thread is not None:
            self._state.launcher_site_thread.join(timeout=3)
        if self._state.sync_provider is not None:
            try:
                self._state.sync_provider.stop()
            except Exception as exc:  # noqa: BLE001
                logging.getLogger(__name__).warning("sync_stop_failed: %s", exc)
        try:
            close_browser_app_mode()
        except Exception as exc:  # noqa: BLE001
            logging.getLogger(__name__).debug(
                "browser_close_on_shutdown_failed: %s", exc
            )
        self._server.shutdown()
        self._server.server_close()
        if self._state.database is not None:
            self._state.database.connection.close()
        self._shutdown.set()
