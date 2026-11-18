# Packaging and release

This reference is for maintainers building application bundles, installers, and update packages. `VERSION` is the source of truth for the application and installer version. Use the scripts below for the target platform and validate the resulting package before distributing it.

## Scripts
- Windows package:
  - `tools/scripts/package-windows.ps1`
  - `packaging/windows/package-windows.ps1`
- Windows bundled Python updater:
  - `tools/scripts/update-bundled-python-runtime.ps1`
- Windows installer:
  - `tools/scripts/build-installer-windows.ps1`
  - `tools/scripts/build-installer-and-update-windows.ps1`
  - `packaging/windows/inno/lanlauncherng.iss`
- Cross-platform release wrapper:
  - `tools/scripts/build-cross-platform-installer-and-updater.sh`
- Update package + manifest:
  - `tools/scripts/build_update_package.py`
- Embed the catalog root public key:
  - `tools/scripts/register_game_catalog_root.py`
- Sign an OpenSourceGameIndex or publisher registry:
  - `tools/scripts/sign_ogsi_document.py`
- Automatic version bump, package build, and publication:
  - `tools/scripts/build_and_publish_update.py`
- Linux package:
  - `packaging/linux/package-linux.sh`
- Linux installer bundle:
  - `tools/scripts/build-installer-linux.sh`
  - `packaging/linux/install.sh`
  - `packaging/linux/uninstall.sh`
- Artifact checksums:
  - `packaging/shared/generate-checksums.ps1`
- Icon generation helper:
  - `tools/scripts/generate-app-icons.py`

## Provider files in installation packages

Both installer builds place `README.md`, `README.txt`, and the shipped `bootstrap.json` beside the final installer artifact. The Linux archive also contains those files beside `install.sh` so users can edit the provider template after extracting it.

The shipped bootstrap file seeds provider catalog entries; `game_provider_type` routes an entry to Resilio or Ouisync. It does not select the LLNG Client/Server role, pair a LAN client, or enable/disable provider processes. The bundled Ouisync runtime is available without an extra download.

The bundled Ouisync CLI is upstream v0.10.2 (`ee4dffce2fb5458a821afef14a41d77abbc85926`) plus the LLNG patch `vendor/licenses/ouisync/LLNG-MODIFICATIONS.patch` (manifest version `0.10.2+llng.1`). Upstream 0.10.x saves re-received leaf nodes of reused blocks as missing, so read replicas stall below 100% after repository updates; the patch saves them as present when the block is stored locally. Check out the tag, apply the patch with `git apply`, and run `cargo test --locked -p ouisync --lib` before building. The patch file is also the MPL-2.0 source offer for the modified files and ships in the package. Build Linux with `cargo build --release --locked -p ouisync-cli --features vfs --target x86_64-unknown-linux-gnu`; it requires FUSE development headers at build time and `/dev/fuse` access at runtime. A build on the current development host links against glibc 2.39 symbols; check `objdump -T` before release when the build host changes. For Windows, use the MSVC target and `cargo-xwin` (not MinGW): build with `DOKAN_DLL_OUTPUT_PATH=<output-dir> cargo xwin build --target x86_64-pc-windows-msvc --release --locked -p ouisync-cli --features vfs`, then ship `ouisync.exe`, the generated `dokan2.dll`, and `VCRUNTIME140.dll` beside each other. Reuse the VCRUNTIME DLL already included in the CPython runtime and declare its hash and Python redistribution notice in the manifest. The Windows package also carries the official Dokany v2.3.0.1000 x64 MSI. Its signed kernel driver is offered as a checked-by-default installer task and remains installed after temporary mounts end; do not silently remove or replace an existing Dokan 2 driver. Remap source and Cargo paths in release builds, then run the developer-path leakage check and both platform manifest checks. ADR-0003 records this system dependency and its administrator requirement.

Resilio binaries and license files are proprietary and are not redistributed by LLNG. The Windows setup detects optional `btsync.exe` and `llng.btskey` files beside the setup EXE. The Linux install script detects `rslsync` and `llng.btskey` beside the extracted `install.sh`. Both installers copy supplied files into the configured runtime paths. Use only binaries and a license obtained for the intended platform and use from Resilio; consult its [Terms of Use](https://www.resilio.com/legal/terms-of-use/), [download page](https://www.resilio.com/sync/download/), and [license instructions](https://help.resilio.com/hc/en-us/articles/204762369-How-to-apply-license-key-and-share-license-seats).

## Bundled tool manifest
- `tools/scripts/package-windows.ps1` refreshes `tools/manifest.json` SHA256 values before packaging.
- Windows and Linux package builds run `tools/scripts/lint_game_metadata.py` over repository `library/` and `ng_provider/` trees when present. Run it explicitly with additional roots for staged game content; it fails packaging on unsupported or malformed installer actions.
- `tools/scripts/build-installer-windows.ps1` also refreshes checksums:
  - against repository tools when package build is included
  - against `app/tools/manifest.json` inside the packaged root when `-SkipPackageBuild` is used

## Prerequisites
- Git checkout available locally.
- `VERSION` file present in repository root (single source of truth for app + installer version).
- Python virtual environment available at `.venv` (contains `mkdocs` and test tooling).
- Windows development virtual environment available at `.venv-dev-win` (contains `mkdocs` and other Windows-side tooling).
- Linux development virtual environment remains `.venv`.
- Compiled local docs folder available at `site/` (build via `mkdocs build --strict`).
- Runtime packaging:
  - Windows packages ship an embedded CPython runtime under `vendor/bin/windows-amd64/python`.
  - Linux packages still use `.venv-runtime-lin`.
  - If missing or invalid, packaging scripts auto-create the matching runtime via `tools/scripts/build-runtime-venv.ps1` (Windows embedded runtime) or `tools/scripts/build-runtime-venv.sh` (Linux venv).
  - Windows runtime builder downloads the official `python-<version>-embed-amd64.zip` into `.cache/python-runtime-win/`, expands it into `vendor/bin/windows-amd64/python`, writes `python<xy>._pth`, and copies the Python license into `vendor/licenses/python/LICENSE.txt`.
  - Linux runtime builder uses `python -m venv --copies` to avoid broken interpreter symlinks on cross-mounted filesystems.
- Package output includes `site/` when present; the frontend help button opens `file://.../site/index.html` from local disk.
- Windows installer builds require Inno Setup 6 (`ISCC.exe`), for example:
  - `C:\Program Files (x86)\Inno Setup 6\ISCC.exe`
  - `P:\Programme\Inno Setup 6\ISCC.exe`
  - `$HOME/.wine/drive_c/Program Files (x86)/Inno Setup 6/ISCC.exe` (Linux + Wine)
- Linux installer bundle builds require:
  - `bash`
  - `tar`

## Build Commands (Windows)
0. Update the bundled Windows Python runtime when needed:
   - latest patch in the current bundled series:
     - `powershell -ExecutionPolicy Bypass -File tools/scripts/update-bundled-python-runtime.ps1`
   - latest stable CPython release from python.org:
     - `powershell -ExecutionPolicy Bypass -File tools/scripts/update-bundled-python-runtime.ps1 -LatestStable`
   - exact version pin:
     - `powershell -ExecutionPolicy Bypass -File tools/scripts/update-bundled-python-runtime.ps1 -PythonVersion 3.14.1`
   - script behavior:
     - resolves the target version from the official python.org FTP index
     - rebuilds `vendor/bin/windows-amd64/python`
     - updates the `python-runtime` entry in `tools/manifest.json` with the new version and `python.exe` SHA256
1. (If icon assets are missing) generate icons:
   - `.\.venv-dev-win\Scripts\python.exe tools/scripts/generate-app-icons.py`
2. Create portable Windows package:
   - `powershell -ExecutionPolicy Bypass -File tools/scripts/package-windows.ps1 -OutputRoot "dist/windows/lanlauncher"`
3. Build Windows setup EXE (Inno Setup):
   - `powershell -ExecutionPolicy Bypass -File tools/scripts/build-installer-windows.ps1`
4. Output artifact:
   - `dist/windows/installer/lanlauncherng-setup.exe`

## Cross-Platform Release Wrapper
On the Linux development machine, build both Windows and Linux installer/update artifacts with the repo defaults:

```bash
bash tools/scripts/build-cross-platform-installer-and-updater.sh
```

Default output locations:
- Windows package: `dist/windows/lanlauncherng`
- Windows installer: `dist/windows/installer`
- Windows update package: `dist/windows/update`
- Linux package: `dist/linux/lanlauncherng`
- Linux installer: `dist/linux/installer`
- Linux update package: `dist/linux/update`

The wrapper reuses the existing release scripts, so it still depends on `pwsh`/`bash`, `.venv`, OpenSSL, and the bundled signing keys.

## Build Update Package + Manifest

For the normal developer workflow, keep the update destination in the ignored
`.env` file (see `.env.example`):

```dotenv
LLNGUPDATEFOLDER=/absolute/path/to/ng_provider/update
```

Run this after every code change:

```bash
./.venv/bin/python tools/scripts/build_and_publish_update.py
```

On Windows use `.\.venv-dev-win\Scripts\python.exe` with the same script.

The script increments the patch component in `VERSION`, builds the current
platform package and signed update manifest, then atomically copies the ZIP and
`update-manifest.json` into `LLNGUPDATEFOLDER`. A failed build restores the
previous `VERSION`; signing keys, `.env`, and local update paths remain ignored.
Use `--no-publish` for a local artifact build without copying to the update
folder.

Create update payload zip and manifest in one step:

```powershell
.\.venv-dev-win\Scripts\python.exe tools/scripts/build_update_package.py `
  --package-root dist/windows/lanlauncherng `
  --output-dir dist/windows/update `
  --install-mode directory_swap `
  --install-target-path "." `
  --preserve-paths "data" `
  --key-id llng-root-2026 `
  --register-public-key `
  --public-key secrets/llng-update-public.pem `
  --private-key secrets/llng-update-private.pem `
  --overwrite
```

Default behavior:
- `build_update_package.py` selects package builder by platform (`--package-platform auto`):
  - `dist/windows/...` -> `tools/scripts/package-windows.ps1`
  - `dist/linux/...` -> `packaging/linux/package-linux.sh`
- Use `--skip-package-build` to skip this pre-step when package root is already built.
- Before zipping, payload is normalized to always include:
  - both launcher scripts: `run.bat` and `run.sh`
  - both bundled runtime binary folders: `vendor/bin/windows-amd64` and `vendor/bin/linux-x64`
  - for Linux update payloads, `.venv-runtime-lin` is removed from the ZIP so the builder-machine venv is never shipped
  - Linux update manifests automatically preserve `.venv-runtime-lin` on the target install so the locally created runtime survives directory-swap updates

Output files:
- `dist/windows/update/lanlauncherng-update-<version>.zip`
- `dist/windows/update/update-manifest.json`

## Build Installer + Update Package Together
Single command for both artifacts:

```powershell
powershell -ExecutionPolicy Bypass -File tools/scripts/build-installer-and-update-windows.ps1 `
  -PackageRoot "dist/windows/lanlauncherng" `
  -UpdateOutputDir "dist/windows/update" `
  -InstallTargetPath "." `
  -KeyId "llng-root-2026" `
  -PublicKeyPath "secrets/llng-update-public.pem" `
  -PrivateKeyPath "secrets/llng-update-private.pem"
```

Default behavior:
- combined script builds package root first, then builds installer and update artifacts from that package.
- use `-SkipPackageBuild` only if you intentionally want to reuse an existing package root.
- the update-package stage uses the bundled `vendor/bin/windows-amd64/python/python.exe` runtime, not the developer venv.

By default, `build-installer-and-update-windows.ps1` registers the public key into
`src/core/service/app.py` (`UPDATE_MANIFEST_PUBLIC_KEYS`) before signing/building.
Use `-SkipPublicKeyRegistration` to disable that behavior.

## Private Key and Signature Notes
- Manifest signatures are RSA-SHA256, created using `openssl`.
- `build_update_package.py` auto-detects OpenSSL from:
  - `PATH`
  - common Windows installs (for example `C:\Program Files\OpenSSL-Win64\bin\openssl.exe`)
- If detection fails, pass `--openssl-bin "<full path to openssl.exe>"`.
- The `signature.key_id` in the manifest must match a trusted public key embedded in launcher code (`UPDATE_MANIFEST_PUBLIC_KEYS`).
- If you rotate to a new signing key:
  1. add the new public key + `key_id` to launcher code
  2. release that launcher version first
  3. then sign update manifests with the new private key

Generate a private key example (2048-bit RSA):

```powershell
New-Item -ItemType Directory -Force -Path "secrets" | Out-Null
& "C:\Program Files\OpenSSL-Win64\bin\openssl.exe" genpkey -algorithm RSA -out "secrets/llng-update-private.pem" -pkeyopt rsa_keygen_bits:2048
```

PowerShell note:
- If the executable path is quoted (for example under `Program Files`), use the call operator `&` before the path.

### OpenSourceGameIndex publisher root

Game-catalog trust uses a separate offline root key and never reuses the update key. Keep its private key on an offline or otherwise protected machine outside the repository and synchronized folders. Generate the root key and public copy with OpenSSL:

```bash
install -d -m 700 "$HOME/.local/share/llng-signing"
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 -out "$HOME/.local/share/llng-signing/catalog-root-private.pem"
chmod 600 "$HOME/.local/share/llng-signing/catalog-root-private.pem"
openssl pkey -in "$HOME/.local/share/llng-signing/catalog-root-private.pem" -pubout -out "$HOME/.local/share/llng-signing/catalog-root-public.pem"
./.venv/bin/python tools/scripts/register_game_catalog_root.py \
  --public-key "$HOME/.local/share/llng-signing/catalog-root-public.pem" \
  --key-id llng-catalog-root-2026
```

The registration tool reads only the public PEM and embeds that trust anchor in `src/core/catalog/publisher_trust.py`. Review the source diff and build/release a launcher containing the root before publishing a signed v2 index. The tool rejects keys below 3072 bits, keys above 4096 bits, and exponents other than 65537. Never copy the private key into the repository, package, provider update folder, or a game repository. Publisher signing keys are separate, individually listed in `trusted-publishers.json`, and can be revoked by a newer root-signed registry.

Edit the trust registry as a reviewed manual change: add a publisher public key with `game-index` usage, or mark its existing key ID `revoked` and advance the registry sequence. Do not reuse key IDs. Sign the updated registry with the offline root, then sign each index with its authorized publisher key:

```bash
./.venv/bin/python tools/scripts/sign_ogsi_document.py registry \
  --input trusted-publishers-draft.json \
  --output ng_provider/update/trusted-publishers.json \
  --key-id llng-catalog-root-2026 \
  --private-key "$HOME/.local/share/llng-signing/catalog-root-private.pem"
./.venv/bin/python tools/scripts/sign_ogsi_document.py index \
  --input index-draft.json \
  --output ng_provider/update/index.json \
  --key-id publisher-maintainer-1 \
  --private-key /path/to/offline/publisher-private.pem
```

The signing script canonicalizes JSON, invokes OpenSSL, and writes only the signature and signed document to the output. It does not publish or synchronize anything. Distribute the reviewed registry and index through the NG Ouisync provider so clients can verify them offline.

The publisher-only helper and its README are versioned under `ng_provider/`; publisher credentials, VPN configuration, and repository data remain Git-ignored. The helper builds an unsigned index candidate from each immediate `repos/<game_id>/metadata.json` folder. On the seed host, run `python3 generate_index.py`; by default it writes `/opt/ng_provider/index-draft.json`, outside the seed tree, advances the revision beyond the existing draft/signed index, omits empty catalog-only placeholders, and verifies each Ouisync archive's declared SHA-256. Review the candidate, sign it on the offline signing machine with the command above, return the signed index to the seed host, then reconcile the per-game repositories and finally the `ng_provider` repository. The complete sequence and requirements for token/info-hash metadata are documented in `ng_provider/README.md`. The script is publisher infrastructure and is not included in LLNG installers or updates.

Unsigned local test manifest (not accepted by production launcher signature checks):

```powershell
.\.venv-dev-win\Scripts\python.exe tools/scripts/build_update_package.py `
  --package-root dist/windows/lanlauncherng `
  --output-dir dist/windows/update `
  --unsigned `
  --overwrite
```

## Build Commands (Linux)
0. (If icon assets are missing) generate icons:
   - `./.venv-dev-win/Scripts/python.exe tools/scripts/generate-app-icons.py`
1. Create portable Linux package:
   - `bash packaging/linux/package-linux.sh dist/linux/lanlauncherng`
2. Build Linux installer bundle (`tar.gz` containing payload + install scripts):
   - `bash tools/scripts/build-installer-linux.sh dist/linux/lanlauncherng dist/linux/installer`
3. Output artifact:
   - `dist/linux/installer/lanlauncherng-installer.tar.gz`
4. Installer payload note:
  - the installer archive excludes prebuilt `.venv-runtime-lin`; install step recreates it with target host `python3`.
   - reinstalling with `sudo ./install.sh` restores ownership and write permissions for `$PREFIX/data` and `$PREFIX/config` to the invoking sudo user.
  - after an elevated directory-swap update, the updater restores the invoking user's ownership and write permissions on `config/` too. Resilio persists the install-specific absolute `storage_path` and `pid_file` in `config/resilio/config.json` at startup.

## Checksum Generation
- Generate checksums for release files:
  - `powershell -ExecutionPolicy Bypass -File packaging/shared/generate-checksums.ps1 -TargetPath dist`
- Output:
  - `dist/SHA256SUMS.txt`

## Validation Before Release
1. Run tests:
   - `.\.venv-dev-win\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"`
2. Verify i18n parity:
   - `powershell -ExecutionPolicy Bypass -File tools/scripts/verify-i18n.ps1`
3. Verify bundled runtime tools:
   - `powershell -ExecutionPolicy Bypass -File tools/scripts/verify-bundle.ps1`
4. Build docs in strict mode:
   - `.\.venv-dev-win\Scripts\python.exe -m mkdocs build --strict`

## Installer Usage (Linux)
After extracting `lanlauncherng-installer.tar.gz`:
1. Install:
   - `sudo ./install.sh`
2. Start launcher:
   - `lanlauncherng`
3. Uninstall:
   - `sudo ./uninstall.sh`

Linux installer also installs launcher icon to:
- `/usr/share/pixmaps/lanlauncherng.png`
- `/root/Desktop/LANLauncherNG.desktop`
- `/home/<sudo-user>/Desktop/LANLauncherNG.desktop` (when installed via `sudo`)
- During installation, `.venv-runtime-lin` is recreated with the target host's `python3` so runtime Python matches that Linux system.
- During installation, writable runtime paths (`data`) are re-owned to the invoking sudo user to recover from root-owned files left by elevated updates.
- Packaged `core.json` sets `log_path` to `data/logs/log.txt`. If this path is not writable at startup, launcher logging falls back to user-writable paths.

## Troubleshooting
- Wrong version shown in app or installer:
  - update root `VERSION` file and rebuild package + installer.
- `ISCC.exe not found`:
  - install Inno Setup 6 and rerun `build-installer-windows.ps1`.
- `run.bat` errors:
  - rebuild package with latest `tools/scripts/package-windows.ps1`.
- Missing bundled tools at startup:
  - run `verify-bundle.ps1`, then rebuild package.
- Missing runtime Python in packaged app:
  - rebuild the package; Windows bundles `vendor/bin/windows-amd64/python/python.exe` and Linux bundles `.venv-runtime-lin`. The launcher start scripts use the matching runtime.
  - on Linux, the package build rebuilds `.venv-runtime-lin` when `bin/python` is not executable.
- Windows package build reports developer machine path leakage:
  - rebuild with `tools/scripts/package-windows.ps1`; the package builder strips Python cache artifacts from `app/src` and `app/tools`, and fails if the staged bundle contains the local repo or home-directory path.
- Linux launcher reports missing `.venv-runtime-lin` when started from `/usr/local/bin/lanlauncherng`:
  - rebuild the package/installer with `packaging/linux/package-linux.sh` and reinstall; `run.sh` resolves symlink paths to the actual install directory.
- Linux installer reports missing system Python:
  - install `python3-venv`/`python3` on the target machine, then rerun `sudo ./install.sh`.
- `run.sh` reports bundled Python is not executable:
  - current filesystem may be mounted with `noexec`; move/install package to an executable filesystem (for example `/opt`).
- Windows embedded runtime download fails:
  - verify access to `https://www.python.org/ftp/python/` and rerun `tools/scripts/build-runtime-venv.ps1`.
  - the downloaded embed ZIP is cached under `.cache/python-runtime-win/`.
- Bundled Python updater picks an unexpected version:
  - run `tools/scripts/update-bundled-python-runtime.ps1 -PythonVersion <exact version>` to pin the target explicitly.
  - without arguments the updater tracks the latest patch release in the currently bundled major/minor series from `tools/manifest.json`.
  - with `-LatestStable` it upgrades to the highest stable version published in the python.org FTP index.
- MkDocs strict failures:
  - fix nav/links and rerun `mkdocs build --strict`.

## Startup safety
At service bootstrap, required bundled tools are validated from `tools/manifest.json`:
- file existence
- SHA256 checksum (if configured)
- license file presence (if configured)

## Release flow summary
1. Build packages (`dist/windows`, `dist/linux`).
2. Build installer artifacts:
   - Windows (`build-installer-windows.ps1`, requires Inno Setup 6 / `ISCC.exe`)
   - Linux (`build-installer-linux.sh`, produces `tar.gz` with `install.sh`/`uninstall.sh`)
3. Generate `SHA256SUMS.txt`.
4. Run smoke tests on clean machines.
5. Publish artifacts + checksums + bilingual release notes.
