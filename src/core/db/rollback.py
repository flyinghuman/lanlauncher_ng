"""Database backup and rollback helpers for migration operations."""

from __future__ import annotations

import json
import shutil
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path


def _db_backup_dir(db_path: str) -> Path:
    source = Path(db_path)
    stem = source.stem or "database"
    return source.parent / "backups" / stem


def _db_backup_index_path(db_path: str) -> Path:
    return _db_backup_dir(db_path) / "index.json"


def _current_schema_version(db_file: Path) -> int:
    if not db_file.exists() or not db_file.is_file():
        return 0
    try:
        conn = sqlite3.connect(db_file)
        try:
            row = conn.execute(
                "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
            ).fetchone()
            return int(row[0]) if row else 0
        finally:
            conn.close()
    except sqlite3.Error:
        return 0


def _read_backup_index(index_path: Path) -> list[dict]:
    if not index_path.exists() or not index_path.is_file():
        return []
    try:
        payload = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    entries = payload.get("backups", []) if isinstance(payload, dict) else []
    if not isinstance(entries, list):
        return []
    return [item for item in entries if isinstance(item, dict)]


def _write_backup_index(index_path: Path, entries: list[dict]) -> None:
    index_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"backups": entries}
    index_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def create_db_backup(db_path: str, app_version: str = "") -> Path | None:
    source = Path(db_path)
    if not source.exists() or not source.is_file():
        return None
    backup_dir = _db_backup_dir(db_path)
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d-%H%M%S", time.localtime())
    target = backup_dir / f"{source.name}.{timestamp}.bak"
    shutil.copy2(source, target)
    index_path = _db_backup_index_path(db_path)
    entries = _read_backup_index(index_path)
    entries.append(
        {
            "backup_path": str(target),
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "schema_version": _current_schema_version(source),
            "app_version": str(app_version or "").strip(),
        }
    )
    _write_backup_index(index_path, entries)
    return target


def list_db_backups(db_path: str) -> list[dict]:
    backup_dir = _db_backup_dir(db_path)
    if not backup_dir.exists() or not backup_dir.is_dir():
        return []

    indexed_map: dict[str, dict] = {}
    for entry in _read_backup_index(_db_backup_index_path(db_path)):
        path_key = str(entry.get("backup_path", "") or "").strip()
        if path_key:
            indexed_map[path_key] = entry

    entries: list[dict] = []
    for candidate in backup_dir.iterdir():
        if not (candidate.is_file() and candidate.name.endswith(".bak")):
            continue
        key = str(candidate)
        indexed = indexed_map.get(key, {})
        schema_version = int(
            indexed.get("schema_version")
            if isinstance(indexed.get("schema_version"), int)
            else _current_schema_version(candidate)
        )
        entry = {
            "backup_path": key,
            "created_at_utc": str(indexed.get("created_at_utc", "") or "").strip(),
            "schema_version": schema_version,
            "app_version": str(indexed.get("app_version", "") or "").strip(),
            "mtime": candidate.stat().st_mtime,
        }
        entries.append(entry)
    return sorted(entries, key=lambda item: float(item.get("mtime", 0)), reverse=True)


def latest_db_backup(
    db_path: str, target_schema_version: int | None = None
) -> Path | None:
    backups = list_db_backups(db_path)
    for entry in backups:
        schema_version = int(entry.get("schema_version", 0) or 0)
        if target_schema_version is not None and schema_version > target_schema_version:
            continue
        return Path(str(entry.get("backup_path", "") or ""))
    return None


def restore_db_backup(db_path: str, backup_path: str) -> Path:
    source = Path(backup_path)
    if not source.exists() or not source.is_file():
        raise FileNotFoundError(f"backup not found: {source}")
    target = Path(db_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return target
