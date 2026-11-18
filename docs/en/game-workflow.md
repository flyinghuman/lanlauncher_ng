# Game workflow reference

This page records the game-folder and launch contract for maintainers and people preparing game content. For player instructions, see [Using LANLauncherNG](using-lanlauncher.md).

## Library layout

Game folders are stored below the configured library root, normally as `<library>/<game_id>`. The folder ID is the catalog/provider key and should remain stable. Do not rename a synced folder without updating its catalog entry and provider configuration.

Each distributed game can include `<library>/<game_id>/metadata.json` or `<library>/<game_id>/.ouisync/metadata.json`. Their portable field and path contract is defined in [`game-metadata.md`](game-metadata.md#json-format) and the source schema `schemas/game-metadata-v1.schema.json`. `distribution.archive` may name a `.rar`, `.tar.gz`, or legacy `.eti` archive and its SHA-256 checksum. Media and archive paths are relative to the metadata file. Ouisync content is temporarily mounted for installation/update: the archive is read from the mount and extracted into writable `local/`; metadata and non-archive assets needed afterward are copied into the game folder, along with launch files. A configurable Ouisync storage root can place each game's repository on a separate disk. Changing the root leaves existing repositories where they are and reuses them there; new repositories use the selected root. Removing local Ouisync data leaves the extracted game installed. LAN shares use one repository per selected game folder, including local-only folders that are not in the global LLNG database. LLNG copies shareable files from the game folder through a temporary writable mount, skips `local/` entirely, and flattens files from `.ouisync` into the repository root. When the same relative path exists in both places, `.ouisync` takes precedence. The server publishes a read-only key in the LAN catalog and unmounts the repository after copying. The private catalog snapshot is stored in `<library>/locallansync/.ouisync/index.json`. Local-only catalog entries are separate: their catalog record is stored in the LLNG database and their editable metadata is stored below the library's top-level `metadata/` directory. Local-only entries are not LAN-shared automatically; a folder can still be explicitly selected for a LAN share.

## Install and update lifecycle

LLNG waits for synchronization to finish and for the configured archive to be available, then extracts it into `local/`. Without an explicit archive path it checks `<game_id>.eti`, `<game_id>.rar`, and `<game_id>.tar.gz` in that order. A configured SHA-256 is checked before extraction. Ouisync metadata can also declare the `version.ini` path inside the archive; LLNG compares that version with the signed index target before extracting. An index version change marks an installed game for update, and automatic extraction waits until Ouisync materialization reaches 100%. `.tar.gz` entries are validated against path traversal, links, and special files. If present, `game_setup.cmd` or `game_setup.sh` runs after extraction. A completed installation normally includes a `local/` directory; `version.ini` supplies the installed version when available.

LAN game folders are synchronized on demand. LLNG waits for the repository snapshot, mounts it only while installing/updating, then unmounts it. **Sync archives only** leaves extraction to an explicit **Install Anyway** action.

Uninstall removes the installed `local/` tree and launcher helper scripts while retaining the synchronized payload and archive by default. LAN unsharing or catalog removal does not delete client files. Incomplete downloads are removed from the visible catalog state; installed copies are retained and cannot sync again until the share returns.

## Launch contract

The default client entry point is `game_start.cmd` on Windows and `game_start.sh` on Linux. A separate `server_start.cmd` or `server_start.sh` may be used for the **Start Server** action. A metadata `game_start.file` overrides the client entry point; `game_start.args` are appended to the legacy arguments:

1. game folder path
2. game ID
3. selected language
4. player name

Arguments may use `$GAMEDIR`, `${GAMEDIR}`, `%GAMEDIR%`, `GAME_DIR`, or `GAME_PATH` placeholders. Only safe relative launch-file paths within the game folder are accepted.

On Linux, native shell scripts are preferred. Windows `.cmd` launchers use the selected compatibility runtime (`wine`, `proton`, or `proton-ge`) when configured; the global runtime can be overridden per game. Proton prefixes are isolated under `<library>/<game_id>/.compatdata/`.

For metadata fields and installer tasks, see [Game Metadata](game-metadata.md). For the local HTTP API, see [Core Service](core-service.md).
