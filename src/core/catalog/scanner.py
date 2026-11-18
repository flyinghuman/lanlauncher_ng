"""Install-state scanning with simple TTL-based cache invalidation."""

from __future__ import annotations

import time
from configparser import ConfigParser
from configparser import Error as ConfigParserError
from dataclasses import dataclass
from pathlib import Path

from src.core.catalog.install_support import InstallSupport
from src.core.catalog.repository import CatalogRepository


@dataclass
class ScanStats:
    scanned: int
    installed: int
    missing: int


class InstallStateScanner:
    def __init__(
        self,
        repo: CatalogRepository,
        library_path: str,
        install_support: InstallSupport,
        ttl_seconds: int = 30,
    ):
        self._repo = repo
        self._library = Path(library_path)
        self._support = install_support
        self._ttl_seconds = ttl_seconds
        self._last_scan_at = 0.0

    def set_library_path(self, library_path: str) -> None:
        # Settings updates can move the library root without restarting the service.
        self._library = Path(library_path)
        self._last_scan_at = 0.0

    def _is_installed(self, game_id: str) -> bool:
        game_dir = self._library / game_id
        if not (game_dir.exists() and game_dir.is_dir()):
            return False
        game = self._repo.get_game(game_id, locale="en") or {}
        metadata = game.get("metadata", {}) if isinstance(game, dict) else {}
        game_provider_type = str(game.get("game_provider_type", "") or "").strip().lower()
        start_file = ""
        if isinstance(metadata, dict):
            game_start = metadata.get("game_start")
            if isinstance(game_start, dict):
                start_file = str(game_start.get("file", "") or "").strip()

        markers = self._support.marker_paths_for(game_id)
        if not markers:
            # Without explicit marker config, treat a game as installed only when
            # unpack/runtime artifacts exist, not when the folder only contains sync payload.
            local_dir = game_dir / "local"
            has_local_dir = local_dir.exists() and local_dir.is_dir()
            has_game_start = False
            if start_file:
                candidate = game_dir / Path(start_file.replace("\\", "/"))
                has_game_start = candidate.exists() and candidate.is_file()
            if not has_game_start:
                has_game_start = any(
                    (game_dir / script_name).exists()
                    for script_name in ("game_start.cmd", "game_start.sh")
                )
            if game_provider_type == "local":
                return has_game_start
            return has_local_dir and has_game_start

        # Marker checks allow per-game installed detection beyond folder presence.
        return any((game_dir / marker).exists() for marker in markers)

    def _installed_version(self, game_id: str) -> str:
        ini_path = self._library / game_id / "version.ini"
        if not ini_path.exists():
            return ""
        try:
            raw = ini_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
        parser = ConfigParser()
        try:
            parser.read_string(raw)
        except ConfigParserError:
            # Legacy launchers sometimes wrote plain version string without INI sections.
            for line in raw.splitlines():
                value = line.strip()
                if value:
                    return value
            return ""
        if parser.has_option("version", "local"):
            return parser.get("version", "local")
        if parser.has_option("game", "version"):
            return parser.get("game", "version")
        if parser.defaults().get("version"):
            return str(parser.defaults().get("version"))
        return ""

    def scan(self, force: bool = False) -> ScanStats:
        now = time.time()
        if not force and (now - self._last_scan_at) < self._ttl_seconds:
            return ScanStats(scanned=0, installed=0, missing=0)

        game_ids = self._repo.list_game_ids()
        installed = 0
        missing = 0

        for game_id in game_ids:
            current_state = self._repo.current_install_state(game_id)
            if self._is_installed(game_id):
                self._repo.set_install_state(
                    game_id, "installed", self._installed_version(game_id)
                )
                installed += 1
            else:
                if current_state in {"downloading", "installing"}:
                    # Auto-install workflow uses transient states while sync/unpack is in progress.
                    # Do not overwrite them to missing during periodic scans.
                    missing += 1
                    continue
                self._repo.set_install_state(game_id, "missing", "")
                missing += 1

        self._last_scan_at = now
        return ScanStats(scanned=len(game_ids), installed=installed, missing=missing)
