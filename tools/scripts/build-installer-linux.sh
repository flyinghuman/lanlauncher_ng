#!/usr/bin/env bash
set -euo pipefail

PACKAGE_ROOT="${1:-dist/linux/lanlauncherng}"
INSTALLER_ROOT="${2:-dist/linux/installer}"
STAGING_DIR="$INSTALLER_ROOT/lanlauncherng-installer"
ARCHIVE_PATH="$INSTALLER_ROOT/lanlauncherng-installer.tar.gz"

./packaging/linux/package-linux.sh "$PACKAGE_ROOT"

rm -rf "$STAGING_DIR"
mkdir -p "$STAGING_DIR"

cp -a "$PACKAGE_ROOT" "$STAGING_DIR/lanlauncherng"
# The Linux installer recreates .venv-runtime-lin on the target host, so we
# intentionally exclude the prebuilt runtime env from installer payload.
rm -rf "$STAGING_DIR/lanlauncherng/.venv-runtime-lin"
cp -a "packaging/linux/install.sh" "$STAGING_DIR/install.sh"
cp -a "packaging/linux/uninstall.sh" "$STAGING_DIR/uninstall.sh"
cp -a "packaging/linux/README.md" "$STAGING_DIR/README.md"
cp -a "packaging/linux/README.txt" "$STAGING_DIR/README.txt"
if [[ -f "ng_provider/bootstrap.json" ]]; then
  cp -a "ng_provider/bootstrap.json" "$STAGING_DIR/bootstrap.json"
fi
chmod +x "$STAGING_DIR/install.sh" "$STAGING_DIR/uninstall.sh"

mkdir -p "$INSTALLER_ROOT"
rm -f "$INSTALLER_ROOT/bootstrap.json"
cp -a "packaging/linux/README.md" "$INSTALLER_ROOT/README.md"
cp -a "packaging/linux/README.txt" "$INSTALLER_ROOT/README.txt"
if [[ -f "ng_provider/bootstrap.json" ]]; then
  cp -a "ng_provider/bootstrap.json" "$INSTALLER_ROOT/bootstrap.json"
fi
tar -C "$INSTALLER_ROOT" -czf "$ARCHIVE_PATH" "lanlauncherng-installer"

echo "Linux installer bundle created: $ARCHIVE_PATH"
