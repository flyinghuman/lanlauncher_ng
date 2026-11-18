#!/bin/sh
set -eu

repo_root=$(git rev-parse --show-toplevel)
cd "$repo_root"

if [ -x .venv/bin/python ]; then
    python=.venv/bin/python
elif [ -x .venv-dev-win/Scripts/python.exe ]; then
    python=.venv-dev-win/Scripts/python.exe
else
    printf '%s\n' 'No project Python environment found. Create .venv or .venv-dev-win first.' >&2
    exit 1
fi

printf '%s\n' 'Running Ruff autofixes and lint checks...'
"$python" -m ruff check --fix .

printf '%s\n' 'Running the full unittest suite...'
"$python" -m unittest discover -s tests -p 'test_*.py' -t .
