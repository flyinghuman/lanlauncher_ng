#!/usr/bin/env bash
set -euo pipefail

VENV_PATH="${1:-.venv-runtime-lin}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "Python interpreter not found: $PYTHON_BIN" >&2
  exit 1
fi

rm -rf "$VENV_PATH"
# Use copied interpreter binaries instead of symlinks so runtime works on
# cross-mounted filesystems (for example NTFS mounts) where symlinks can break.
"$PYTHON_BIN" -m venv --without-pip --copies "$VENV_PATH"

if [[ ! -x "$VENV_PATH/bin/python" ]]; then
  echo "Runtime venv creation failed: missing executable $VENV_PATH/bin/python" >&2
  exit 1
fi

echo "Runtime venv created at: $VENV_PATH"
