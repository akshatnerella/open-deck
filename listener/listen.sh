#!/bin/sh
# Read key names from the deck and point tmux at the matching session.
#
# The whole idea, in one loop: the deck says "FOX", we run a tmux command.
# The deck has no idea tmux exists; this script has no idea about key matrices.
#
# Usage:  ./listen.sh [port]

PORT="${1:-$(ls /dev/cu.usbmodem* 2>/dev/null | head -1)}"

if [ -z "$PORT" ]; then
    echo "listen: no deck found. Is it plugged in?" >&2
    exit 1
fi

# A serial port is a file, but it needs configuring first: 115200 baud to match
# Serial.begin(), and "raw" so the terminal driver passes bytes through instead
# of trying to be a shell (interpreting Ctrl-C, echoing input, and so on).
stty -f "$PORT" 115200 raw -echo || exit 1

echo "listening on $PORT  (ctrl-c to stop)"

# Reading the port as a file is what makes this small: `read` blocks until a
# newline arrives, which is exactly the framing the firmware prints.
while read -r key; do
    case "$key" in
        FOX|OWL|CAT|PNDA) ;;
        *) continue ;;                  # ignore anything we do not recognise
    esac

    session=$(echo "$key" | tr '[:upper:]' '[:lower:]')

    # -A means "attach if it exists, create if it does not", so a session you
    # have never made still works on the first press. -d keeps it detached:
    # we are not a terminal, so we must not try to attach here.
    tmux new-session -A -d -s "$session" 2>/dev/null

    # switch-client only works if a terminal is actually attached to tmux.
    # With no client it fails with "no current client", so check first.
    if tmux list-clients -F '#{client_name}' 2>/dev/null | grep -q .; then
        tmux switch-client -t "$session"
        echo "$key -> $session"
    else
        echo "$key -> $session (ready; no terminal attached yet)"
    fi
done < "$PORT"
