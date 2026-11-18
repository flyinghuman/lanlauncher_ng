#!/usr/bin/env sh
set -eu

MANIFEST_PATH=""
CURRENT_VERSION=""
TARGET_VERSION=""
SESSION_ID=""
PAYLOAD_PATH=""
PAYLOAD_SHA256=""
INSTALL_MODE="noop"
INSTALL_TARGET_PATH=""
PRESERVE_PATHS_CSV="data"
HEALTH_CHECK_TYPE="none"
HEALTH_CHECK_PATH=""
REPO_ROOT=""
ELEVATED_CHILD="0"
RESOLVED_TARGET_PATH=""
OWNER_UID="${LLNG_UPDATER_OWNER_UID:-${SUDO_UID:-}}"
OWNER_GID="${LLNG_UPDATER_OWNER_GID:-${SUDO_GID:-}}"

while [ "$#" -gt 0 ]; do
  case "$1" in
    --manifest-path)
      MANIFEST_PATH="$2"
      shift 2
      ;;
    --current-version)
      CURRENT_VERSION="$2"
      shift 2
      ;;
    --target-version)
      TARGET_VERSION="$2"
      shift 2
      ;;
    --session-id)
      SESSION_ID="$2"
      shift 2
      ;;
    --payload-path)
      PAYLOAD_PATH="$2"
      shift 2
      ;;
    --payload-sha256)
      PAYLOAD_SHA256="$2"
      shift 2
      ;;
    --install-mode)
      INSTALL_MODE="$2"
      shift 2
      ;;
    --install-target-path)
      INSTALL_TARGET_PATH="$2"
      shift 2
      ;;
    --preserve-paths-csv)
      PRESERVE_PATHS_CSV="$2"
      shift 2
      ;;
    --health-check-type)
      HEALTH_CHECK_TYPE="$2"
      shift 2
      ;;
    --health-check-path)
      HEALTH_CHECK_PATH="$2"
      shift 2
      ;;
    --repo-root)
      REPO_ROOT="$2"
      shift 2
      ;;
    --elevated-child)
      ELEVATED_CHILD="1"
      shift 1
      ;;
    *)
      echo "[updater] unknown arg: $1"
      exit 2
      ;;
  esac
done

echo "[updater] start session=${SESSION_ID} current=${CURRENT_VERSION} target=${TARGET_VERSION}"
if [ ! -f "$MANIFEST_PATH" ]; then
  echo "[updater] manifest missing: $MANIFEST_PATH"
  exit 3
fi
if [ ! -e "$PAYLOAD_PATH" ]; then
  echo "[updater] payload missing: $PAYLOAD_PATH"
  exit 4
fi

if command -v sha256sum >/dev/null 2>&1; then
  ACTUAL_SHA256="$(sha256sum "$PAYLOAD_PATH" | awk '{print $1}')"
elif command -v shasum >/dev/null 2>&1; then
  ACTUAL_SHA256="$(shasum -a 256 "$PAYLOAD_PATH" | awk '{print $1}')"
else
  echo "[updater] no sha256 tool available"
  exit 5
fi
if [ "$ACTUAL_SHA256" != "$PAYLOAD_SHA256" ]; then
  echo "[updater] payload checksum mismatch expected=$PAYLOAD_SHA256 actual=$ACTUAL_SHA256"
  exit 6
fi

echo "[updater] payload checksum verified"

JOURNAL_DIR="${REPO_ROOT}/data/update"
LOCK_DIR="${JOURNAL_DIR}/updater.lock.d"
JOURNAL_PATH="${JOURNAL_DIR}/last-run.json"
JOURNAL_SESSION_PATH="${JOURNAL_DIR}/session-${SESSION_ID}.json"
STAGING_DIR="${JOURNAL_DIR}/staging/${SESSION_ID}"
BACKUP_ROOT="${JOURNAL_DIR}/backup"
BACKUP_ROOT_DEFAULT="$BACKUP_ROOT"
BACKUP_DIR="${BACKUP_ROOT}/${SESSION_ID}"
BACKUP_OUTSIDE_TARGET="0"

ensure_journal_dirs() {
  mkdir -p "$JOURNAL_DIR"
  mkdir -p "$BACKUP_ROOT"
}

write_journal() {
  PHASE="$1"
  STATUS="$2"
  DETAIL="$3"
  NOW_UTC="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  cat > "$JOURNAL_PATH" <<EOF
{
  "platform": "linux",
  "session_id": "$SESSION_ID",
  "phase": "$PHASE",
  "status": "$STATUS",
  "detail": "$DETAIL",
  "current_version": "$CURRENT_VERSION",
  "target_version": "$TARGET_VERSION",
  "manifest_path": "$MANIFEST_PATH",
  "payload_path": "$PAYLOAD_PATH",
  "payload_sha256": "$PAYLOAD_SHA256",
  "install_mode": "$INSTALL_MODE",
  "install_target_path": "$INSTALL_TARGET_PATH",
  "resolved_target_path": "$RESOLVED_TARGET_PATH",
  "preserve_paths_csv": "$PRESERVE_PATHS_CSV",
  "health_check_type": "$HEALTH_CHECK_TYPE",
  "health_check_path": "$HEALTH_CHECK_PATH",
  "timestamp_utc": "$NOW_UTC"
}
EOF
  cp "$JOURNAL_PATH" "$JOURNAL_SESSION_PATH"
}

resolve_target_path() {
  RAW="$1"
  if [ -z "$RAW" ]; then
    echo ""
    return
  fi
  case "$RAW" in
    /*) printf '%s' "$RAW" ;;
    *) printf '%s' "${REPO_ROOT}/$RAW" ;;
  esac
}

path_is_within() {
  CHILD="$1"
  PARENT="$2"
  [ -n "$CHILD" ] || return 1
  [ -n "$PARENT" ] || return 1
  case "${CHILD}/" in
    "${PARENT}/"*) return 0 ;;
    *) return 1 ;;
  esac
}

can_write_dir() {
  DIR_PATH="$1"
  mkdir -p "$DIR_PATH" 2>/dev/null || return 1
  PROBE="${DIR_PATH}/.llng-write-test-$$-$(date +%s).tmp"
  (umask 022 && : > "$PROBE") 2>/dev/null || return 1
  rm -f "$PROBE" 2>/dev/null || true
  return 0
}

requires_elevation() {
  TARGET="$1"
  if [ -z "$TARGET" ]; then
    return 1
  fi
  if [ -e "$TARGET" ]; then
    PARENT="$(dirname "$TARGET")"
    can_write_dir "$PARENT" || return 0
    return 1
  fi
  PARENT="$(dirname "$TARGET")"
  can_write_dir "$PARENT" || return 0
  return 1
}

reexec_elevated() {
  CURRENT_UID="$(id -u)"
  CURRENT_GID="$(id -g)"
  if command -v pkexec >/dev/null 2>&1; then
    pkexec env LLNG_UPDATER_ELEVATED_CHILD=1 LLNG_UPDATER_OWNER_UID="$CURRENT_UID" LLNG_UPDATER_OWNER_GID="$CURRENT_GID" sh "$0" \
      --manifest-path "$MANIFEST_PATH" \
      --current-version "$CURRENT_VERSION" \
      --target-version "$TARGET_VERSION" \
      --session-id "$SESSION_ID" \
      --payload-path "$PAYLOAD_PATH" \
      --payload-sha256 "$PAYLOAD_SHA256" \
      --install-mode "$INSTALL_MODE" \
      --install-target-path "$INSTALL_TARGET_PATH" \
      --preserve-paths-csv "$PRESERVE_PATHS_CSV" \
      --health-check-type "$HEALTH_CHECK_TYPE" \
      --health-check-path "$HEALTH_CHECK_PATH" \
      --repo-root "$REPO_ROOT" \
      --elevated-child
    return $?
  fi
  if command -v sudo >/dev/null 2>&1; then
    sudo LLNG_UPDATER_ELEVATED_CHILD=1 LLNG_UPDATER_OWNER_UID="$CURRENT_UID" LLNG_UPDATER_OWNER_GID="$CURRENT_GID" sh "$0" \
      --manifest-path "$MANIFEST_PATH" \
      --current-version "$CURRENT_VERSION" \
      --target-version "$TARGET_VERSION" \
      --session-id "$SESSION_ID" \
      --payload-path "$PAYLOAD_PATH" \
      --payload-sha256 "$PAYLOAD_SHA256" \
      --install-mode "$INSTALL_MODE" \
      --install-target-path "$INSTALL_TARGET_PATH" \
      --preserve-paths-csv "$PRESERVE_PATHS_CSV" \
      --health-check-type "$HEALTH_CHECK_TYPE" \
      --health-check-path "$HEALTH_CHECK_PATH" \
      --repo-root "$REPO_ROOT" \
      --elevated-child
    return $?
  fi
  return 12
}

restore_user_owner_if_known() {
  TARGET_PATH="$1"
  if [ -z "$TARGET_PATH" ] || [ ! -e "$TARGET_PATH" ]; then
    return
  fi
  if [ -z "${OWNER_UID:-}" ] || [ -z "${OWNER_GID:-}" ]; then
    return
  fi
  chown -R "${OWNER_UID}:${OWNER_GID}" "$TARGET_PATH" 2>/dev/null || true
  chmod -R u+rwX "$TARGET_PATH" 2>/dev/null || true
}

strip_nested_updater_state_from_backup() {
  BACKUP_ROOT_PATH="$1"
  [ -n "$BACKUP_ROOT_PATH" ] || return 0
  [ -d "$BACKUP_ROOT_PATH" ] || return 0
  # Keep exactly one rollback snapshot. Older updater runtime state inside the
  # moved install root would otherwise recurse into the next preserved backup.
  rm -rf "${BACKUP_ROOT_PATH}/data/update"
}

copy_preserved_path() {
  FROM_PATH="$1"
  TO_PATH="$2"
  REL_TRIM="$3"
  [ -e "$FROM_PATH" ] || return 0
  mkdir -p "$(dirname "$TO_PATH")"
  rm -rf "$TO_PATH"
  cp -a "$FROM_PATH" "$TO_PATH"
  if [ "$REL_TRIM" = "data" ]; then
    rm -rf "${TO_PATH}/update"
  fi
}

resolve_staged_root() {
  ROOT="$1"
  CHILD_COUNT="$(find "$ROOT" -mindepth 1 -maxdepth 1 | wc -l | awk '{print $1}')"
  if [ "$CHILD_COUNT" = "1" ]; then
    ONLY_CHILD="$(find "$ROOT" -mindepth 1 -maxdepth 1 | head -n 1)"
    if [ -d "$ONLY_CHILD" ]; then
      printf '%s' "$ONLY_CHILD"
      return
    fi
  fi
  printf '%s' "$ROOT"
}

ensure_run_sh_present() {
  TARGET_ROOT="$1"
  BACKUP_ROOT_PATH="$2"
  RUN_SH_PATH="${TARGET_ROOT}/run.sh"
  if [ -f "$RUN_SH_PATH" ]; then
    return 0
  fi
  if [ -f "${BACKUP_ROOT_PATH}/run.sh" ]; then
    cp -a "${BACKUP_ROOT_PATH}/run.sh" "$RUN_SH_PATH"
    chmod +x "$RUN_SH_PATH" 2>/dev/null || true
    return 0
  fi
  cat > "$RUN_SH_PATH" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
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
  exit 1
fi
export PYTHONPATH="app"
.venv-runtime-lin/bin/python -m src.core.main --config config/core.json
SH
  chmod +x "$RUN_SH_PATH" 2>/dev/null || true
}

extract_payload_to_staging() {
  rm -rf "$STAGING_DIR"
  mkdir -p "$STAGING_DIR"
  EXTRACT_ROOT="${STAGING_DIR}/payload"
  mkdir -p "$EXTRACT_ROOT"

  if [ -d "$PAYLOAD_PATH" ]; then
    cp -R "$PAYLOAD_PATH" "${EXTRACT_ROOT}/content"
    resolve_staged_root "${EXTRACT_ROOT}/content"
    return
  fi

  case "$PAYLOAD_PATH" in
    *.zip)
      if ! command -v unzip >/dev/null 2>&1; then
        echo "[updater] unzip not available"
        exit 13
      fi
      unzip -q "$PAYLOAD_PATH" -d "$EXTRACT_ROOT"
      ;;
    *.tar|*.tar.gz|*.tgz)
      if ! command -v tar >/dev/null 2>&1; then
        echo "[updater] tar not available"
        exit 14
      fi
      tar -xf "$PAYLOAD_PATH" -C "$EXTRACT_ROOT"
      ;;
    *)
      echo "[updater] unsupported payload format for directory_swap: $PAYLOAD_PATH"
      exit 15
      ;;
  esac
  resolve_staged_root "$EXTRACT_ROOT"
}

post_update_health_ok() {
  BASE_PATH="$1"
  if [ "$HEALTH_CHECK_TYPE" = "none" ]; then
    return 0
  fi
  if [ "$HEALTH_CHECK_TYPE" = "file_exists" ]; then
    [ -n "$HEALTH_CHECK_PATH" ] || return 1
    case "$HEALTH_CHECK_PATH" in
      /*) CHECK_PATH="$HEALTH_CHECK_PATH" ;;
      *) CHECK_PATH="${BASE_PATH}/${HEALTH_CHECK_PATH}" ;;
    esac
    [ -f "$CHECK_PATH" ] || return 1
    return 0
  fi
  return 1
}

prune_backup_history() {
  KEEP_SESSION="$1"
  KEPT="0"
  for DIR in $(ls -1dt "$BACKUP_ROOT"/* 2>/dev/null || true); do
    [ -d "$DIR" ] || continue
    HAS_CURRENT="0"
    [ -d "$DIR/current" ] && HAS_CURRENT="1"
    if [ "$(basename "$DIR")" = "$KEEP_SESSION" ] && [ "$HAS_CURRENT" = "1" ]; then
      KEPT="1"
      continue
    fi
    if [ "$HAS_CURRENT" = "1" ] && [ "$KEPT" = "0" ]; then
      KEPT="1"
      continue
    fi
    rm -rf "$DIR"
  done
}

if [ "$INSTALL_MODE" = "directory_swap" ]; then
  [ -n "$INSTALL_TARGET_PATH" ] || { echo "[updater] install target missing"; exit 8; }
  RESOLVED_TARGET_PATH="$(resolve_target_path "$INSTALL_TARGET_PATH")"
  if path_is_within "$JOURNAL_DIR" "$RESOLVED_TARGET_PATH"; then
    RUNTIME_ROOT="$(dirname "$RESOLVED_TARGET_PATH")/.llng-update-runtime/${SESSION_ID}"
    JOURNAL_DIR="${RUNTIME_ROOT}/data/update"
    LOCK_DIR="${JOURNAL_DIR}/updater.lock.d"
    JOURNAL_PATH="${JOURNAL_DIR}/last-run.json"
    JOURNAL_SESSION_PATH="${JOURNAL_DIR}/session-${SESSION_ID}.json"
    STAGING_DIR="${JOURNAL_DIR}/staging/${SESSION_ID}"
    BACKUP_ROOT="${JOURNAL_DIR}/backup"
    BACKUP_ROOT_DEFAULT="$BACKUP_ROOT"
    BACKUP_OUTSIDE_TARGET="1"
  fi
  # Backup path cannot live below target when doing full-directory rename swap.
  if path_is_within "$BACKUP_ROOT_DEFAULT" "$RESOLVED_TARGET_PATH"; then
    BACKUP_ROOT="$(dirname "$RESOLVED_TARGET_PATH")/.llng-update-backup"
    BACKUP_OUTSIDE_TARGET="1"
  fi
  BACKUP_DIR="${BACKUP_ROOT}/${SESSION_ID}"
  if requires_elevation "$RESOLVED_TARGET_PATH"; then
    if [ "$(id -u)" -ne 0 ]; then
      if [ "$ELEVATED_CHILD" = "1" ] || [ "${LLNG_UPDATER_ELEVATED_CHILD:-0}" = "1" ]; then
        echo "[updater] elevated child is not running as root"
        exit 12
      fi
      echo "[updater] requesting elevation for target: $RESOLVED_TARGET_PATH"
      if reexec_elevated; then
        exit 0
      fi
      echo "[updater] elevation denied"
      exit 12
    fi
  fi
fi

ensure_journal_dirs
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  echo "[updater] install lock active: $LOCK_DIR"
  write_journal "lock" "failed" "lock_active"
  exit 7
fi
trap 'rmdir "$LOCK_DIR" 2>/dev/null || true' EXIT
write_journal "lock" "ok" "lock_acquired"
write_journal "verify" "ok" "payload_checksum_verified"

STAGED_ROOT="$(extract_payload_to_staging)"
write_journal "stage" "ok" "payload_staged"
PAYLOAD_HAS_RUN_SH="0"
[ -f "${STAGED_ROOT}/run.sh" ] && PAYLOAD_HAS_RUN_SH="1"

mkdir -p "$BACKUP_DIR"
BACKUP_CURRENT="${BACKUP_DIR}/current"
SWAPPED="0"

if [ "$INSTALL_MODE" = "directory_swap" ]; then
  if [ -z "$RESOLVED_TARGET_PATH" ]; then
    RESOLVED_TARGET_PATH="$(resolve_target_path "$INSTALL_TARGET_PATH")"
  fi
  mkdir -p "$(dirname "$RESOLVED_TARGET_PATH")"
  rm -rf "$BACKUP_CURRENT"
  if [ -e "$RESOLVED_TARGET_PATH" ]; then
    mv "$RESOLVED_TARGET_PATH" "$BACKUP_CURRENT"
    strip_nested_updater_state_from_backup "$BACKUP_CURRENT"
  fi
  write_journal "backup" "ok" "backup_created"

  if mv "$STAGED_ROOT" "$RESOLVED_TARGET_PATH"; then
    SWAPPED="1"
    OLD_IFS="$IFS"
    IFS=","
    for REL in $PRESERVE_PATHS_CSV; do
      IFS="$OLD_IFS"
      REL_TRIM="$(printf '%s' "$REL" | sed 's/^ *//;s/ *$//')"
      [ -n "$REL_TRIM" ] || { IFS=","; continue; }
      case "$REL_TRIM" in
        /*|*..*) IFS=","; continue ;;
      esac
      FROM_PATH="${BACKUP_CURRENT}/${REL_TRIM}"
      TO_PATH="${RESOLVED_TARGET_PATH}/${REL_TRIM}"
      if [ -e "$FROM_PATH" ]; then
        copy_preserved_path "$FROM_PATH" "$TO_PATH" "$REL_TRIM"
        restore_user_owner_if_known "$TO_PATH"
      fi
      IFS=","
    done
    IFS="$OLD_IFS"

    # The package ships config templates as root-owned files after an elevated
    # directory swap. The launcher must be able to persist Resilio's resolved
    # storage_path and pid_file under config/resilio at the next start.
    restore_user_owner_if_known "${RESOLVED_TARGET_PATH}/config"
    # Resilio replaces config.json atomically through a sibling temporary file,
    # so write access to the file alone is not sufficient.
    restore_user_owner_if_known "${RESOLVED_TARGET_PATH}/config/resilio"

    if ensure_run_sh_present "$RESOLVED_TARGET_PATH" "$BACKUP_CURRENT"; then
      if [ "$PAYLOAD_HAS_RUN_SH" != "1" ]; then
        echo "[updater] run.sh missing in payload; restored/generated fallback entrypoint"
      fi
    else
      write_journal "swap" "failed" "run_sh_missing_and_restore_failed"
      if [ -e "$BACKUP_CURRENT" ]; then
        rm -rf "$RESOLVED_TARGET_PATH"
        mv "$BACKUP_CURRENT" "$RESOLVED_TARGET_PATH" && write_journal "rollback" "ok" "rollback_complete_after_missing_run_sh" || write_journal "rollback" "failed" "rollback_failed_after_missing_run_sh"
      fi
      exit 10
    fi

    write_journal "swap" "ok" "directory_swap_complete"
    if post_update_health_ok "$RESOLVED_TARGET_PATH"; then
      write_journal "health" "ok" "health_check_passed"
      # Keep backup outside target during swap/health and relocate only after success.
      if [ "$BACKUP_OUTSIDE_TARGET" = "1" ]; then
        FINAL_BACKUP_ROOT="${RESOLVED_TARGET_PATH}/data/update/backup"
        FINAL_BACKUP_DIR="${FINAL_BACKUP_ROOT}/${SESSION_ID}"
        mkdir -p "$FINAL_BACKUP_DIR"
        FINAL_BACKUP_CURRENT="${FINAL_BACKUP_DIR}/current"
        rm -rf "$FINAL_BACKUP_CURRENT"
        mv "$BACKUP_CURRENT" "$FINAL_BACKUP_CURRENT"
        BACKUP_ROOT="$FINAL_BACKUP_ROOT"
        BACKUP_DIR="$FINAL_BACKUP_DIR"
        BACKUP_CURRENT="$FINAL_BACKUP_CURRENT"
      fi
    else
      write_journal "health" "failed" "health_check_failed"
      rm -rf "$RESOLVED_TARGET_PATH"
      if [ -e "$BACKUP_CURRENT" ]; then
        mv "$BACKUP_CURRENT" "$RESOLVED_TARGET_PATH" && write_journal "rollback" "ok" "rollback_complete_after_health" || write_journal "rollback" "failed" "rollback_failed_after_health"
      else
        write_journal "rollback" "failed" "rollback_source_missing_after_health"
      fi
      exit 11
    fi
  else
    write_journal "swap" "failed" "directory_swap_failed"
    if [ "$SWAPPED" = "1" ]; then
      rm -rf "$RESOLVED_TARGET_PATH"
    fi
    if [ -e "$BACKUP_CURRENT" ]; then
      mv "$BACKUP_CURRENT" "$RESOLVED_TARGET_PATH" && write_journal "rollback" "ok" "rollback_complete" || write_journal "rollback" "failed" "rollback_failed"
    else
      write_journal "rollback" "failed" "rollback_source_missing"
    fi
    exit 10
  fi
else
  write_journal "backup" "ok" "backup_skipped_noop"
  write_journal "swap" "ok" "swap_placeholder_complete"
fi

prune_backup_history "$SESSION_ID"
write_journal "apply" "ok" "apply_complete"
# Keep per-session snapshot for diagnostics, but clear last-run marker after success
# so stale recovery hints are not triggered by old completed runs.
rm -f "$JOURNAL_PATH" 2>/dev/null || true
echo "[updater] update apply complete"
exit 0
