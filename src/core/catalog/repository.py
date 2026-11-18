"""Catalog query and install-state data access."""

from __future__ import annotations

import sqlite3
import json
from dataclasses import dataclass, replace
from pathlib import Path
from threading import Lock
from typing import Any, Callable

from src.core.catalog.metadata import GameMetadata, MetadataStore, _parse_metadata
from src.core.catalog.game_index import OuisyncRepositoryAccess
from src.core.catalog.lan_catalog import reconcile_snapshot


@dataclass(frozen=True)
class ListQuery:
    locale: str = "en"
    q: str = ""
    genre_id: int | None = None
    installed: str | None = None
    sort: str = "title"
    order: str = "asc"
    page: int = 1
    page_size: int = 25
    excluded_ids: tuple[str, ...] = ()
    disabled_ids: tuple[str, ...] = ()
    visibility: str = "visible"


class CatalogRepository:
    def __init__(
        self,
        conn: sqlite3.Connection,
        metadata_root: Path | None = None,
        metadata_lookup: Callable[[str], GameMetadata | None] | None = None,
    ):
        self._conn = conn
        self._conn.row_factory = sqlite3.Row
        self._lock = Lock()
        self._metadata_store = MetadataStore(metadata_root or Path.cwd() / "metadata")
        self._metadata_lookup = metadata_lookup

    def reconcile_lan_snapshot(self, index_path: Path) -> dict[str, int]:
        with self._lock:
            return reconcile_snapshot(self._conn, index_path)

    def reconcile_game_index_membership(self, game_ids: set[str]) -> list[str]:
        """Persist current OSGI membership and return titles awaiting retirement."""
        normalized = {
            str(game_id or "").strip().casefold(): str(game_id or "").strip()
            for game_id in game_ids
            if str(game_id or "").strip()
        }
        with self._lock:
            with self._conn:
                previous = self._conn.execute(
                    "SELECT game_id FROM game_index_catalog_entries WHERE present = 1"
                ).fetchall()
                for row in previous:
                    old_id = str(row[0] or "").strip()
                    if old_id and old_id.casefold() not in normalized:
                        self._conn.execute(
                            "UPDATE game_index_catalog_entries SET present = 0, pending_removal = 1 "
                            "WHERE game_id = ? COLLATE NOCASE",
                            (old_id,),
                        )
                for game_id in normalized.values():
                    self._conn.execute(
                        "INSERT INTO game_index_catalog_entries(game_id, present, pending_removal) "
                        "VALUES (?, 1, 0) ON CONFLICT(game_id) DO UPDATE SET "
                        "present = 1, pending_removal = 0",
                        (game_id,),
                    )
                rows = self._conn.execute(
                    "SELECT game_id FROM game_index_catalog_entries WHERE pending_removal = 1"
                ).fetchall()
        return [str(row[0]) for row in rows]

    def reconcile_game_index_catalog(self, entries: list[GameMetadata]) -> None:
        """Expose verified installable index entries in the normal game catalog.

        New entries start visible; existing rows keep the user's hidden flag so
        the periodic index refresh does not undo "hide game".
        """
        with self._lock, self._conn:
            for metadata in entries:
                game_id = str(metadata.game_id or "").strip()
                provider = str(
                    metadata.game_provider_type or metadata.distribution_provider or ""
                ).strip().lower()
                if not game_id or provider != "ouisync":
                    continue
                title_en = str(metadata.title or game_id)
                title_de = str(metadata.title_de or metadata.title or game_id)
                self._conn.execute(
                    """
                    INSERT INTO game_catalog (
                        id, title_en, title_de, key, release_year, publisher, size_gb,
                        readme_en, readme_de, max_players, master_required, genre_id,
                        version, game_provider_type, hidden
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ouisync', 0)
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
                        version = excluded.version,
                        game_provider_type = excluded.game_provider_type
                    """,
                    (
                        game_id,
                        title_en,
                        title_de,
                        str(metadata.key or game_id.upper()),
                        str(metadata.release_year or ""),
                        str(metadata.publisher or ""),
                        float(metadata.size_gb or 0.0),
                        str(metadata.description or ""),
                        str(metadata.description_de or metadata.description or ""),
                        str(metadata.max_players or ""),
                        int(bool(metadata.master_required)),
                        metadata.genre_id,
                        str(metadata.version or ""),
                    ),
                )

    def clear_game_index_membership(self, game_id: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "DELETE FROM game_index_catalog_entries WHERE game_id = ? COLLATE NOCASE",
                (str(game_id or "").strip(),),
            )

    def pending_game_index_removals(self) -> list[str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT game_id FROM game_index_catalog_entries WHERE pending_removal = 1"
            ).fetchall()
        return [str(row[0]) for row in rows]

    def game_id_records(self, game_id: str) -> dict[str, Any]:
        """Find case-insensitive catalog ownership without applying metadata overlays."""
        with self._lock:
            catalog = self._conn.execute(
                "SELECT id, game_provider_type FROM game_catalog WHERE id = ? COLLATE NOCASE LIMIT 1",
                (game_id,),
            ).fetchone()
            extra = self._conn.execute(
                "SELECT game_id FROM extra_sync_items WHERE game_id = ? COLLATE NOCASE LIMIT 1",
                (game_id,),
            ).fetchone()
            owner = self._conn.execute(
                "SELECT source_id FROM lan_catalog_entries WHERE game_id = ? COLLATE NOCASE",
                (game_id,),
            ).fetchone()
        return {"catalog": tuple(catalog) if catalog else None, "extra": bool(extra),
                "lan_source": str(owner[0]) if owner else ""}

    def lan_game_metadata(self, game_id: str) -> GameMetadata | None:
        """Read the last validated LAN entry, including offline launch metadata."""
        with self._lock:
            row = self._conn.execute(
                "SELECT l.game_id, l.index_path, l.metadata_json FROM lan_catalog_entries l "
                "JOIN game_catalog g ON g.id = l.game_id COLLATE NOCASE "
                "WHERE l.game_id = ? COLLATE NOCASE AND (l.available = 1 OR l.retained = 1) "
                "AND lower(g.game_provider_type) = 'ouisync'", (game_id,)
            ).fetchone()
        if row is None:
            return None
        try:
            item = json.loads(row[2])
            if not isinstance(item, dict):
                return None
            metadata = _parse_metadata(str(row[0]), item, Path(str(row[1])).parent)
            if metadata is None:
                return None
            llng = item.get("llng") if isinstance(item.get("llng"), dict) else {}
            distribution = llng.get("distribution") if isinstance(llng.get("distribution"), dict) else {}
            if distribution.get("provider") == "ouisync":
                info_hash = str(distribution.get("info_hash") or "")
                return replace(metadata, key=info_hash, game_provider_type="ouisync",
                               distribution_provider="ouisync",
                               distribution_read_token=str(distribution.get("read_token") or ""),
                               distribution_info_hash=info_hash, image=None, video=None,
                               source_file=str(row[1]))
            return None
        except (ValueError, TypeError, OSError):
            return None

    def unavailable_lan_games(self) -> list[str]:
        """Find revoked LAN shares so their folders can be paused, even offline."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT l.game_id FROM lan_catalog_entries l LEFT JOIN game_catalog g ON g.id = l.game_id COLLATE NOCASE "
                "WHERE l.available = 0 AND (g.id IS NULL OR (l.retained = 1 AND lower(g.game_provider_type) = 'ouisync'))"
            ).fetchall()
        return [str(row[0]) for row in rows]

    def lan_game_available(self, game_id: str) -> bool | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT l.available FROM lan_catalog_entries l LEFT JOIN game_catalog g ON g.id = l.game_id COLLATE NOCASE "
                "WHERE l.game_id = ? COLLATE NOCASE AND (l.available = 1 OR g.id IS NULL "
                "OR (l.retained = 1 AND lower(g.game_provider_type) = 'ouisync')) ", (game_id,)
            ).fetchone()
        return bool(row[0]) if row is not None else None

    def lan_game_ouisync_access(self, game_id: str) -> OuisyncRepositoryAccess | None:
        """Return a private LAN token only to the game-sync path, never catalog payloads."""
        with self._lock:
            row = self._conn.execute(
                "SELECT l.game_id, l.metadata_json FROM lan_catalog_entries l "
                "JOIN game_catalog g ON g.id = l.game_id COLLATE NOCASE "
                "WHERE l.game_id = ? COLLATE NOCASE AND (l.available = 1 OR l.retained = 1) "
                "AND lower(g.game_provider_type) = 'ouisync'",
                (game_id,),
            ).fetchone()
        if row is None:
            return None
        try:
            item = json.loads(row[1])
            llng = item.get("llng") if isinstance(item, dict) else None
            distribution = llng.get("distribution") if isinstance(llng, dict) else None
            if not isinstance(distribution, dict):
                return None
            token = distribution.get("read_token")
            info_hash = distribution.get("info_hash")
            if distribution.get("provider") != "ouisync" or not isinstance(token, str) or not isinstance(info_hash, str):
                return None
            if not token or token != token.strip() or not info_hash:
                return None
            return OuisyncRepositoryAccess(
                game_id=str(row[0]),
                read_token=token,
                expected_info_hash=info_hash,
                editable_files=tuple(),
                repository_namespace="lan-repository",
            )
        except (ValueError, TypeError, OSError):
            return None

    def non_lan_share_game_ids(self) -> set[str]:
        """Hide catalog/provider-owned games from the private LAN share inventory."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT id FROM game_catalog WHERE trim(COALESCE(game_provider_type, '')) != '' "
                "AND lower(trim(game_provider_type)) != 'local' "
                "UNION SELECT game_id FROM extra_sync_items WHERE trim(COALESCE(game_provider_type, '')) != '' "
                "AND lower(trim(game_provider_type)) != 'local' "
                "UNION SELECT game_id FROM game_index_catalog_entries "
                "WHERE present = 1 OR pending_removal = 1"
            ).fetchall()
        return {str(row[0]).casefold() for row in rows if row[0]}

    def lan_cover_path(self, game_id: str) -> Path | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT index_path, metadata_json FROM lan_catalog_entries WHERE game_id = ? COLLATE NOCASE",
                (game_id,),
            ).fetchone()
        if row is None:
            return None
        try:
            item = json.loads(row[1])
            media = item.get("media", {})
            image = media.get("image_url") or media.get("image")
            if not isinstance(image, str) or not image:
                return None
            root = Path(row[0]).resolve(strict=False).parent
            candidate = (root / image).resolve(strict=False)
            candidate.relative_to(root)
            return candidate if candidate.is_file() else None
        except (OSError, ValueError, TypeError, AttributeError):
            return None

    def _apply_metadata_overrides(
        self,
        game_id: str,
        payload: dict[str, Any],
        locale: str,
    ) -> None:
        metadata = self.lan_game_metadata(game_id)
        if metadata is None and self._metadata_lookup is not None:
            metadata = self._metadata_lookup(game_id)
        if metadata is None:
            metadata = self._metadata_store.get(game_id)
        if metadata is None:
            return
        title = metadata.effective_title(locale)
        readme = metadata.effective_description(locale)
        if title:
            payload["title"] = title
        if readme:
            payload["readme"] = readme
        if metadata.key:
            payload["key"] = metadata.key
        if metadata.release_year:
            payload["release_year"] = metadata.release_year
        if metadata.publisher:
            payload["publisher"] = metadata.publisher
        if metadata.size_gb is not None:
            payload["size_gb"] = metadata.size_gb
        if metadata.max_players:
            payload["max_players"] = metadata.max_players
        if metadata.master_required is not None:
            payload["master_required"] = int(metadata.master_required)
        if metadata.version:
            payload["version"] = metadata.version
            installed_version = str(payload.get("installed_version", "") or "")
            payload["needs_update"] = bool(
                payload.get("install_state") == "installed"
                and installed_version
                and installed_version != metadata.version
            )
        genre = metadata.effective_genre(locale)
        if genre:
            payload["genre"] = genre
        if metadata.genre_id is not None:
            payload["genre_id"] = metadata.genre_id
        if metadata.game_provider_type:
            payload["game_provider_type"] = metadata.game_provider_type
        payload["metadata"] = metadata.as_payload()

    def _safe_sort(self, field: str) -> str:
        mapping = {
            "title": "title",
            "size": "g.size_gb",
            "players": "CAST(g.max_players AS INTEGER)",
            # Runtime catalogs typically use YYYYMMDD-style version strings.
            # Sorting by numeric cast provides a practical "newest update first" order.
            "version": "CAST(g.version AS INTEGER)",
        }
        return mapping.get(field, "title")

    def list_games(self, query: ListQuery) -> dict[str, Any]:
        title_col = "g.title_de" if query.locale == "de" else "g.title_en"
        readme_col = "g.readme_de" if query.locale == "de" else "g.readme_en"
        sort_col = self._safe_sort(query.sort)
        order = "DESC" if query.order.lower() == "desc" else "ASC"

        filters: list[str] = ["1=1"]
        params: list[Any] = []

        if query.q:
            filters.append(f"{title_col} LIKE ?")
            params.append(f"%{query.q}%")

        if query.genre_id is not None:
            filters.append("g.genre_id = ?")
            params.append(query.genre_id)

        if query.installed in {"installed", "missing"}:
            if query.installed == "installed":
                filters.append("COALESCE(i.state, 'missing') = 'installed'")
            else:
                filters.append("COALESCE(i.state, 'missing') != 'installed'")
        elif query.installed == "updates":
            filters.append("COALESCE(i.state, 'missing') = 'installed'")
            if self._metadata_lookup is None:
                filters.append("COALESCE(i.installed_version, '') != ''")
                filters.append(
                    "COALESCE(i.installed_version, '') != COALESCE(g.version, '')"
                )
        if query.excluded_ids:
            excluded = [
                str(game_id or "").strip()
                for game_id in query.excluded_ids
                if str(game_id or "").strip()
            ]
            if excluded:
                placeholders = ",".join("?" for _ in excluded)
                filters.append(f"g.id NOT IN ({placeholders})")
                params.extend(excluded)

        if query.disabled_ids:
            disabled = [
                str(game_id or "").strip().lower()
                for game_id in query.disabled_ids
                if str(game_id or "").strip()
            ]
            if disabled:
                placeholders = ",".join("?" for _ in disabled)
                filters.append(
                    f"(LOWER(g.id) NOT IN ({placeholders}) OR COALESCE(i.state, 'missing') = 'installed')"
                )
                params.extend(disabled)

        # Keep hidden entries out of the normal catalog while allowing the UI to
        # request the dedicated hidden category explicitly.
        filters.append("COALESCE(g.hidden, 0) = ?")
        params.append(1 if str(query.visibility).strip().lower() == "hidden" else 0)

        where_clause = " AND ".join(filters)
        metadata_update_filter = (
            query.installed == "updates" and self._metadata_lookup is not None
        )
        unpaged = query.page_size <= 0 or metadata_update_filter
        offset = max(query.page - 1, 0) * query.page_size if not unpaged else 0
        games_source = """
            (
                SELECT
                    c.id,
                    c.title_en,
                    c.title_de,
                    c.key,
                    c.release_year,
                    c.publisher,
                    c.size_gb,
                    c.readme_en,
                    c.readme_de,
                    c.max_players,
                    c.master_required,
                    c.genre_id,
                    c.version,
                    c.game_provider_type,
                    c.hidden,
                    0 AS is_manual_sync
                FROM game_catalog c
                UNION ALL
                SELECT
                    e.game_id AS id,
                    e.title_en,
                    e.title_de,
                    e.game_key AS key,
                    e.release_year,
                    e.publisher,
                    e.size_gb,
                    e.readme_en,
                    e.readme_de,
                    e.max_players,
                    e.master_required,
                    NULL AS genre_id,
                    e.version,
                    e.game_provider_type,
                    e.hidden,
                    1 AS is_manual_sync
                FROM extra_sync_items e
                WHERE e.visible_in_gamelist = 1
            ) g
        """

        with self._lock:
            total = self._conn.execute(
                f"""
                SELECT COUNT(*)
                FROM {games_source}
                LEFT JOIN install_state i ON i.game_id = g.id
                WHERE {where_clause}
                """,
                params,
            ).fetchone()[0]

            base_query = f"""
                SELECT
                    g.id,
                    {title_col} AS title,
                    g.key,
                    g.release_year,
                    g.publisher,
                    g.size_gb,
                    g.max_players,
                    g.master_required,
                    g.version,
                    g.game_provider_type,
                    g.hidden,
                    COALESCE(i.state, 'missing') AS install_state,
                    COALESCE(i.installed_version, '') AS installed_version,
                    CASE
                        WHEN COALESCE(i.state, 'missing') = 'installed'
                             AND COALESCE(i.installed_version, '') != ''
                             AND COALESCE(i.installed_version, '') != COALESCE(g.version, '')
                        THEN 1
                        ELSE 0
                    END AS needs_update,
                    ge.name_en,
                    ge.name_de,
                    g.is_manual_sync,
                    {readme_col} AS readme
                FROM {games_source}
                LEFT JOIN install_state i ON i.game_id = g.id
                LEFT JOIN genres ge ON ge.id = g.genre_id
                WHERE {where_clause}
                ORDER BY {sort_col} {order}
            """
            if unpaged:
                # page_size <= 0 means the caller explicitly requests full list without LIMIT/OFFSET.
                rows = self._conn.execute(base_query, params).fetchall()
            else:
                rows = self._conn.execute(
                    f"{base_query} LIMIT ? OFFSET ?",
                    [*params, query.page_size, offset],
                ).fetchall()

        items = []
        for row in rows:
            locale = query.locale
            items.append(
                {
                    "id": row["id"],
                    "title": row["title"],
                    "key": row["key"],
                    "release_year": row["release_year"],
                    "publisher": row["publisher"],
                    "size_gb": row["size_gb"],
                    "max_players": row["max_players"],
                    "master_required": row["master_required"],
                    "version": row["version"],
                    "game_provider_type": str(row["game_provider_type"] or ""),
                    "hidden": bool(row["hidden"]),
                    "install_state": row["install_state"],
                    "installed_version": row["installed_version"],
                    "needs_update": bool(row["needs_update"]),
                    "genre": (
                        row["name_de"] if query.locale == "de" else row["name_en"]
                    )
                    or ("Manueller Sync" if query.locale == "de" else "Manual Sync"),
                    "is_manual_sync": bool(row["is_manual_sync"]),
                    "readme": row["readme"],
                }
            )
            self._apply_metadata_overrides(str(row["id"] or ""), items[-1], locale)

        if metadata_update_filter:
            items = [item for item in items if item.get("needs_update")]
            total = len(items)
            offset = max(query.page - 1, 0) * query.page_size if query.page_size > 0 else 0
            if query.page_size > 0:
                items = items[offset : offset + query.page_size]

        return {
            "items": items,
            "page": query.page,
            "page_size": query.page_size,
            "total": total,
        }

    def list_genres(self, locale: str = "en") -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT id, name_en, name_de
                FROM genres
                ORDER BY CASE WHEN ? = 'de' THEN name_de ELSE name_en END COLLATE NOCASE ASC
                """,
                (locale,),
            ).fetchall()
        return [
            {
                "id": int(row["id"]),
                "name": str(row["name_de"] if locale == "de" else row["name_en"] or ""),
            }
            for row in rows
        ]

    def get_game(self, game_id: str, locale: str = "en") -> dict[str, Any] | None:
        title_col = "g.title_de" if locale == "de" else "g.title_en"
        readme_col = "g.readme_de" if locale == "de" else "g.readme_en"

        with self._lock:
            row = self._conn.execute(
                f"""
                SELECT
                    g.id,
                    {title_col} AS title,
                    g.key,
                    g.release_year,
                    g.publisher,
                    g.size_gb,
                    {readme_col} AS readme,
                    g.max_players,
                    g.master_required,
                    g.genre_id,
                    g.game_provider_type,
                    g.hidden,
                    g.version,
                    COALESCE(i.state, 'missing') AS install_state,
                    COALESCE(i.installed_version, '') AS installed_version,
                    CASE
                        WHEN COALESCE(i.state, 'missing') = 'installed'
                             AND COALESCE(i.installed_version, '') != ''
                             AND COALESCE(i.installed_version, '') != COALESCE(g.version, '')
                        THEN 1
                        ELSE 0
                    END AS needs_update,
                    ge.name_en,
                    ge.name_de
                FROM game_catalog g
                LEFT JOIN install_state i ON i.game_id = g.id
                LEFT JOIN genres ge ON ge.id = g.genre_id
                WHERE g.id = ?
                """,
                (game_id,),
            ).fetchone()

        if row is None:
            extra_title_col = "e.title_de" if locale == "de" else "e.title_en"
            extra_readme_col = "e.readme_de" if locale == "de" else "e.readme_en"
            with self._lock:
                row = self._conn.execute(
                    f"""
                    SELECT
                        e.game_id AS id,
                        {extra_title_col} AS title,
                        e.game_key AS key,
                        e.release_year,
                        e.publisher,
                        e.size_gb,
                        {extra_readme_col} AS readme,
                    e.max_players,
                    e.master_required,
                        e.game_provider_type,
                        e.hidden,
                    e.version,
                        COALESCE(i.state, 'missing') AS install_state,
                        COALESCE(i.installed_version, '') AS installed_version,
                        CASE
                            WHEN COALESCE(i.state, 'missing') = 'installed'
                                 AND COALESCE(i.installed_version, '') != ''
                                 AND COALESCE(i.installed_version, '') != COALESCE(e.version, '')
                            THEN 1
                            ELSE 0
                        END AS needs_update
                    FROM extra_sync_items e
                    LEFT JOIN install_state i ON i.game_id = e.game_id
                    WHERE e.game_id = ?
                    """,
                    (game_id,),
                ).fetchone()
            if row is None:
                return None
            payload = {
                "id": row["id"],
                "title": row["title"],
                "key": row["key"],
                "release_year": row["release_year"],
                "publisher": row["publisher"],
                "size_gb": row["size_gb"],
                "readme": row["readme"],
                "max_players": row["max_players"],
                "master_required": row["master_required"],
                "game_provider_type": str(row["game_provider_type"] or ""),
                "hidden": bool(row["hidden"]),
                "version": row["version"],
                "install_state": row["install_state"],
                "installed_version": row["installed_version"],
                "needs_update": bool(row["needs_update"]),
                "genre": "Manueller Sync" if locale == "de" else "Manual Sync",
            }
            self._apply_metadata_overrides(str(row["id"]), payload, locale)
            return payload
        payload = {
            "id": row["id"],
            "title": row["title"],
            "key": row["key"],
            "release_year": row["release_year"],
            "publisher": row["publisher"],
            "size_gb": row["size_gb"],
            "readme": row["readme"],
            "max_players": row["max_players"],
            "master_required": row["master_required"],
            "genre_id": row["genre_id"],
            "game_provider_type": str(row["game_provider_type"] or ""),
            "hidden": bool(row["hidden"]),
            "version": row["version"],
            "install_state": row["install_state"],
            "installed_version": row["installed_version"],
            "needs_update": bool(row["needs_update"]),
            "genre": row["name_de"] if locale == "de" else row["name_en"],
        }
        self._apply_metadata_overrides(str(row["id"]), payload, locale)
        return payload

    def set_install_state(
        self, game_id: str, state: str, installed_version: str = ""
    ) -> None:
        with self._lock:
            with self._conn:
                self._conn.execute(
                    """
                    INSERT INTO install_state(game_id, state, installed_version, updated_at)
                    VALUES (?, ?, ?, datetime('now'))
                    ON CONFLICT(game_id) DO UPDATE SET
                        state = excluded.state,
                        installed_version = excluded.installed_version,
                        updated_at = excluded.updated_at
                    """,
                    (game_id, state, str(installed_version or "")),
                )

    def current_install_state(self, game_id: str) -> str:
        with self._lock:
            row = self._conn.execute(
                "SELECT state FROM install_state WHERE game_id = ?",
                (game_id,),
            ).fetchone()
        if row is None:
            return "missing"
        return str(row["state"] or "missing")

    def resolve_catalog_game_id(self, game_id: str) -> str | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT id FROM game_catalog WHERE id = ? COLLATE NOCASE LIMIT 1",
                (game_id,),
            ).fetchone()
        if row is None:
            return None
        return str(row["id"] if isinstance(row, sqlite3.Row) else row[0] or "").strip()

    def remove_catalog_game(self, game_id: str) -> int:
        canonical_game_id = self.resolve_catalog_game_id(game_id)
        if not canonical_game_id:
            return 0
        with self._lock:
            with self._conn:
                # Remove auxiliary state rows first so stale install/runtime data cannot
                # survive when a provider explicitly discards a game id.
                self._conn.execute(
                    "DELETE FROM install_state WHERE game_id = ?",
                    (canonical_game_id,),
                )
                self._conn.execute(
                    "DELETE FROM sync_state WHERE game_id = ?",
                    (canonical_game_id,),
                )
                self._conn.execute(
                    "DELETE FROM game_launch_settings WHERE game_id = ?",
                    (canonical_game_id,),
                )
                self._conn.execute(
                    "DELETE FROM games WHERE id = ?", (canonical_game_id,)
                )
                deleted = self._conn.execute(
                    "DELETE FROM game_catalog WHERE id = ?",
                    (canonical_game_id,),
                ).rowcount
        return int(deleted)

    def set_game_hidden(self, game_id: str, hidden: bool) -> bool:
        """Persist catalog visibility without touching installed game data."""
        normalized = str(game_id or "").strip()
        if not normalized:
            return False
        with self._lock:
            with self._conn:
                cursor = self._conn.execute(
                    "UPDATE game_catalog SET hidden = ? WHERE id = ? COLLATE NOCASE",
                    (1 if hidden else 0, normalized),
                )
                if cursor.rowcount:
                    return True
                cursor = self._conn.execute(
                    "UPDATE extra_sync_items SET hidden = ? WHERE game_id = ? COLLATE NOCASE",
                    (1 if hidden else 0, normalized),
                )
                return bool(cursor.rowcount)

    def list_game_ids(self) -> list[str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id FROM game_catalog ORDER BY id"
            ).fetchall()
        return [str(row[0]) for row in rows]

    def list_game_provider_types(self) -> set[str]:
        """Return non-local providers currently referenced by catalog records."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT game_provider_type FROM game_catalog "
                "UNION SELECT game_provider_type FROM extra_sync_items"
            ).fetchall()
        return {
            str(row[0] or "").strip().lower()
            for row in rows
            if str(row[0] or "").strip().lower() not in {"", "local"}
        }

    def list_sync_targets(self) -> list[dict[str, str]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT id, key, title_en
                FROM game_catalog
                WHERE COALESCE(game_provider_type, '') != 'local'
                ORDER BY id
                """
            ).fetchall()
        targets: list[dict[str, str]] = []
        for row in rows:
            targets.append(
                {
                    "id": str(row["id"] or ""),
                    "key": str(row["key"] or ""),
                    "title": str(row["title_en"] or row["id"] or ""),
                }
            )
        return targets
