"""Legacy database import into normalized launcher schema."""

from __future__ import annotations

import sqlite3
from pathlib import Path


def _read_legacy_table(conn: sqlite3.Connection, table: str) -> list[sqlite3.Row]:
    conn.row_factory = sqlite3.Row
    return conn.execute(f"SELECT * FROM {table}").fetchall()


def _to_float(value: object, fallback: float = 0.0) -> float:
    try:
        return float(value) if value is not None else fallback
    except (TypeError, ValueError):
        return fallback


def _to_int(value: object, fallback: int = 0) -> int:
    try:
        return int(value) if value is not None else fallback
    except (TypeError, ValueError):
        return fallback


def _to_text(value: object) -> str:
    return "" if value is None else str(value)


def _version_rank(raw: object) -> int:
    text = _to_text(raw).strip()
    if not text:
        return 0
    digits = "".join(ch for ch in text if ch.isdigit())
    if not digits:
        return 0
    try:
        return int(digits)
    except ValueError:
        return 0


def import_legacy_catalog(
    target_conn: sqlite3.Connection, legacy_db_path: str
) -> dict[str, int]:
    """Import legacy game/tool/genre data from old SQLite format.

    Import is idempotent via upsert semantics on primary keys.
    """

    path = Path(legacy_db_path)
    if not path.exists():
        return {"genres": 0, "games": 0, "tools": 0}

    legacy_conn = sqlite3.connect(path)
    try:
        genres = _read_legacy_table(legacy_conn, "genre")
        games = _read_legacy_table(legacy_conn, "games")
        tools = _read_legacy_table(legacy_conn, "tools")
    finally:
        legacy_conn.close()

    with target_conn:
        for row in genres:
            target_conn.execute(
                """
                INSERT INTO genres(id, name_en, name_de)
                VALUES (?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name_en = excluded.name_en,
                    name_de = excluded.name_de
                """,
                (
                    _to_int(row["genre_id"]),
                    _to_text(row["genre_en"]),
                    _to_text(row["genre_de"]),
                ),
            )

        for row in games:
            incoming_version = _to_text(row["game_version"])
            existing = target_conn.execute(
                "SELECT version FROM game_catalog WHERE id = ?",
                (_to_text(row["game_id"]),),
            ).fetchone()
            existing_version = ""
            if existing is not None:
                if isinstance(existing, sqlite3.Row):
                    existing_version = _to_text(existing["version"])
                else:
                    existing_version = _to_text(existing[0])
            if existing is not None and _version_rank(incoming_version) < _version_rank(
                existing_version
            ):
                # Keep newer catalog record when multiple providers report the same game id.
                continue
            target_conn.execute(
                """
                INSERT INTO game_catalog(
                    id, title_en, title_de, key, release_year, publisher,
                    size_gb, readme_en, readme_de, max_players,
                    master_required, genre_id, version
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    version = excluded.version
                """,
                (
                    _to_text(row["game_id"]),
                    _to_text(row["game_title"]),
                    _to_text(row["game_title"]),
                    _to_text(row["game_key"]),
                    _to_text(row["game_release"]),
                    _to_text(row["game_publisher"]),
                    _to_float(row["game_size"]),
                    _to_text(row["game_readme_en"]),
                    _to_text(row["game_readme_de"]),
                    _to_text(row["game_maxplayers"]),
                    _to_int(row["game_master_req"]),
                    _to_int(row["genre_id"]),
                    incoming_version,
                ),
            )

        for row in tools:
            target_conn.execute(
                """
                INSERT INTO tools(id, name, key, maintainer, size_gb, readme_en, readme_de, disabled)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    key = excluded.key,
                    maintainer = excluded.maintainer,
                    size_gb = excluded.size_gb,
                    readme_en = excluded.readme_en,
                    readme_de = excluded.readme_de,
                    disabled = excluded.disabled
                """,
                (
                    _to_text(row["tool_id"]),
                    _to_text(row["tool_name"]),
                    _to_text(row["tool_key"]),
                    _to_text(row["tool_maintainer"]),
                    _to_float(row["tool_size"]),
                    _to_text(row["tool_readme_en"]),
                    _to_text(row["tool_readme_de"]),
                    _to_int(row["tool_disabled"]),
                ),
            )

    return {"genres": len(genres), "games": len(games), "tools": len(tools)}
