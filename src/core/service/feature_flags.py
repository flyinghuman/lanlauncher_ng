"""Feature flag resolution for staged rollout controls."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FeatureFlagDefinition:
    key: str
    default: bool
    description: str


FEATURE_FLAG_DEFINITIONS: tuple[FeatureFlagDefinition, ...] = (
    FeatureFlagDefinition(
        key="shutdown_update_recovery",
        default=True,
        description="Enable interrupted shutdown-update recovery (resume/abort) flow.",
    ),
)


def _parse_bool(raw: object, default: bool) -> bool:
    if isinstance(raw, bool):
        return raw
    text = str(raw or "").strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


class FeatureFlags:
    def __init__(self, values: dict[str, bool], source_path: str) -> None:
        self._values = dict(values)
        self._source_path = source_path

    def is_enabled(self, key: str) -> bool:
        return bool(self._values.get(key, False))

    def values(self) -> dict[str, bool]:
        return dict(self._values)

    def payload(self) -> dict:
        definitions = [
            {
                "key": item.key,
                "default": item.default,
                "description": item.description,
                "enabled": self.is_enabled(item.key),
            }
            for item in FEATURE_FLAG_DEFINITIONS
        ]
        return {
            "values": self.values(),
            "definitions": definitions,
            "source_path": self._source_path,
        }


def load_feature_flags(path: str) -> FeatureFlags:
    logger = logging.getLogger(__name__)
    source_path = str(path or "").strip()
    source_file = (
        Path(source_path) if source_path else Path("config/feature-flags.json")
    )
    if not source_file.is_absolute():
        source_file = Path.cwd() / source_file

    resolved: dict[str, bool] = {
        item.key: item.default for item in FEATURE_FLAG_DEFINITIONS
    }
    file_payload: dict[str, object] = {}

    if source_file.exists() and source_file.is_file():
        try:
            raw = json.loads(source_file.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                if isinstance(raw.get("flags"), dict):
                    file_payload = raw.get("flags", {})
                else:
                    file_payload = raw
        except (OSError, json.JSONDecodeError):
            logger.warning("feature_flags_load_failed path=%s", source_file)

    for definition in FEATURE_FLAG_DEFINITIONS:
        if definition.key in file_payload:
            resolved[definition.key] = _parse_bool(
                file_payload.get(definition.key), definition.default
            )

    for definition in FEATURE_FLAG_DEFINITIONS:
        env_key = f"LLNG_FF_{definition.key.upper().replace('-', '_')}"
        if env_key in os.environ:
            resolved[definition.key] = _parse_bool(
                os.environ.get(env_key), resolved[definition.key]
            )

    logger.info("feature_flags_loaded values=%s source=%s", resolved, source_file)
    return FeatureFlags(resolved, str(source_file))
