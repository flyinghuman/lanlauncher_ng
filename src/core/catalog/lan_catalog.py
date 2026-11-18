"""Reconcile a validated LAN snapshot with locally owned catalog records."""

from __future__ import annotations

import json
import math
import sqlite3
from pathlib import Path
from typing import Any

from src.core.catalog.game_index import GameIndexStore
from src.core.catalog.lan_snapshot import read_snapshot


def reconcile_snapshot(conn: sqlite3.Connection, index_path: Path) -> dict[str, int]:
    """Import one complete snapshot, leaving unrelated sources and files alone.

    The caller must serialize access to the connection. A missing or malformed
    snapshot raises before any mutation; it never means an empty catalog.
    """
    path = index_path.resolve(strict=True)
    snapshot = read_snapshot(path)
    source_id = snapshot["source"]["id"]
    store = GameIndexStore(str(path), path.parent / ".unused-index-cache")
    entries: list[tuple[dict[str, Any], Any, str]] = []
    for item in snapshot["games"]:
        metadata = store._parse_entry(
            item, "", schema_version=2 if "llng" in item else 1
        )
        if metadata is None or (
            metadata.size_gb is not None
            and (not math.isfinite(metadata.size_gb) or metadata.size_gb < 0)
        ):
            raise ValueError("lan_index_game_invalid")
        # Ensure malformed extension values cannot produce a partial update.
        raw = json.dumps(item, ensure_ascii=False, allow_nan=False)
        entries.append((item, metadata, raw))

    counts = {"updated": 0, "removed": 0, "retained": 0, "conflicts": 0}
    incoming_ids = {item["game_id"].casefold() for item, _, _ in entries}
    with conn:
        old_rows = conn.execute(
            "SELECT game_id FROM lan_catalog_entries WHERE source_id = ? AND available = 1",
            (source_id,),
        ).fetchall()
        for row in old_rows:
            game_id = str(row[0])
            if game_id.casefold() in incoming_ids:
                continue
            state = conn.execute(
                "SELECT state FROM install_state WHERE game_id = ? COLLATE NOCASE",
                (game_id,),
            ).fetchone()
            if state and str(state[0]).lower() in {
                "installed",
                "installing",
            }:
                conn.execute(
                    "UPDATE lan_catalog_entries SET available = 0, retained = 1 WHERE game_id = ?",
                    (game_id,),
                )
                counts["retained"] += 1
            else:
                conn.execute(
                    "UPDATE lan_catalog_entries SET available = 0, retained = 0 WHERE game_id = ?",
                    (game_id,),
                )
                conn.execute(
                    "DELETE FROM game_catalog WHERE id = ? COLLATE NOCASE", (game_id,)
                )
                conn.execute(
                    "UPDATE install_state SET state = 'missing' WHERE game_id = ? COLLATE NOCASE AND state = 'downloading'",
                    (game_id,),
                )
                counts["removed"] += 1

        for item, metadata, raw in entries:
            game_id = item["game_id"]
            provider_type = "ouisync"
            provider_key = metadata.distribution_info_hash
            owner = conn.execute(
                "SELECT game_id, source_id, available, retained FROM lan_catalog_entries WHERE game_id = ? COLLATE NOCASE",
                (game_id,),
            ).fetchone()
            existing = conn.execute(
                "SELECT id FROM game_catalog WHERE id = ? COLLATE NOCASE",
                (game_id,),
            ).fetchone()
            extra = conn.execute(
                "SELECT game_id FROM extra_sync_items WHERE game_id = ? COLLATE NOCASE",
                (game_id,),
            ).fetchone()
            if (
                extra
                or (owner and owner[1] != source_id)
                or (existing and (not owner or not (owner[2] or owner[3])))
            ):
                counts["conflicts"] += 1
                continue
            if owner:
                game_id = str(owner[0])
            conn.execute(
                """
                INSERT INTO game_catalog(id, title_en, title_de, key, release_year, publisher,
                    size_gb, readme_en, readme_de, max_players, master_required, version, game_provider_type)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET title_en=excluded.title_en,
                    title_de=excluded.title_de, key=excluded.key, release_year=excluded.release_year,
                    publisher=excluded.publisher, size_gb=excluded.size_gb,
                    readme_en=excluded.readme_en, readme_de=excluded.readme_de,
                    max_players=excluded.max_players, master_required=excluded.master_required,
                    version=excluded.version, game_provider_type=excluded.game_provider_type
                """,
                (
                    game_id,
                    metadata.title,
                    metadata.title_de,
                    provider_key,
                    metadata.release_year,
                    metadata.publisher,
                    metadata.size_gb or 0,
                    metadata.description,
                    metadata.description_de,
                    metadata.max_players,
                    int(bool(metadata.master_required)),
                    metadata.version,
                    provider_type,
                ),
            )
            conn.execute(
                """INSERT INTO lan_catalog_entries(game_id, source_id, index_path, metadata_json, available)
                   VALUES (?, ?, ?, ?, 1)
                   ON CONFLICT(game_id) DO UPDATE SET source_id=excluded.source_id,
                     index_path=excluded.index_path, metadata_json=excluded.metadata_json, available=1, retained=0""",
                (game_id, source_id, str(path), raw),
            )
            counts["updated"] += 1
    return counts
