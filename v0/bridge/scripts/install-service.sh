#!/usr/bin/env bash
# Install the Open Deck daemon as a login service.
#
#   ./scripts/install-service.sh [launch-command]
#
# Re-running is safe: the service is unloaded and reloaded in place.
set -euo pipefail

BRIDGE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
COMMAND="${1:-claude}"
LABEL="com.opendeck.bridge"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG_DIR="$HOME/Library/Logs"

find_python() {
  local dir="$BRIDGE_DIR"
  while [ "$dir" != "/" ]; do
    [ -x "$dir/.venv/bin/python" ] && { echo "$dir/.venv/bin/python"; return; }
    dir="$(dirname "$dir")"
  done
  echo "no .venv found - run: python3 -m venv .venv && .venv/bin/pip install pyserial" >&2
  exit 1
}

PYTHON="$(find_python)"
mkdir -p "$HOME/Library/LaunchAgents" "$LOG_DIR"

sed -e "s|__PYTHON__|$PYTHON|g" \
    -e "s|__COMMAND__|$COMMAND|g" \
    -e "s|__BRIDGE_DIR__|$BRIDGE_DIR|g" \
    -e "s|__LOG_DIR__|$LOG_DIR|g" \
    "$BRIDGE_DIR/scripts/com.opendeck.bridge.plist" > "$PLIST"

launchctl bootout "gui/$UID/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$UID" "$PLIST"

echo "installed:  $PLIST"
echo "python:     $PYTHON"
echo "command:    $COMMAND"
echo "logs:       $LOG_DIR/opendeck.log"
echo
echo "stop:       launchctl bootout gui/$UID/$LABEL"
echo "uninstall:  launchctl bootout gui/$UID/$LABEL && rm $PLIST"
