#!/usr/bin/env python3
"""Check per-game installer actions before publishing or packaging game content."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
from pathlib import Path
from typing import Any

_SUPPORTED_ACTIONS = {"winetricks", "protontricks"}
_SKIP_DIRS = {".git", "__pycache__", "local", ".compatdata", "lan-repository", ".staging"}


def _task_list(raw: dict[str, Any]) -> tuple[list[Any], str | None]:
    for key in ("installer_tasks", "installer", "script"):
        if key not in raw:
            continue
        value = raw[key]
        if isinstance(value, dict):
            value = value.get("tasks")
        if not isinstance(value, list):
            return [], f"{key} must be a list of task objects"
        return value, None
    return [], None


def _tokens(raw: Any) -> list[str] | None:
    if isinstance(raw, list):
        if not all(isinstance(value, str) for value in raw):
            return None
        return [value for value in raw if value.strip()]
    if isinstance(raw, str):
        try:
            return shlex.split(raw)
        except ValueError:
            return None
    if raw is None:
        return []
    return None


def _game_id_for(metadata_path: Path) -> str:
    folder = metadata_path.parent
    if folder.name == ".ouisync":
        folder = folder.parent
    return folder.name


def lint_file(path: Path) -> list[str]:
    label = str(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return [f"{label}: cannot read metadata JSON ({exc})"]
    if not isinstance(raw, dict):
        return [f"{label}: metadata root must be an object"]

    diagnostics: list[str] = []
    folder_id = _game_id_for(path)
    declared_id = raw.get("game_id")
    if declared_id is not None and str(declared_id).casefold() != folder_id.casefold():
        diagnostics.append(
            f"{label}: game_id {declared_id!r} does not match containing folder {folder_id!r}"
        )

    tasks, error = _task_list(raw)
    if error:
        diagnostics.append(f"{label}: {error}")
        return diagnostics

    for index, task in enumerate(tasks, start=1):
        prefix = f"{label}: installer task {index}"
        if not isinstance(task, dict):
            diagnostics.append(f"{prefix} must be an object")
            continue
        action = str(task.get("name") or task.get("action") or "").strip().lower()
        if action not in _SUPPORTED_ACTIONS:
            diagnostics.append(
                f"{prefix} has unsupported action {action or '<missing>'!r}; "
                "supported actions are winetricks and protontricks"
            )
            continue

        app = _tokens(task.get("app"))
        args = _tokens(task.get("args"))
        if app is None:
            diagnostics.append(f"{prefix} app must be a string or an array of strings")
            continue
        if args is None:
            diagnostics.append(f"{prefix} args must be a string or an array of strings")
            continue
        package_tokens = app or [value for value in args if not value.startswith("-")]
        if not package_tokens:
            diagnostics.append(f"{prefix} needs a package in app or args")

    return diagnostics


def find_metadata_files(roots: list[Path]) -> list[Path]:
    files: set[Path] = set()
    for root in roots:
        if root.is_file():
            if root.name == "metadata.json":
                files.add(root)
            continue
        if not root.is_dir():
            continue
        for current, directories, names in os.walk(root):
            directories[:] = [name for name in directories if name not in _SKIP_DIRS]
            if "metadata.json" in names:
                files.add(Path(current) / "metadata.json")
    return sorted(files)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "roots",
        nargs="+",
        type=Path,
        help="game folders or metadata.json files to inspect recursively",
    )
    args = parser.parse_args(argv)

    files = find_metadata_files(args.roots)
    errors = [message for path in files for message in lint_file(path)]
    if errors:
        for message in errors:
            print(f"ERROR: {message}", file=sys.stderr)
        return 1
    print(f"OK: validated installer actions in {len(files)} metadata file(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
