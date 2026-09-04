#!/usr/bin/env bash
# Offline test suite - no hardware, no harness required.
cd "$(dirname "$0")/.." || exit 1
PY="../tools/.venv/bin/python"
[ -x "$PY" ] || PY="python3"
exec "$PY" -m unittest discover -s tests "$@"
