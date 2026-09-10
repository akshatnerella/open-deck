#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

find_python() {
  local dir="$PWD"
  while [ "$dir" != "/" ]; do
    [ -x "$dir/.venv/bin/python" ] && { echo "$dir/.venv/bin/python"; return; }
    dir="$(dirname "$dir")"
  done
  command -v python3
}

PY="$(find_python)"
"$PY" - <<'PYCHECK'
import sys
if sys.version_info < (3, 11):
    sys.exit(f"Python 3.11+ required, found {sys.version.split()[0]}")
PYCHECK

PYTHONPATH="tests:${PYTHONPATH:-}" exec "$PY" -m unittest discover -s tests -p 'test_*.py' "$@"
