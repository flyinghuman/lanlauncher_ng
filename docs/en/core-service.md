# Core service

The Python service coordinates the catalog, sync providers, game lifecycle, platform adapters, and local HTTP API. Configuration is loaded from JSON with environment overrides. SQLite migrations run during normal startup or can be invoked on their own. Logs use structured records and rotate at 10 MB.

## Development commands

Start the service:

```bash
./.venv/bin/python -m src.core.main --config config/core.json
```

Run or inspect database maintenance without starting the UI/API service:

```bash
./.venv/bin/python -m src.core.main --config config/core.json --migrate-db
./.venv/bin/python -m src.core.main --config config/core.json --list-db-backups
./.venv/bin/python -m src.core.main --config config/core.json --rollback-db
```

Migration mode creates a timestamped backup. Automatic rollback chooses the newest backup whose schema is compatible with the target schema; `--rollback-source <path>` selects a specific backup. Use the project test instructions in [Development Workflow](development.md).

## Configuration and data

`config/core.json` is the main configuration source. Supported environment overrides are documented beside each setting in configuration and the related feature reference. The runtime database lives under `data/` and is migrated on startup. Default manual sync entries come from `config/bootstrap.json`; `default_extra_sync_items_path` or `LLNG_DEFAULT_EXTRA_SYNC_ITEMS_PATH` can select another source.

The public game catalog prefers `<library>/ng_provider/update/index.json`, so it can be synchronized and used offline without an internet request. Relative image and video paths resolve inside that provider tree. The service checks the index file every five minutes, alongside provider `game.db` updates configured through legacy provider rows. It compares file metadata around each read, retries transient read or sharing failures, and keeps the last valid index while Ouisync is replacing the file. Cache writes use atomic replacement; unsupported schema versions are ignored. Signed v2 index versions override stale local Ouisync metadata for update detection and per-game runner recommendations. Installed games show an update when the signed version changes; automatic extraction waits for Ouisync materialization to reach 100% and checks the archive checksum and embedded version file. Removing a game from a valid signed index marks it for retirement; LLNG removes its catalog state after its local installation is gone, so the NG provider does not need a `game.db` removal table. ETI and other legacy providers may continue importing their own `game.db`. `game_index_url` remains an optional legacy source used only when the local provider index is absent. Configure `game_index_cache_path`, `game_index_request_timeout_seconds`, and `game_index_refresh_seconds` for cache and legacy refresh behavior.

Membership from a valid local index is recorded in the database for Ouisync games. If an entry disappears from the index, LLNG keeps its catalog record while its local installation is still present. After uninstall, or when install state is no longer `installing` and the extracted `local/` directory is gone, LLNG removes the catalog record and its related state. The pending removal survives restarts. Invalid or cache-only index data cannot create new pending removals, though an already pending removal can finish after uninstall.

The service can import provider `game.db` data. An optional `discarded(game_id, game_key)` table requests removal of matching local catalog/runtime records and game data. A row is ignored when its game ID is not present in the local catalog; treat this input as destructive administrative data.

## HTTP/API boundaries

The local control API exposes health and version information, settings, catalog, provider status, logs, and lifecycle actions. It binds to loopback and is not a remote administration interface. LAN discovery and pairing use a separate bounded IPv4 UDP flow.

`GET /sync/speed` returns provider throughput and best-effort local disk activity. A `game_id` query selects the provider for that game; without it, throughput is aggregated. On Linux, disk activity is sampled from the block device behind the library where possible, with process I/O counters as fallback.

## Update and recovery contract

On shutdown, the service checks `<effective_library_path>/ng_provider/update/update-manifest.json` unless the path is overridden by `update_manifest_path` or `LLNG_UPDATE_MANIFEST_PATH`. A newer release is applied only after its manifest signature and payload SHA-256 pass validation. Trusted public keys are embedded in the application.

The manifest describes the payload path and checksum, install mode (`noop` or `directory_swap`), target path, preserved paths, and an optional post-install file check. Update wrappers are platform-specific:

- Windows: `scripts/wrappers/windows/llng-updater.ps1`
- Linux: `scripts/wrappers/linux/llng-updater.sh`

The updater stages the payload, saves a restorable previous version, swaps the target, restores preserved paths (by default `data`), and rolls back when the swap or optional health check fails. Protected targets may request Windows UAC or Linux `pkexec`/`sudo` privileges. Update journals and the retained backup are kept under `data/update/`.

The API flow is `prepare` → `apply` → poll `status` → user confirmation through `finalize`. If startup detects an interrupted swap, the caller must explicitly resume or abort recovery. `/app/update/rollback` restores the latest valid retained backup when available. The update manifest and wrappers can be overridden with `LLNG_UPDATE_MANIFEST_PATH`, `LLNG_WINDOWS_UPDATER_SCRIPT_PATH`, and `LLNG_LINUX_UPDATER_SCRIPT_PATH`.

Feature flags are loaded from `feature_flags_path` / `LLNG_FEATURE_FLAGS_PATH`; `LLNG_FF_<FLAG_KEY>` overrides an individual flag. `GET /app/flags` returns resolved values and definitions.
