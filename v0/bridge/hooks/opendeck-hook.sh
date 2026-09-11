#!/usr/bin/env bash
# Open Deck - Claude Code hook forwarder.
#
# Claude Code pipes the hook payload as JSON on stdin. We add the tmux target
# of the pane the agent is running in - that is what lets the deck attribute
# state to a specific pane - and POST it to the local daemon.
#
# Two rules, in order of importance:
#   1. NEVER block the agent. Fire-and-forget with a hard timeout.
#   2. NEVER fail the hook. Always exit 0, even with the daemon down.
#
# Usage in settings.json:  opendeck-hook.sh <EventName>

EVENT="${1:-unknown}"
PORT="${OPENDECK_HOOK_PORT:-8787}"
PAYLOAD=$(cat)

TARGET=""
if [ -n "$TMUX" ]; then
  TARGET=$(tmux display-message -p '#S:#I.#P' 2>/dev/null)
fi

BODY=""
if command -v jq >/dev/null 2>&1; then
  BODY=$(printf '%s' "$PAYLOAD" | jq -c \
    --arg t "$TARGET" --arg e "$EVENT" \
    '. + {tmux_target: $t, hook_event_name: $e}' 2>/dev/null)
fi
# jq missing, or the payload was not valid JSON - send a minimal envelope.
if [ -z "$BODY" ]; then
  BODY=$(printf '{"hook_event_name":"%s","tmux_target":"%s"}' "$EVENT" "$TARGET")
fi

curl -s -m 1 -X POST -H 'Content-Type: application/json' \
  -d "$BODY" "http://127.0.0.1:${PORT}/${EVENT}" >/dev/null 2>&1 &

exit 0
