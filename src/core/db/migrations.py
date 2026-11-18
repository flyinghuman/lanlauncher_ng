"""SQLite schema bootstrap and migration handling."""

from __future__ import annotations

import sqlite3

SCHEMA_VERSION = 14

MIGRATION_SQL: dict[int, list[str]] = {
    1: [
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS app_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS games (
            id TEXT PRIMARY KEY,
            title_en TEXT NOT NULL,
            title_de TEXT NOT NULL,
            version TEXT NOT NULL DEFAULT ''
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS install_state (
            game_id TEXT PRIMARY KEY,
            state TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (game_id) REFERENCES games(id)
        );
        """,
    ],
    2: [
        """
        CREATE TABLE IF NOT EXISTS genres (
            id INTEGER PRIMARY KEY,
            name_en TEXT NOT NULL,
            name_de TEXT NOT NULL
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS tools (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            key TEXT NOT NULL,
            maintainer TEXT NOT NULL DEFAULT '',
            size_gb REAL NOT NULL DEFAULT 0,
            readme_en TEXT NOT NULL DEFAULT '',
            readme_de TEXT NOT NULL DEFAULT '',
            disabled INTEGER NOT NULL DEFAULT 0
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS game_catalog (
            id TEXT PRIMARY KEY,
            title_en TEXT NOT NULL,
            title_de TEXT NOT NULL,
            key TEXT NOT NULL,
            release_year TEXT NOT NULL DEFAULT '',
            publisher TEXT NOT NULL DEFAULT '',
            size_gb REAL NOT NULL DEFAULT 0,
            readme_en TEXT NOT NULL DEFAULT '',
            readme_de TEXT NOT NULL DEFAULT '',
            max_players TEXT NOT NULL DEFAULT '',
            master_required INTEGER NOT NULL DEFAULT 0,
            genre_id INTEGER,
            version TEXT NOT NULL DEFAULT '',
            FOREIGN KEY (genre_id) REFERENCES genres(id)
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS sync_state (
            game_id TEXT PRIMARY KEY,
            progress_percent REAL NOT NULL DEFAULT 0,
            download_bps INTEGER NOT NULL DEFAULT 0,
            upload_bps INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'idle',
            updated_at TEXT NOT NULL,
            FOREIGN KEY (game_id) REFERENCES game_catalog(id)
        );
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_game_catalog_title_en ON game_catalog(title_en);
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_game_catalog_genre_id ON game_catalog(genre_id);
        """,
    ],
    3: [
        """
        CREATE TABLE IF NOT EXISTS extra_sync_items (
            game_id TEXT PRIMARY KEY,
            game_key TEXT NOT NULL,
            title_en TEXT NOT NULL DEFAULT '',
            title_de TEXT NOT NULL DEFAULT '',
            release_year TEXT NOT NULL DEFAULT '',
            publisher TEXT NOT NULL DEFAULT '',
            size_gb REAL NOT NULL DEFAULT 0,
            readme_en TEXT NOT NULL DEFAULT '',
            readme_de TEXT NOT NULL DEFAULT '',
            max_players TEXT NOT NULL DEFAULT '',
            master_required INTEGER NOT NULL DEFAULT 0,
            version TEXT NOT NULL DEFAULT '',
            visible_in_gamelist INTEGER NOT NULL DEFAULT 1,
            sync_enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """,
    ],
    4: [
        """
        ALTER TABLE install_state ADD COLUMN installed_version TEXT NOT NULL DEFAULT '';
        """,
    ],
    5: [
        """
        ALTER TABLE extra_sync_items ADD COLUMN is_game_provider INTEGER NOT NULL DEFAULT 0;
        """,
        """
        ALTER TABLE extra_sync_items ADD COLUMN has_game_db INTEGER NOT NULL DEFAULT 0;
        """,
    ],
    6: [
        """
        ALTER TABLE extra_sync_items ADD COLUMN is_seeded_default INTEGER NOT NULL DEFAULT 0;
        """,
    ],
    7: [
        """
        CREATE TABLE IF NOT EXISTS game_launch_settings (
            game_id TEXT PRIMARY KEY,
            linux_runtime TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (game_id) REFERENCES game_catalog(id)
        );
        """,
    ],
    8: [
        """
        ALTER TABLE game_launch_settings
        ADD COLUMN linux_leave_terminal_open INTEGER NOT NULL DEFAULT 0;
        """,
    ],
    9: [
        """
        ALTER TABLE extra_sync_items
        ADD COLUMN packed_image_path TEXT NOT NULL DEFAULT '';
        """,
        """
        ALTER TABLE extra_sync_items
        ADD COLUMN packed_image_password TEXT NOT NULL DEFAULT '';
        """,
    ],
    10: [
        """
        ALTER TABLE extra_sync_items
        ADD COLUMN game_provider_type TEXT NOT NULL DEFAULT 'resilio';
        """,
    ],
    11: [
        """
        ALTER TABLE game_catalog
        ADD COLUMN game_provider_type TEXT NOT NULL DEFAULT '';
        """,
    ],
    12: [
        """
        ALTER TABLE game_catalog
        ADD COLUMN hidden INTEGER NOT NULL DEFAULT 0;
        """,
        """
        ALTER TABLE extra_sync_items
        ADD COLUMN hidden INTEGER NOT NULL DEFAULT 0;
        """,
    ],
    13: [
        """
        CREATE TABLE IF NOT EXISTS lan_catalog_entries (
            game_id TEXT PRIMARY KEY COLLATE NOCASE,
            source_id TEXT NOT NULL,
            index_path TEXT NOT NULL,
            metadata_json TEXT NOT NULL,
            available INTEGER NOT NULL DEFAULT 1,
            retained INTEGER NOT NULL DEFAULT 0
        );
        """,
        "CREATE INDEX IF NOT EXISTS idx_lan_catalog_source ON lan_catalog_entries(source_id);",
    ],
    14: [
        """
        CREATE TABLE IF NOT EXISTS game_index_catalog_entries (
            game_id TEXT PRIMARY KEY COLLATE NOCASE,
            present INTEGER NOT NULL DEFAULT 1,
            pending_removal INTEGER NOT NULL DEFAULT 0
        );
        """,
        "CREATE INDEX IF NOT EXISTS idx_game_index_catalog_pending ON game_index_catalog_entries(pending_removal);",
    ],
}


def _current_version(conn: sqlite3.Connection) -> int:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        );
        """
    )

    row = conn.execute(
        "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
    ).fetchone()
    return int(row[0]) if row else 0


def apply_migrations(conn: sqlite3.Connection) -> int:
    """Apply pending migrations and return resulting schema version."""

    current = _current_version(conn)

    for version in range(current + 1, SCHEMA_VERSION + 1):
        statements = MIGRATION_SQL.get(version, [])
        with conn:
            for sql in statements:
                conn.execute(sql)
            conn.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (?, datetime('now'))",
                (version,),
            )

    return SCHEMA_VERSION
