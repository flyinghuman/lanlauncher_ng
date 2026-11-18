# Legacy Assets and Install Logic

This page applies to the legacy Resilio flow only. Ouisync uses the bundled binary and `ouisync_*` config keys instead.

## Integrated legacy payloads
- Legacy game artwork copied to `src/frontend/assets/games` and included in packages.
- Legacy game catalog DB copied to `data/legacy/game.db` in packaged builds.
- Resilio Sync is not bundled. Provide your own local installation and point the launcher at it.
- Ouisync is bundled with LANLauncherNG and does not need a separate local install.
- Default local drop-in paths are gitignored on purpose:
  - `vendor/bin/windows-amd64/btsync.exe`
  - `vendor/bin/linux-x64/rslsync`
  - `vendor/licenses/resilio/llng.btskey`
- Installers look for these filenames next to the setup package or install script and copy them into the correct locations automatically:
  - `btsync.exe` on Windows
  - `rslsync` on Linux
  - `llng.btskey` on both platforms
  - `bootstrap.json` for custom provider presets
    - seed entries may declare `game_provider_type: resilio|ouisync`
- Windows note: if Resilio provides a setup executable, rename the downloaded file to `btsync.exe` before placing it next to the LANLauncherNG installer.
- If you prefer a different location, set `sync_binary_path` and `sync_license_key_path` in `config/core.json` or via `LLNG_SYNC_BINARY_PATH` and `LLNG_SYNC_LICENSE_KEY_PATH`.
- Resilio config remains local-only:
  - `config/resilio/config.json`
  - `config/resilio/config.yml`

## Install/start scripts
- Installation is handled by launcher logic:
  - retain `<game_id>.eti` for legacy Resilio content; new game packages may use `.rar` or `.tar.gz` and declare the archive in the game's `metadata.json`.
  - `.rar` and `.eti` are extracted with UnRAR. Windows uses the bundled `unrar.exe`; Linux currently expects `unrar` on `PATH`. `.tar.gz` uses the Python standard library.
- Start scripts remain game-local legacy scripts:
  - `<library>/<game_id>/game_start.cmd`
  - `<library>/<game_id>/server_start.cmd`
- Linux compatibility wrapper:
  - `scripts/wrappers/linux/run-cmd-wrapper.sh`
  - used only when no `game_start.sh`/`server_start.sh` exists.

## Installed-game detection
- Base check: game folder exists under configured library path.
- Optional per-game marker checks from `config/install/checks.json`.
- If markers are defined for a game, at least one marker file must exist inside that game's folder.

## API support
- Install script lookup endpoint:
  - `GET /catalog/games/{id}/install-script`
