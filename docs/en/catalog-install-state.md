# Catalog and install state

The catalog service combines game records from the configured providers with LLNG-owned state in SQLite. Catalog metadata describes a game; install state is scanned from the local library and records whether its files are missing, downloading, installing, or installed. Provider ownership determines where sync actions are sent.

## Catalog ownership

- Official provider entries are imported from provider catalogs and keep their provider identity.
- LAN entries are imported from the validated `locallansync/.ouisync/index.json` snapshot. They retain their LAN ownership even when the server is unavailable.
- Local-only entries are created in the launcher and are not synchronized. Their game folders and metadata are not removed when the catalog record is deleted.

LLNG checks a new game ID against the local catalog, the LAN snapshot, and available official provider databases. IDs are compared without regard to case. If a source cannot be checked, creation is rejected rather than risking a duplicate.

## API

- `GET /catalog/games` returns visible entries and supports `locale`, `q`, `genre_id`, `installed`, `sort`, `order`, `page`, and `page_size`.
- `GET /catalog/games/{id}` returns details and metadata for one entry.
- `GET /catalog/games/{id}/sync-status` reports provider and installation progress.
- `GET /catalog/genres?locale=en|de` returns available genres.
- `GET /catalog/games?visibility=hidden` returns hidden entries; the default list excludes them.
- Hiding a game that comes from the signed Ouisync index is persistent: periodic index refreshes update its metadata but keep the hidden flag.
- `POST /catalog/games/{id}/visibility` updates visibility without changing game files.
- `GET /catalog/rescan?force=true|false` refreshes install-state data.

Install state is persisted locally and refreshed from the filesystem. A missing or invalid LAN snapshot does not erase the last valid LAN catalog. Unsharing a game removes an incomplete download from the active catalog state; installed data is retained.
