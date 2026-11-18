#!/usr/bin/env bash
set -euo pipefail

OUTPUT_ROOT="${1:-dist/linux/lanlauncherng}"
ROOT="$(pwd)"
OUT="$ROOT/$OUTPUT_ROOT"
ICON_PNG="$ROOT/src/frontend/assets/icons/lanlauncherng.png"
RUNTIME_VENV="$ROOT/.venv-runtime-lin"
RUNTIME_VENV_BUILDER="$ROOT/tools/scripts/build-runtime-venv.sh"

if [[ ! -f "$ICON_PNG" ]]; then
  echo "App icon missing: $ICON_PNG" >&2
  echo "Run: ./.venv/Scripts/python.exe tools/scripts/generate-app-icons.py" >&2
  exit 1
fi

if [[ ! -x "$RUNTIME_VENV/bin/python" ]]; then
  if [[ ! -f "$RUNTIME_VENV_BUILDER" ]]; then
    echo "Runtime venv missing and builder script not found: $RUNTIME_VENV_BUILDER" >&2
    exit 1
  fi
  echo "Building runtime venv at $RUNTIME_VENV ..."
  bash "$RUNTIME_VENV_BUILDER" "$RUNTIME_VENV"
fi

metadata_roots=()
for candidate in library ng_provider; do
  if [[ -d "$candidate" ]]; then
    metadata_roots+=("$candidate")
  fi
done
if (( ${#metadata_roots[@]} > 0 )); then
  "$RUNTIME_VENV/bin/python" tools/scripts/lint_game_metadata.py "${metadata_roots[@]}"
fi

rm -rf "$OUT"
mkdir -p \
  "$OUT/app" \
  "$OUT/config" \
  "$OUT/config/install" \
  "$OUT/config/resilio" \
  "$OUT/data/library" \
  "$OUT/data/legacy" \
  "$OUT/data/logs" \
  "$OUT/data/sync" \
  "$OUT/data/ouisync" \
  "$OUT/vendor/bin" \
  "$OUT/vendor/bin/linux-x64" \
  "$OUT/vendor/licenses" \
  "$OUT/vendor/licenses/resilio" \
  "$OUT/vendor/python" \
  "$OUT/vendor/licenses/ouisync" \
  "$OUT/vendor/licenses/msgpack" \
  "$OUT/site" \
  "$OUT/docs" \
  "$OUT/scripts/wrappers" \
  "$OUT/scripts/checks"

cp -R src "$OUT/app/src"
cp -R tools "$OUT/app/tools"
find "$OUT/app/src" "$OUT/app/tools" -type d -name '__pycache__' -prune -exec rm -rf {} +
find "$OUT/app/src" "$OUT/app/tools" -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete
if [[ -f "VERSION" ]]; then
  cp "VERSION" "$OUT/VERSION"
fi
if compgen -G "vendor/bin/linux-x64/*" > /dev/null; then
  cp -R vendor/bin/linux-x64/* "$OUT/vendor/bin/linux-x64"
fi
if [[ -d "vendor/python" ]]; then
  cp -R vendor/python/. "$OUT/vendor/python/"
fi
find "$OUT/vendor/python" -type d -name '__pycache__' -prune -exec rm -rf {} +
find "$OUT/vendor/python" -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete
cp vendor/licenses/ouisync/* "$OUT/vendor/licenses/ouisync/"
cp vendor/licenses/msgpack/LICENSE.txt "$OUT/vendor/licenses/msgpack/LICENSE.txt"
cp -R docs/* "$OUT/docs"
if [[ -d "site" ]]; then
  cp -R site/* "$OUT/site"
else
  echo "warning: compiled docs folder 'site/' not found; local docs link will be unavailable until site is generated" >&2
fi
if [[ -d "scripts" ]]; then
  cp -R scripts/* "$OUT/scripts"
fi
if [[ -f "config/install/checks.json" ]]; then
  cp "config/install/checks.json" "$OUT/config/install/checks.json"
fi
if [[ -f "config/resilio/config.yml" ]]; then
  cp "config/resilio/config.yml" "$OUT/config/resilio/config.yml"
fi
if [[ -f "config/resilio/config.json" ]]; then
  cp "config/resilio/config.json" "$OUT/config/resilio/config.json"
fi
if [[ -f "config/bootstrap.json" ]]; then
  cp "config/bootstrap.json" "$OUT/config/bootstrap.json"
fi
if [[ -f "config/feature-flags.json" ]]; then
  cp "config/feature-flags.json" "$OUT/config/feature-flags.json"
fi
if [[ -f "old/game.db" ]]; then
  cp "old/game.db" "$OUT/data/legacy/game.db"
fi

if [[ -d "$RUNTIME_VENV" ]]; then
  cp -R "$RUNTIME_VENV" "$OUT/.venv-runtime-lin"
fi

cat > "$OUT/config/core.json" <<'JSON'
{
  "bind_host": "127.0.0.1",
  "bind_port": 18080,
  "db_path": "data/lanlauncher.db",
  "legacy_db_path": "data/legacy/game.db",
  "library_path": "data/library",
  "log_path": "data/logs/log.txt",
  "log_level": "WARNING",
  "default_locale": "en",
  "sync_provider": "ouisync",
  "sync_binary_path": "vendor/bin/linux-x64/rslsync",
  "sync_config_path": "config/resilio/config.json",
  "sync_pid_path": "data/sync/rslsync.pid",
  "sync_log_path": "data/logs/resilio-sync.log",
  "sync_license_key_path": "vendor/licenses/resilio/llng.btskey",
  "sync_api_url": "http://127.0.0.1:13338/api",

  "sync_api_key": "VGWWKFEB2BVHKUNMUPMZHTZFNEVSPWT5CO3UKNKOMXL54FOYDF7VQ2FTUK2M7HXQRMRZ4H5XPABI3NKR7EMCMCVEJDGG54RDO56AGASC2WTU366TPMDTTH4HUS4XWL2LIA",
  "sync_request_timeout_seconds": 2,
  "sync_retry_count": 3,
  "sync_startup_retry_seconds": 8,
  "ouisync_binary_path": "vendor/bin/linux-x64/ouisync",
  "ouisync_config_dir": "data/ouisync",
  "ouisync_log_path": "data/logs/ouisync.log",
  "ouisync_startup_timeout_seconds": 15,
  "tool_manifest_path": "app/tools/manifest.json",
  "repo_root": ".",
  "install_scripts_root": "scripts/wrappers",
  "install_checks_path": "config/install/checks.json",
  "linux_cmd_wrapper_path": "scripts/wrappers/linux/run-cmd-wrapper.sh",
  "settings_path": "data/settings.json",
  "default_extra_sync_items_path": "config/bootstrap.json",
  "feature_flags_path": "config/feature-flags.json",
  "update_manifest_path": "ng_provider/update/update-manifest.json"
}
JSON

cat > "$OUT/run.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
# Resolve symlinked launcher entrypoints (for example /usr/local/bin/lanlauncherng)
# so runtime paths are always relative to the real install directory.
SCRIPT_SOURCE="${BASH_SOURCE[0]}"
while [[ -h "$SCRIPT_SOURCE" ]]; do
  SCRIPT_DIR="$(cd -P "$(dirname "$SCRIPT_SOURCE")" && pwd)"
  SCRIPT_SOURCE="$(readlink "$SCRIPT_SOURCE")"
  [[ "$SCRIPT_SOURCE" != /* ]] && SCRIPT_SOURCE="$SCRIPT_DIR/$SCRIPT_SOURCE"
done
SCRIPT_DIR="$(cd -P "$(dirname "$SCRIPT_SOURCE")" && pwd)"
cd "$SCRIPT_DIR"
if [[ ! -f ".venv-runtime-lin/bin/python" ]]; then
  echo "Missing bundled Python environment (.venv-runtime-lin)."
  exit 1
fi
if [[ ! -x ".venv-runtime-lin/bin/python" ]]; then
  echo "Bundled Python exists but is not executable (.venv-runtime-lin/bin/python)." >&2
  echo "Your filesystem may be mounted with noexec; move/install the package to an executable filesystem." >&2
  exit 1
fi
export PYTHONPATH="app"
.venv-runtime-lin/bin/python -m src.core.main --config config/core.json
SH

chmod +x "$OUT/run.sh"
if [[ -f "$OUT/scripts/wrappers/linux/run-cmd-wrapper.sh" ]]; then
  chmod +x "$OUT/scripts/wrappers/linux/run-cmd-wrapper.sh"
fi
echo "Linux package created at: $OUT"
