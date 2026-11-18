"""Cross-platform helper functions used by OS adapters."""

from __future__ import annotations

from pathlib import Path


def normalize_user_path(raw_path: str) -> Path:
    """Expand and normalize path without requiring existence.

    `resolve(strict=False)` keeps behavior deterministic while allowing a caller
    to validate not-yet-created paths.
    """

    return Path(raw_path).expanduser().resolve(strict=False)
