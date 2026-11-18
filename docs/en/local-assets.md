# Local Resilio Assets

This page covers the legacy Resilio setup path. Ouisync is bundled with LANLauncherNG and does not need a separate local license file.

LANLauncherNG does not ship Resilio Sync binaries or license files. If you want to deploy a local Resilio build together with LANLauncherNG, place the files next to the installer or install script before running setup.

## Windows
- Rename the downloaded Resilio Sync setup file to `btsync.exe`.
- Place `btsync.exe` next to the LANLauncherNG installer.
- Place `llng.btskey` next to the installer if you have a license key file.
- Place `bootstrap.json` next to the installer if you want custom extra-provider presets to be installed automatically.
  - Seed items can declare `game_provider_type` as `resilio` or `ouisync`.
- During installation, the setup copies those files to:
  - `vendor/bin/windows-amd64/btsync.exe`
  - `vendor/licenses/resilio/llng.btskey`
  - `config/bootstrap.json`

## Linux
- Place `rslsync` next to `install.sh`.
- Place `llng.btskey` next to `install.sh` if you have a license key file.
- Place `bootstrap.json` next to `install.sh` if you want custom extra-provider presets to be installed automatically.
- During installation, the script copies those files to:
  - `vendor/bin/linux-x64/rslsync`
  - `vendor/licenses/resilio/llng.btskey`
  - `config/bootstrap.json`
- If `rslsync` is missing, the installer prints a warning that Resilio mode needs a local `rslsync` binary before installation.

## Notes
- The files are gitignored on purpose so local admins can distribute their own Resilio setup without adding it to the repository.
- Update manifests preserve these local Resilio files when possible, so a directory-swap update will not delete an already copied `rslsync` or `llng.btskey`.
- If you want to use different locations, set `sync_binary_path` and `sync_license_key_path` in `config/core.json` or via `LLNG_SYNC_BINARY_PATH` and `LLNG_SYNC_LICENSE_KEY_PATH`.
- Ouisync is the default provider; see the sync provider reference for its configuration.
