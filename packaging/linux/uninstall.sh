#!/usr/bin/env bash
set -euo pipefail

PREFIX="${PREFIX:-/opt/lanlauncherng}"
BIN_LINK="${BIN_LINK:-/usr/local/bin/lanlauncherng}"
DESKTOP_FILE="/usr/share/applications/lanlauncherng.desktop"
PIXMAP_ICON="/usr/share/pixmaps/lanlauncherng.png"
DESKTOP_SHORTCUT_NAME="LANLauncherNG.desktop"
ROOT_DESKTOP_FILE="/root/Desktop/$DESKTOP_SHORTCUT_NAME"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run uninstaller as root (sudo)." >&2
  exit 1
fi

rm -f "$BIN_LINK"
rm -f "$DESKTOP_FILE"
rm -f "$PIXMAP_ICON"
rm -f "$ROOT_DESKTOP_FILE"
if [[ -n "${SUDO_USER:-}" && "$SUDO_USER" != "root" ]]; then
  SUDO_HOME="$(getent passwd "$SUDO_USER" | cut -d: -f6 || true)"
  if [[ -n "$SUDO_HOME" ]]; then
    rm -f "$SUDO_HOME/Desktop/$DESKTOP_SHORTCUT_NAME"
  fi
fi
rm -rf "$PREFIX"

echo "Removed LANLauncherNG from $PREFIX"
