#!/usr/bin/env bash
# Open Deck - Claude Code hook forwarder.
#
# Claude Code pipes the hook payload as JSON on stdin. We enrich it with the
# tmux target (so the bridge can send keys back to the right pane without
# stealing focus) and POST it to the local bridge daemon.
#
# Design rules, in order of importance:
#   1. NEVER block the agent. Fire-and-forget with a hard timeout.
#   2. NEVER fail the hook. Always exit 0, even if the bridge is down.
#
# Usage in settings.json:  opendeck-hook.sh <EventName>

EVENT="${1:-unknown}"
PORT="${OPENDECK_HOOK_PORT:-8787}"

PAYLOAD=$(cat)

# Which tmux pane is this agent running in? Empty when not under tmux.
TMUX_TARGET=""
if [ -n "$TMUX" ]; then
  TMUX_TARGET=$(tmux display-message -p '#S:#I' 2>/dev/null)
fi

if command -v jq >/dev/null 2>&1; then
  BODY=$(printf '%s' "$PAYLOAD" | jq -c \
    --arg t "$TMUX_TARGET" --arg e "$EVENT" \
    '. + {tmux_target: $t, hook_event_name: $e}' 2>/dev/null)
fi
# jq missing or the payload wasn't valid JSON - send a minimal envelope instead.
if [ -z "$BODY" ]; then
  BODY=$(printf '{"hook_event_name":"%s","tmux_target":"%s","raw":true}' \
    "$EVENT" "$TMUX_TARGET")
fi

curl -s -m 1 -X POST \
  -H 'Content-Type: application/json' \
  -d "$BODY" \
  "http://127.0.0.1:${PORT}/${EVENT}" >/dev/null 2>&1 &

exit 0
