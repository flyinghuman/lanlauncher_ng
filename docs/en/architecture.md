# Architecture (English)

## High-level components
- `src/core`: backend core service
- `src/frontend`: modern UI
- `tools`: scripts and tool manifests
- `vendor`: bundled binaries and licenses
- `packaging`: platform packaging scripts

## Backend modules
- `catalog`: game and tool metadata APIs
- `sync`: provider abstraction + concrete adapters
- `launcher`: install/start/repair/uninstall orchestration
- `platform`: Windows/Linux OS integrations
- `api`: HTTP/WebSocket endpoints

## Dependency strategy
- Prefer stdlib and low-footprint libraries.
- New heavy dependencies require an ADR.
- The global Ouisync provider uses the bundled Ouisync CLI as an isolated child process. LLNG controls it through Ouisync's upstream pure-Python session binding over the authenticated loopback socket. The binding uses MessagePack, which the Python standard library does not provide; its small pure-Python fallback and the session package are bundled under `vendor/python` so clients need no Internet access or package installation. During install/update, LLNG temporarily mounts the selected repository, verifies its signed repository identity, extracts its archive, copies files needed after unmount, and always unmounts afterward. The Linux CLI uses FUSE and requires glibc 2.39 or newer plus access to `/dev/fuse`. Windows uses the VFS-enabled MSVC CLI, bundled Dokan and `VCRUNTIME140.dll`, and a pinned upstream Dokany MSI; the installer offers the signed kernel driver as a checked-by-default task that requires administrator approval and remains installed after temporary mounts end. Private LAN publishing uses a separate per-game repository and accepts local-only game folders. It copies shareable game-folder files through a temporary writable mount, excludes `local/`, flattens `.ouisync` content into the repository root, then publishes the repository's read-only key in the local catalog. Storage-root changes preserve existing repositories at their prior paths and apply the new path to new repositories. See [ADR-0003](../shared/adr/ADR-0003.md). Ouisync, Dokan, MessagePack, Microsoft runtime, and CLI dependency license notices ship under `vendor/licenses`. The CLI is upstream v0.10.2 with one LLNG patch to the MPL-2.0 store code (reused leaf nodes are saved as present); the patch ships as `vendor/licenses/ouisync/LLNG-MODIFICATIONS.patch`.
- The upstream `ouisync.service` Python binding was evaluated and is not used: it requires Python 3.11+, embeds native Rust through `ctypes`, and would remove process crash isolation without adding a capability LLNG needs. It also requires target-specific native artifacts and Linux ABI validation. Keep the already-bundled CLI plus `ouisync.session` unless a concrete capability justifies that tradeoff.

## Offline helper tools
- Linux Wine helper assets can be staged in the synced provider tree under `<library>/ng_provider/tools/`.
- `winetricks` is consumed directly from `<library>/ng_provider/tools/winetricks/winetricks` when present, with shared cache data under `<library>/ng_provider/tools/winetricks/cache`.
- `protontricks` offline installers can be distributed alongside it under `<library>/ng_provider/tools/protontricks/` for air-gapped client setup.
- Launcher-managed game prefixes for `wine`, `proton`, and `proton-ge` live under `<library>/<game_id>/.compatdata/<runtime>`. Package installs and game launches use the same per-game environment.
