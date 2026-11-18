"""Install script resolution and install-check rules."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path


@dataclass(frozen=True)
class InstallScriptInfo:
    game_id: str
    platform: str
    exists: bool
    path: str


class InstallSupport:
    def __init__(self, scripts_root: str, checks_path: str):
        self._scripts_root = Path(scripts_root)
        self._checks_path = Path(checks_path)
        self._checks = self._load_checks()

    def _load_checks(self) -> dict:
        if not self._checks_path.exists():
            return {"games": {}}
        try:
            return json.loads(self._checks_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"games": {}}

    def refresh(self) -> None:
        self._checks = self._load_checks()

    def install_script_for(self, game_id: str, platform_name: str) -> InstallScriptInfo:
        extension = ".ps1" if platform_name == "windows" else ".sh"
        candidate = self._scripts_root / platform_name / f"{game_id}{extension}"
        if not candidate.exists():
            candidate = self._scripts_root / platform_name / f"install-game{extension}"

        return InstallScriptInfo(
            game_id=game_id,
            platform=platform_name,
            exists=candidate.exists(),
            path=str(candidate),
        )

    def marker_paths_for(self, game_id: str) -> list[str]:
        games = self._checks.get("games", {}) if isinstance(self._checks, dict) else {}
        game = games.get(game_id, {}) if isinstance(games, dict) else {}
        markers = game.get("markers", []) if isinstance(game, dict) else []
        return [str(m) for m in markers if isinstance(m, str) and m]
