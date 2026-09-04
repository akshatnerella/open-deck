"""Action execution: turn a profile's action spec into something happening on the host.

Three action types cover everything the deck needs:
  keystroke - simulate a key/chord (macOS: AppleScript System Events)
  shell     - run a shell command (tmux window switching, launching agents)
  text      - type a literal string, optionally followed by Return
"""

from __future__ import annotations

import logging
import shlex
import subprocess

log = logging.getLogger("opendeck.actions")

# AppleScript key codes for keys that aren't plain characters.
_KEY_CODES = {
    "return": 36, "enter": 36, "tab": 48, "space": 49, "delete": 51,
    "escape": 53, "esc": 53, "left": 123, "right": 124, "down": 125, "up": 126,
    "f1": 122, "f2": 120, "f3": 99, "f4": 118, "f5": 96, "f6": 97,
    "home": 115, "end": 119, "pageup": 116, "pagedown": 121,
}
_MODIFIERS = {
    "cmd": "command down", "command": "command down",
    "ctrl": "control down", "control": "control down",
    "alt": "option down", "opt": "option down", "option": "option down",
    "shift": "shift down",
}


def _osascript(script: str) -> None:
    try:
        subprocess.run(["osascript", "-e", script], check=True,
                       capture_output=True, timeout=5)
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode(errors="replace").strip()
        if "not allowed assistive access" in stderr or "1002" in stderr:
            log.error("Accessibility permission missing. Grant your terminal app "
                      "Accessibility access in System Settings > Privacy & Security "
                      "> Accessibility, then restart it.")
        else:
            log.error("osascript failed: %s", stderr)
    except subprocess.TimeoutExpired:
        log.error("osascript timed out")


def keystroke(keys: list[str]) -> None:
    """Send one key or chord. `keys` is e.g. ["escape"] or ["cmd", "shift", "p"]."""
    if not keys:
        return
    mods = [_MODIFIERS[k.lower()] for k in keys[:-1] if k.lower() in _MODIFIERS]
    key = keys[-1].lower()
    using = f" using {{{', '.join(mods)}}}" if mods else ""

    if key in _KEY_CODES:
        script = f'tell application "System Events" to key code {_KEY_CODES[key]}{using}'
    else:
        script = (f'tell application "System Events" to keystroke '
                  f'"{key.replace(chr(92), chr(92)*2).replace(chr(34), chr(92)+chr(34))}"{using}')
    _osascript(script)


def type_text(text: str, submit: bool = False) -> None:
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    _osascript(f'tell application "System Events" to keystroke "{escaped}"')
    if submit:
        keystroke(["return"])


def shell(command: str) -> None:
    try:
        subprocess.run(command, shell=True, check=False,
                       capture_output=True, timeout=10)
    except subprocess.TimeoutExpired:
        log.error("shell command timed out: %s", command)


def focus_target(target: str) -> None:
    """Bring an agent's terminal to the foreground.

    Supports tmux targets ("tmux:session:window") and raw shell commands.
    """
    if not target:
        return
    if target.startswith("tmux:"):
        shell(f"tmux select-window -t {shlex.quote(target[5:])}")
    else:
        shell(target)


def run(action: dict, context: dict | None = None) -> None:
    """Execute one action dict from a profile."""
    if not action:
        return
    ctx = context or {}
    kind = action.get("type")

    if kind == "keystroke":
        keystroke(action.get("keys", []))
    elif kind == "shell":
        cmd = action.get("command", "")
        for k, v in ctx.items():
            cmd = cmd.replace(f"{{{k}}}", str(v))
        shell(cmd)
    elif kind == "text":
        type_text(action.get("text", ""), submit=action.get("submit", False))
    elif kind == "focus":
        focus_target(ctx.get("target", ""))
    elif kind == "none":
        pass
    else:
        log.warning("unknown action type: %r", kind)
