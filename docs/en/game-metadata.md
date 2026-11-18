# Game Metadata

LAN entries use their locally stored index metadata for game details, links, installer tasks and launch scripts and arguments even when the server is offline. The LAN folder ID remains the sync key and cannot be replaced by a metadata key.

The server-generated index includes `generated_at_utc` as required by the Open Source Game Index schema. The timestamp changes only when the published snapshot changes; older LAN indexes without it remain readable and are upgraded on publication.

The public OpenSourceGameIndex v1 format remains supported for catalog compatibility, but unsigned v1 data cannot authorize Ouisync repositories. Version 2 preserves existing game fields and adds a required monotonic `index_revision` and signature. Each Ouisync game supplies its read token, expected repository info hash, editable-file list, archive SHA-256, and archive version-file path in its own `metadata.json`; the generator copies these values into the signed index. Its `version` field drives update notices even while local game metadata is stale. LLNG keeps tokens out of ordinary catalog responses and uses them only after both index and root-signed publisher registry verification. Increase `index_revision` for each publication; clients reject rollbacks and different content reusing a revision. The registry and catalog signature contract is defined in [ADR-0002](../shared/adr/ADR-0002.md).

The synchronized catalog directory contains `trusted-publishers.json` beside `index.json`. Verified copies are cached with the index under the launcher's local data directory. LLNG records the highest accepted registry sequence/digest and index revision/digest there; older versions or different content at the same version are rejected. A revoked signer stops authorizing indexes once the newer root-signed registry is received. Builds without a provisioned catalog root key reject v2 indexes and fail closed; the catalog root is separate from the update keys and must be embedded in a launcher release before publishing signed catalogs.

When a user selects an Ouisync game, LLNG obtains its read-only token only from the verified signed index. It stores the per-game repository at `<library>/<game_id>/.ouisync/<game_id>` by default, or under the optional Ouisync storage root. LLNG checks the repository info hash against signed `expected_info_hash`, verifies the archive SHA-256, then reads the declared `version.ini` inside that archive and compares it with the signed index version before extraction. An index version change shows an update for installed games; automatic extraction waits for Ouisync materialization to reach 100%. LLNG extracts directly into writable `local/`, copies metadata, referenced media, launch files, and signed `editable_files` needed after unmount, and then unmounts. The archive is not copied into a second tree. Removing repository data frees the local synced copy while keeping the extracted game installed.

Example LLNG extension (use a publisher-issued read-only token):

```json
{
  "schema_version": 2,
  "index_revision": 1,
  "games": [{
    "game_id": "example-game",
    "title": "Example Game",
    "version": "1.2.0",
    "game_provider_type": "ouisync",
    "runner": "proton",
    "installer_tasks": [{"name": "protontricks", "args": "vcrun2019"}],
    "distribution": {
      "schema_version": 1,
      "archive": {
        "file": "example-game.tar.gz",
        "format": "tar.gz",
        "sha256": "<64-hex-archive-checksum>",
        "version_file": "version.ini"
      }
    },
    "llng": {
      "schema_version": 1,
      "distribution": {
        "provider": "ouisync",
        "read_token": "<read-only-token>",
        "info_hash": "<expected-repository-hash>",
        "editable_files": ["settings.ini"]
      }
    }
  }],
  "signature": {
    "key_id": "publisher-key-id",
    "value": "<base64-rsa-sha256-signature>"
  }
}
```

The signature value above is a placeholder. Publishers sign the canonical index with the private key that matches the active key ID in `trusted-publishers.json`.

The machine-readable LLNG-compatible v2 schema is `schemas/opensourcegameindex-v2.schema.json`; the separate trust registry format is `schemas/opensourcegameindex-trust-v1.schema.json`. LLNG continues to accept v1 indexes; unsupported top-level schema versions are rejected and the last validated offline snapshot is retained.

Public Game Index entries accept `media.image_url` and `media.video_url`, as well as the existing `media.image` and `media.video` aliases.

The LAN index uses the same `schema_version`, `source`, and `games` structure. Its version 1 snapshots identify a source with `source.id` and `source.folder_id`, and each game has a `game_id`, title, and an LLNG Ouisync distribution capability. Cover references in `media.image_url` or `media.image` must be relative local JPEG, PNG, or WebP paths inside the catalog. Server mode generates `<library>/locallansync/.ouisync/index.json` for explicitly shared folders containing root `metadata.json`, `.ouisync/metadata.json`, or a legacy per-game sidecar, copying local covers into the catalog. LLNG imports a valid index on startup and when it changes, preserving unrelated catalog entries and installed games after unsharing. Incomplete downloads disappear from the list, and clients pause folders for removed shares without deleting files; installed entries remain playable but cannot resume syncing until the share returns. If the index is missing or invalid, the existing catalog is retained. In the server metadata editor, a public HTTP(S) image URL can be downloaded and converted to a local JPEG before saving. Images are limited to 8 MiB and resized to a maximum edge of 1600 pixels; redirects are bounded and private network addresses are rejected. The selected local file takes precedence over a downloaded cover.

In server settings, use **Create metadata** or **Edit metadata** on a game folder. Sharing a folder without metadata opens the form first. The form writes `metadata.json` in the game root and preserves other existing metadata fields; it no longer creates a per-game `metadata/` subfolder. A JPEG, PNG, or WebP cover can be selected locally; it is copied to the LAN catalog when the folder is shared.

When adding a local game or sharing a folder, LLNG checks the game ID without regard to letter case against the local catalog, LAN index and available official provider databases. A duplicate is rejected with an error; an existing local game can still be edited. If an index or provider database cannot be read, the check fails instead of permitting a potentially conflicting entry.

## Why metadata files exist

Portable game metadata can live at `<library>/<game_id>/metadata.json` or, for Ouisync materialized content, `<library>/<game_id>/.ouisync/metadata.json`. It can carry OpenSourceGameIndex fields plus LLNG distribution details. Media and archive paths are relative to the directory containing the metadata file. Metadata, images, videos, and the archive stay in their source directory; LLNG reads media there and extracts the archive directly from there into writable `local/`. The older per-game `metadata/<game_id>.json` layout remains a read-only compatibility fallback.

The launcher reads:
- `<library>/<game_id>/metadata.json` or `<library>/<game_id>/.ouisync/metadata.json` for portable game metadata and distribution fields.
- `metadata/<game_id>.json` for older catalog overrides.
- `metadata/<game_id>.jpg` / `metadata/<game_id>.mp4` as legacy media fallbacks.

Each JSON file is optional. When no file exists, existing DB values remain unchanged.

## JSON format

The machine-readable contract is `schemas/game-metadata-v1.schema.json` in the source repository and uses JSON Schema Draft 2020-12. Apply it to either portable metadata location. It leaves unknown OpenSourceGameIndex fields available for forward compatibility. LLNG also checks paths at runtime: launch files and local media must stay below their metadata/game directory, and archives must use a supported relative `.eti`, `.rar`, or `.tar.gz` path. LLNG does not need a JSON Schema package at runtime.

Minimal fields:

- `title` (string or locale map)
- `description` (locale map with `de`, `en`, and `fr`; legacy strings remain readable)
- catalog-equivalent fields (optional overrides):
  - `key`
  - `release_year`
  - `publisher`
  - `size_gb`
  - `max_players`
  - `master_required`
  - `version`
  - `genre` (string or locale map)
  - `genre_id`
- `lan_supported` (`true` for LAN-capable games that LLNG should care about)
- `runner` (`wine`, `proton`, `proton-ge`, `native`, `auto`, `windows`, or empty)
- `image` and `video` (optional relative paths)
- `website_url`, `community_url`, `discord_url`, `download_url`, `page_url`
- `links` (list of link objects for launcher and GitHub Pages navigation)
- `game_start.file` and `game_start.args`
- `installer_tasks` or `installer` (list of task objects)
- `distribution.schema_version` (`1`) and `distribution.archive` (`file`, optional `format`, optional SHA-256)

Locale maps support either:
- `{"de": "...", "en": "...", "fr": "..."}`. For descriptions, LLNG selects the requested language and falls back to English; legacy strings remain readable.

The OpenSourceGameIndex publisher format also carries `size_gb`, `master_required`, and the optional `game_start.file`/`game_start.args` override. These fields pass through the signed index and are consumed by LLNG where applicable. The normal `game_start.cmd`/`game_start.sh` discovery remains the default.

### Example

```json
{
  "title": {
    "en": "1nsane",
    "de": "1nsane"
  },
  "description": "Add game specific launch and dependency notes here.",
  "key": "1NSANE_GOG",
  "release_year": "2000",
  "publisher": "Codemasters",
  "size_gb": 1.45,
  "max_players": "8",
  "master_required": false,
  "version": "2000-gog",
  "genre": {
    "en": "Racing",
    "de": "Rennspiel"
  },
  "genre_id": 4,
  "lan_supported": true,
  "runner": "wine",
  "website_url": "https://example.org/game",
  "community_url": "https://example.org/forum",
  "discord_url": "https://example.org/discord",
  "download_url": "https://example.org/download",
  "image": "1nsane.jpg",
  "video": "1nsane.mp4",
  "links": [
    {
      "label": {
        "en": "Project website",
        "de": "Projekt-Website"
      },
      "url": "https://example.org/game"
    }
  ],
  "game_start": {
    "file": "game_start.cmd",
    "args": []
  },
  "distribution": {
    "schema_version": 1,
    "archive": {
      "file": "1nsane.tar.gz",
      "format": "tar.gz",
      "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
    }
  },
  "installer_tasks": [
    {
      "app": "directplay",
      "name": "winetricks",
      "args": "/sp- /norestart /suppressmsgboxes /nogui"
    }
  ]
}
```

## Merge behavior

- `title` and `description` values override catalog values in both list and detail payloads.
- The entire metadata payload is also returned as `metadata` in API responses.
- `game_start` and `installer_tasks` are consumed by runtime lifecycle logic.

## Runtime behavior

- `game_start.file` overrides default `game_start.cmd` for game launch (not server launch). Only safe relative paths inside the game folder are accepted.
- `game_start.args` are appended to the legacy launch arguments (`game_path`, `game_id`, `game_lang`, `player`).
- `distribution.archive.file` is a safe relative path inside the game folder. Supported formats are `.tar.gz`, `.rar`, and legacy `.eti` RAR archives. Without this field, LLNG looks for `<game_id>.eti`, `<game_id>.rar`, then `<game_id>.tar.gz`.
- If `distribution.archive.sha256` is present, LLNG verifies it before running install tasks or extracting the archive. A mismatch stops installation.
- `.tar.gz` extraction rejects absolute paths, parent traversal, symbolic links, and special file types before copying files into `local/`. Hard links (GNU tar writes them for files sharing an inode, for example in Linux AppDirs) are accepted only when they point to a regular file earlier in the same archive; LLNG writes them as independent copies. Of the stored permissions only the owner executable bit is kept (`0755`, otherwise `0644`); setuid, setgid, and world-writable bits are dropped. The archive root becomes `local/`: an archive whose entries start with `local/` would be extracted to `local/local/` and must be repacked so `local/`'s contents are at the archive root. `.rar` and `.eti` use UnRAR; Windows uses the bundled executable and Linux currently requires `unrar` on `PATH`.
- Use the existing `game_start.cmd` and `game_start.sh` convention for platform-specific launchers. No extra platform-binary map is required; `game_start.file` remains an optional single-file override.
- Placeholders in `game_start.args` are expanded: `$GAMEDIR`, `${GAMEDIR}`, `%GAMEDIR%` (and `GAME_DIR`/`GAME_PATH` variants).
- On Linux, `runner` is used as runtime hint for CMD launchers:
  - `wine`, `proton`, `proton-ge`, `native`, `windows`, `auto`.
  - Per-game launch override from launcher settings still has higher precedence.
- `installer_tasks` currently supports `winetricks`/`protontricks` tasks during install/update on Linux.
  - Each task must set `name` or `action` to one of those values and provide package names through `app` or non-option values in `args`.
  - Unknown task names are skipped safely with console diagnostics.
  - On Windows, installer tasks are ignored.

Before distributing game folders, run `python tools/scripts/lint_game_metadata.py <game-root>`. It scans `metadata.json` and `.ouisync/metadata.json`, rejects malformed task objects, unsupported action names, missing package names, and folder-ID mismatches. Both application package builders run the same check on repository `library/` and `ng_provider/` directories when present. Add any separately staged game roots to the command when preparing a content release.

## Migration guidance

For existing Lutris/Bottles style notes, map fields like this:

- `name` -> `title.en` / `title.de`
- `notes` -> `description.en` / `description.de`
- `runner` -> `runner`
- `lan_supported` -> marks whether the game has a LAN mode and should be relevant for LLNG
- `max_players` -> number of players supported by the LAN mode
- `website_url`, `community_url`, `discord_url`, `download_url`, `page_url` -> launcher-visible links
- `links[]` -> custom link entries rendered in launcher detail view and generated public pages
- `game.exe` or launcher entry -> `game_start.file`
- launch args -> `game_start.args`
- winetricks/protontricks actions -> `installer_tasks[]`
- media assets -> `image` / `video` (or `metadata/<game_id>.jpg|mp4` fallback files)

Media path rule:
- Use paths relative to the metadata root (for example `1nsane.jpg`, `media/1nsane.mp4`).
- Do not prefix with `metadata/` in the JSON value.
