#!/usr/bin/env bash
set -euo pipefail

PREFIX="${PREFIX:-/opt/lanlauncherng}"
BIN_LINK="${BIN_LINK:-/usr/local/bin/lanlauncherng}"
DESKTOP_FILE="/usr/share/applications/lanlauncherng.desktop"
PIXMAP_ICON="/usr/share/pixmaps/lanlauncherng.png"
DESKTOP_SHORTCUT_NAME="LANLauncherNG.desktop"
ROOT_DESKTOP_DIR="/root/Desktop"
SYSTEM_PYTHON_BIN="${SYSTEM_PYTHON_BIN:-python3}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PAYLOAD_DIR="$SCRIPT_DIR/lanlauncherng"

copy_optional_asset() {
  local source_name="$1"
  local target_rel="$2"
  local source_path="$SCRIPT_DIR/$source_name"
  local target_path="$PREFIX/$target_rel"

  if [[ -f "$source_path" ]]; then
    mkdir -p "$(dirname "$target_path")"
    cp -f "$source_path" "$target_path"
  fi
}

warn_if_missing_resilio_binary() {
  local source_path="$SCRIPT_DIR/rslsync"
  if [[ ! -f "$source_path" ]]; then
    echo "Warning: Resilio mode needs a local rslsync binary; place rslsync next to install.sh before installing if you plan to use Resilio." >&2
    echo "Warnung: Der Resilio-Modus benötigt ein lokales rslsync-Binärprogramm; lege rslsync vor der Installation neben install.sh, wenn du Resilio verwenden möchtest." >&2
  fi
}

if [[ ! -d "$PAYLOAD_DIR" ]]; then
  echo "Payload directory not found: $PAYLOAD_DIR" >&2
  exit 1
fi

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run installer as root (sudo)." >&2
  exit 1
fi

mkdir -p "$PREFIX"
cp -a "$PAYLOAD_DIR"/. "$PREFIX"/
warn_if_missing_resilio_binary
copy_optional_asset "rslsync" "vendor/bin/linux-x64/rslsync"
copy_optional_asset "llng.btskey" "vendor/licenses/resilio/llng.btskey"
copy_optional_asset "bootstrap.json" "config/optional-bootstrap.json"

if ! command -v "$SYSTEM_PYTHON_BIN" >/dev/null 2>&1; then
  echo "System Python interpreter not found: $SYSTEM_PYTHON_BIN" >&2
  exit 1
fi
# Rebuild runtime venv on the target Linux host so interpreter/kernel ABI
# always matches the installed system and not the packaging machine.
rm -rf "$PREFIX/.venv-runtime-lin"
"$SYSTEM_PYTHON_BIN" -m venv --without-pip --copies "$PREFIX/.venv-runtime-lin"
if [[ ! -x "$PREFIX/.venv-runtime-lin/bin/python" ]]; then
  echo "Runtime venv creation failed: $PREFIX/.venv-runtime-lin/bin/python" >&2
  exit 1
fi

chmod +x "$PREFIX/run.sh" || true
chmod +x "$PREFIX/scripts/wrappers/linux/run-cmd-wrapper.sh" || true
chmod +x "$PREFIX/vendor/bin/linux-x64/rslsync" || true
chmod +x "$PREFIX/vendor/bin/linux-x64/ouisync" || true

# Reinstall/update can leave runtime-writable paths root-owned after elevated swaps.
# Ensure launcher user can write DB/settings/cache paths without manual repair.
if [[ -n "${SUDO_USER:-}" && "$SUDO_USER" != "root" ]]; then
  APP_OWNER_GROUP="$(id -gn "$SUDO_USER" 2>/dev/null || echo "$SUDO_USER")"
  for rel in data config; do
    target="$PREFIX/$rel"
    if [[ -e "$target" ]]; then
      chown -R "$SUDO_USER":"$APP_OWNER_GROUP" "$target" || true
      chmod -R u+rwX "$target" || true
    fi
  done
  # Resilio writes config.json through an atomic sibling-file replacement.
  # Keep its directory writable for the launcher account as well as the file.
  RESILIO_CONFIG_DIR="$PREFIX/config/resilio"
  if [[ -d "$RESILIO_CONFIG_DIR" ]]; then
    chown -R "$SUDO_USER":"$APP_OWNER_GROUP" "$RESILIO_CONFIG_DIR" || true
    chmod -R u+rwX "$RESILIO_CONFIG_DIR" || true
  fi
fi

ln -sf "$PREFIX/run.sh" "$BIN_LINK"
if [[ -f "$PREFIX/app/src/frontend/assets/icons/lanlauncherng.png" ]]; then
  install -m 0644 "$PREFIX/app/src/frontend/assets/icons/lanlauncherng.png" "$PIXMAP_ICON"
fi

write_desktop_entry() {
  local target_file="$1"
  cat > "$target_file" <<EOF
[Desktop Entry]
Type=Application
Name=LANLauncherNG
Exec=$PREFIX/run.sh
Terminal=false
Icon=lanlauncherng
Categories=Game;Network;
EOF
}

write_desktop_entry "$DESKTOP_FILE"
chmod 0755 "$DESKTOP_FILE"

if [[ -n "${SUDO_USER:-}" && "$SUDO_USER" != "root" ]]; then
  SUDO_HOME="$(getent passwd "$SUDO_USER" | cut -d: -f6 || true)"
  if [[ -n "$SUDO_HOME" ]]; then
    USER_DESKTOP_DIR="$SUDO_HOME/Desktop"
    mkdir -p "$USER_DESKTOP_DIR"
    USER_DESKTOP_FILE="$USER_DESKTOP_DIR/$DESKTOP_SHORTCUT_NAME"
    write_desktop_entry "$USER_DESKTOP_FILE"
    chmod 0755 "$USER_DESKTOP_FILE"
    chown "$SUDO_USER":"$SUDO_USER" "$USER_DESKTOP_FILE" || true
  fi
fi

mkdir -p "$ROOT_DESKTOP_DIR"
ROOT_DESKTOP_FILE="$ROOT_DESKTOP_DIR/$DESKTOP_SHORTCUT_NAME"
write_desktop_entry "$ROOT_DESKTOP_FILE"
chmod 0755 "$ROOT_DESKTOP_FILE"

echo "Installed LANLauncherNG to $PREFIX"
echo "Start with: $BIN_LINK"
