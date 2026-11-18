"""Centralized version metadata for launcher core."""

from __future__ import annotations

from pathlib import Path

APP_NAME = "lanlauncher-core"
BUILD_DATE = "2026-03-03"
GIT_COMMIT = "dev"


def _load_version() -> str:
    # VERSION file is the single source of truth for app and installer versioning.
    current = Path(__file__).resolve()
    candidates = [parent / "VERSION" for parent in current.parents]
    candidates.append(Path.cwd() / "VERSION")

    for version_file in candidates:
        try:
            if not version_file.exists():
                continue
            value = version_file.read_text(encoding="utf-8").strip()
            if value:
                return value
        except OSError:
            continue
    return "0.0.0-dev"


APP_VERSION = _load_version()
