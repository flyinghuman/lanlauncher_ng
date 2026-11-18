#!/usr/bin/env bash
set -euo pipefail

SCRIPT_SOURCE="${BASH_SOURCE[0]}"
while [[ -h "$SCRIPT_SOURCE" ]]; do
  SCRIPT_DIR="$(cd -P "$(dirname "$SCRIPT_SOURCE")" && pwd)"
  SCRIPT_SOURCE="$(readlink "$SCRIPT_SOURCE")"
  [[ "$SCRIPT_SOURCE" != /* ]] && SCRIPT_SOURCE="$SCRIPT_DIR/$SCRIPT_SOURCE"
done

REPO_ROOT="$(cd -P "$(dirname "$SCRIPT_SOURCE")/../.." && pwd)"
cd "$REPO_ROOT"

resolve_powershell() {
  if command -v pwsh >/dev/null 2>&1; then
    command -v pwsh
    return
  fi
  if command -v powershell >/dev/null 2>&1; then
    command -v powershell
    return
  fi
  echo "PowerShell executable not found (pwsh/powershell)." >&2
  exit 1
}

PWSH_BIN="${PWSH_BIN:-$(resolve_powershell)}"
PYTHON_BIN="${PYTHON_BIN:-$REPO_ROOT/.venv/bin/python}"
if [[ ! -x "$PYTHON_BIN" ]]; then
  if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python3)"
  else
    echo "Python executable not found (.venv/bin/python or python3)." >&2
    exit 1
  fi
fi

WINDOWS_PACKAGE_ROOT="${WINDOWS_PACKAGE_ROOT:-dist/windows/lanlauncherng}"
WINDOWS_UPDATE_OUTPUT_DIR="${WINDOWS_UPDATE_OUTPUT_DIR:-dist/windows/update}"
LINUX_PACKAGE_ROOT="${LINUX_PACKAGE_ROOT:-dist/linux/lanlauncherng}"
LINUX_INSTALLER_ROOT="${LINUX_INSTALLER_ROOT:-dist/linux/installer}"
LINUX_UPDATE_OUTPUT_DIR="${LINUX_UPDATE_OUTPUT_DIR:-dist/linux/update}"
INSTALL_TARGET_PATH="${INSTALL_TARGET_PATH:-.}"
PRESERVE_PATHS="${PRESERVE_PATHS:-data}"
KEY_ID="${KEY_ID:-llng-root-2026}"
PRIVATE_KEY_PATH="${PRIVATE_KEY_PATH:-secrets/llng-update-private.pem}"
PUBLIC_KEY_PATH="${PUBLIC_KEY_PATH:-secrets/llng-update-public.pem}"

echo "Building Windows installer and update package..."
"$PWSH_BIN" -ExecutionPolicy Bypass -File "tools/scripts/build-installer-and-update-windows.ps1" \
  -PackageRoot "$WINDOWS_PACKAGE_ROOT" \
  -UpdateOutputDir "$WINDOWS_UPDATE_OUTPUT_DIR" \
  -InstallTargetPath "$INSTALL_TARGET_PATH" \
  -PreservePaths "$PRESERVE_PATHS" \
  -KeyId "$KEY_ID" \
  -PublicKeyPath "$PUBLIC_KEY_PATH" \
  -PrivateKeyPath "$PRIVATE_KEY_PATH"

echo "Building Linux installer bundle..."
bash "tools/scripts/build-installer-linux.sh" "$LINUX_PACKAGE_ROOT" "$LINUX_INSTALLER_ROOT"

echo "Building Linux update package..."
"$PYTHON_BIN" "tools/scripts/build_update_package.py" \
  --package-root "$LINUX_PACKAGE_ROOT" \
  --output-dir "$LINUX_UPDATE_OUTPUT_DIR" \
  --package-platform linux \
  --install-target-path "$INSTALL_TARGET_PATH" \
  --preserve-paths "$PRESERVE_PATHS" \
  --key-id "$KEY_ID" \
  --public-key "$PUBLIC_KEY_PATH" \
  --private-key "$PRIVATE_KEY_PATH" \
  --register-public-key \
  --overwrite \
  --skip-package-build

echo "Cross-platform installer and updater build complete."
echo "Windows package: $WINDOWS_PACKAGE_ROOT"
echo "Windows update: $WINDOWS_UPDATE_OUTPUT_DIR"
echo "Linux package: $LINUX_PACKAGE_ROOT"
echo "Linux installer: $LINUX_INSTALLER_ROOT"
echo "Linux update: $LINUX_UPDATE_OUTPUT_DIR"
