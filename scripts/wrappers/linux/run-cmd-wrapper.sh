#!/usr/bin/env bash
set -euo pipefail

RUNTIME="wine"
RUNTIME_BINARY=""
COMPAT_DATA_PATH=""
HOLD_OPEN_ALWAYS=0

_resolve_steam_client_install_path() {
  local runtime_binary="${1:-}"
  local home_dir
  home_dir="${HOME:-$(getent passwd "$(id -u)" | cut -d: -f6 2>/dev/null || echo "")}"
  if [[ -z "$home_dir" ]]; then
    return
  fi

  local runtime_path=""
  if [[ "$runtime_binary" == */* ]]; then
    runtime_path="$(realpath -m "$runtime_binary" 2>/dev/null || echo "$runtime_binary")"
  else
    runtime_path="$(command -v "$runtime_binary" 2>/dev/null || true)"
  fi

  if [[ "$runtime_path" == *"/compatibilitytools.d/"*"/proton" ]]; then
    printf "%s\n" "${runtime_path%/compatibilitytools.d/*}"
    return
  fi
  if [[ "$runtime_path" == *"/steamapps/common/"*"/proton" ]]; then
    printf "%s\n" "${runtime_path%/steamapps/common/*}"
    return
  fi

  local candidates=(
    "$home_dir/.steam/root"
    "$home_dir/.local/share/Steam"
    "$home_dir/.steam/steam"
    "$home_dir/.var/app/com.valvesoftware.Steam/.local/share/Steam"
  )
  local candidate
  for candidate in "${candidates[@]}"; do
    if [[ -d "$candidate/steamapps" ]]; then
      printf "%s\n" "$candidate"
      return
    fi
  done
}

_maybe_hold_terminal() {
  local exit_code="${1:-1}"
  local reason="${2:-failed}"
  local hold_enabled="${LLNG_WRAPPER_HOLD_ON_FAIL:-1}"
  local hold_seconds="${LLNG_WRAPPER_HOLD_ON_FAIL_SECONDS:-15}"

  if [[ "$hold_enabled" == "0" ]]; then
    return
  fi
  if [[ ! "$hold_seconds" =~ ^[0-9]+$ ]]; then
    hold_seconds=15
  fi
  if (( hold_seconds <= 0 )); then
    return
  fi
  if [[ ! -t 0 || ! -t 1 ]]; then
    return
  fi

  if [[ "$reason" == "finished" ]]; then
    echo "process finished (exit=${exit_code}). press any key to stop auto-close countdown."
  else
    echo "launch failed (exit=${exit_code}). press any key to stop auto-close countdown."
  fi
  local remaining=$hold_seconds
  while (( remaining > 0 )); do
    printf "\rclosing this terminal in %2ds ... " "$remaining"
    if IFS= read -r -s -n 1 -t 1 _; then
      printf "\ncountdown stopped. press Enter to close this terminal.\n"
      IFS= read -r _
      printf "\n"
      return
    fi
    ((remaining--))
  done
  printf "\n"
}

_fail_and_exit() {
  local code="$1"
  local message="$2"
  echo "$message" >&2
  _maybe_hold_terminal "$code"
  exit "$code"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --runtime)
      RUNTIME="${2:-}"
      shift 2
      ;;
    --runtime-binary)
      RUNTIME_BINARY="${2:-}"
      shift 2
      ;;
    --compat-data-path)
      COMPAT_DATA_PATH="${2:-}"
      shift 2
      ;;
    --hold-open)
      HOLD_OPEN_ALWAYS=1
      shift
      ;;
    --)
      shift
      break
      ;;
    *)
      break
      ;;
  esac
done

if [[ $# -lt 1 ]]; then
  _fail_and_exit 2 "usage: $0 [--runtime <wine|proton|proton-ge>] [--runtime-binary <path-or-cmd>] [--compat-data-path <path>] [--hold-open] <path-to-cmd-script> [args...]"
fi

CMD_SCRIPT="$1"
shift || true

if [[ ! -f "$CMD_SCRIPT" ]]; then
  _fail_and_exit 3 "cmd script not found: $CMD_SCRIPT"
fi

if [[ -z "$RUNTIME_BINARY" ]]; then
  if [[ "$RUNTIME" == "wine" ]]; then
    RUNTIME_BINARY="wine"
  else
    RUNTIME_BINARY="proton"
  fi
fi

if [[ "$RUNTIME_BINARY" == */* ]]; then
  if [[ ! -x "$RUNTIME_BINARY" ]]; then
    _fail_and_exit 4 "runtime binary is missing or not executable: $RUNTIME_BINARY"
  fi
else
  if ! command -v "$RUNTIME_BINARY" >/dev/null 2>&1; then
    _fail_and_exit 4 "runtime binary not found in PATH: $RUNTIME_BINARY"
  fi
fi

# Run legacy Windows launcher scripts when no native *.sh launcher exists.
set +e
if [[ "$RUNTIME" == "wine" ]]; then
  if [[ -n "$COMPAT_DATA_PATH" ]]; then
    mkdir -p "$COMPAT_DATA_PATH"
    export WINEPREFIX="$COMPAT_DATA_PATH"
  fi
  "$RUNTIME_BINARY" cmd /c "$CMD_SCRIPT" "$@"
  exit_code=$?
else
  if [[ -n "$COMPAT_DATA_PATH" ]]; then
    mkdir -p "$COMPAT_DATA_PATH"
    export STEAM_COMPAT_DATA_PATH="$COMPAT_DATA_PATH"
  fi
  if [[ -z "${STEAM_COMPAT_CLIENT_INSTALL_PATH:-}" ]]; then
    steam_client_install_path="$(_resolve_steam_client_install_path "$RUNTIME_BINARY")"
    if [[ -n "$steam_client_install_path" ]]; then
      export STEAM_COMPAT_CLIENT_INSTALL_PATH="$steam_client_install_path"
    fi
  fi
  "$RUNTIME_BINARY" run cmd /c "$CMD_SCRIPT" "$@"
  exit_code=$?
fi
set -e

if (( exit_code != 0 )); then
  echo "runtime launch failed: runtime=${RUNTIME} binary=${RUNTIME_BINARY} exit=${exit_code}" >&2
fi
if (( exit_code != 0 || HOLD_OPEN_ALWAYS != 0 )); then
  if (( exit_code == 0 )); then
    _maybe_hold_terminal "$exit_code" "finished"
  else
    _maybe_hold_terminal "$exit_code" "failed"
  fi
fi
exit "$exit_code"
