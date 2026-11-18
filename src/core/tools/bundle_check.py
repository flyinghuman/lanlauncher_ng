"""Bundled tool manifest integrity checks."""

from __future__ import annotations

import hashlib
import json
import platform
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class BundleCheckResult:
    ok: bool
    checked: int
    errors: list[str]
    warnings: list[str]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes"}
    return bool(value)


def _current_platform_tag() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    if system.startswith("win"):
        return "windows-amd64"
    if system.startswith("linux"):
        if machine in {"x86_64", "amd64"}:
            return "linux-x64"
    return ""


def run_bundle_checks(manifest_path: str, repo_root: str = ".") -> BundleCheckResult:
    manifest_file = Path(manifest_path)
    root = Path(repo_root)

    if not manifest_file.exists():
        return BundleCheckResult(
            ok=False,
            checked=0,
            errors=[f"manifest_missing:{manifest_file}"],
            warnings=[],
        )

    try:
        payload = json.loads(manifest_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return BundleCheckResult(
            ok=False,
            checked=0,
            errors=[f"manifest_invalid_json:{exc}"],
            warnings=[],
        )

    tools = payload.get("tools", [])
    if not isinstance(tools, list):
        return BundleCheckResult(
            ok=False,
            checked=0,
            errors=["manifest_tools_not_array"],
            warnings=[],
        )

    errors: list[str] = []
    warnings: list[str] = []
    current_platform = _current_platform_tag()

    for tool in tools:
        name = str(tool.get("name", "unknown"))
        tool_platform = str(tool.get("platform", "")).strip().lower()
        if tool_platform not in {"", "any"} and current_platform:
            if tool_platform != current_platform:
                continue
        required = _as_bool(tool.get("required", False))
        rel_path = tool.get("path", "")
        expected_hash = str(tool.get("sha256", "")).lower()
        license_rel = tool.get("license_file", "")

        if not rel_path:
            msg = f"tool_path_missing:{name}"
            if required:
                errors.append(msg)
            else:
                warnings.append(msg)
            continue

        tool_path = root / str(rel_path)
        if not tool_path.exists():
            msg = f"tool_missing:{name}:{tool_path}"
            if required:
                errors.append(msg)
            else:
                warnings.append(msg)
            continue

        if expected_hash:
            actual_hash = _sha256(tool_path)
            if actual_hash.lower() != expected_hash:
                msg = f"tool_checksum_mismatch:{name}"
                if required:
                    errors.append(msg)
                else:
                    warnings.append(msg)

        if license_rel:
            license_path = root / str(license_rel)
            if not license_path.exists():
                msg = f"tool_license_missing:{name}:{license_path}"
                if required:
                    errors.append(msg)
                else:
                    warnings.append(msg)

    return BundleCheckResult(
        ok=len(errors) == 0,
        checked=len(tools),
        errors=errors,
        warnings=warnings,
    )
