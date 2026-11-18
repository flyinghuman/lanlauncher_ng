"""Database connection and bootstrap helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3

from src.core.db.migrations import apply_migrations


@dataclass
class Database:
    path: Path
    connection: sqlite3.Connection


def open_database(db_path: str) -> Database:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    # Threaded HTTP server handlers access the same connection instance.
    conn = sqlite3.connect(path, check_same_thread=False)
    apply_migrations(conn)

    return Database(path=path, connection=conn)
