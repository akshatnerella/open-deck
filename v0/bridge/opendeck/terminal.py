"""Bring a tmux session onto the screen as a fullscreen terminal (macOS)."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from dataclasses import dataclass

log = logging.getLogger(__name__)

TIMEOUT = 10.0


@dataclass(frozen=True)
class TerminalApp:
    name: str
    path: str


#: Preference order; Terminal.app is the guaranteed fallback on any Mac.
KNOWN_TERMINALS = (
    TerminalApp("Ghostty", "/Applications/Ghostty.app"),
    TerminalApp("iTerm", "/Applications/iTerm.app"),
    TerminalApp("WezTerm", "/Applications/WezTerm.app"),
    TerminalApp("kitty", "/Applications/kitty.app"),
    TerminalApp("Alacritty", "/Applications/Alacritty.app"),
    TerminalApp("Terminal", "/System/Applications/Utilities/Terminal.app"),
)

_ARGV_LAUNCHERS = frozenset({"Ghostty", "WezTerm", "kitty", "Alacritty"})


def detect(preferred: str | None = None) -> TerminalApp | None:
    preferred = preferred or os.environ.get("OPENDECK_TERMINAL")
    if preferred:
        for app in KNOWN_TERMINALS:
            if app.name.lower() == preferred.lower():
                return app
        return TerminalApp(preferred, f"/Applications/{preferred}.app")
    return next((app for app in KNOWN_TERMINALS if os.path.isdir(app.path)), None)


def _osascript(script: str) -> bool:
    result = subprocess.run(
        ["osascript", "-e", script], capture_output=True, text=True, timeout=TIMEOUT
    )
    if result.returncode != 0:
        log.warning("osascript failed: %s", result.stderr.strip())
    return result.returncode == 0


class Terminal:
    """Launches and focuses the terminal emulator hosting tmux.

    Fullscreen is applied only at launch. Ghostty uses non-native fullscreen,
    so its window reports ``AXFullScreen == false`` even when fullscreen; a
    "toggle unless already fullscreen" check would exit fullscreen every time.
    """

    def __init__(self, app: TerminalApp | None = None, fullscreen: bool = True) -> None:
        self.app = app or detect()
        self.fullscreen = fullscreen

    @property
    def available(self) -> bool:
        return self.app is not None and shutil.which("osascript") is not None

    def focus(self) -> bool:
        """Raise the terminal without waiting for it.

        `osascript activate` takes ~67ms and nothing downstream depends on its
        result, so blocking the event loop on it just adds latency to every
        key press. The app's existence is validated once at startup.
        """
        if self.app is None:
            return False
        subprocess.Popen(
            ["osascript", "-e", f'tell application "{self.app.name}" to activate'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True

    def launch_attached(self, session: str) -> bool:
        if self.app is None:
            log.error("no terminal app found; set OPENDECK_TERMINAL")
            return False

        if self.app.name in _ARGV_LAUNCHERS:
            args = ["open", "-na", self.app.path, "--args"]
            if self.fullscreen and self.app.name == "Ghostty":
                args.append("--fullscreen=true")
            # The command must be separate argv entries; a single quoted string
            # opens a window that runs nothing.
            args += ["-e", "tmux", "attach", "-t", session]
            result = subprocess.run(args, capture_output=True, text=True)
            return result.returncode == 0

        return self._launch_via_applescript(session)

    def _launch_via_applescript(self, session: str) -> bool:
        assert self.app is not None
        if self.app.name == "Terminal":
            script = (
                'tell application "Terminal"\n'
                "  activate\n"
                f'  do script "tmux attach -t {session}"\n'
                "end tell"
            )
        else:
            script = (
                'tell application "iTerm"\n'
                "  activate\n"
                "  create window with default profile "
                f'command "tmux attach -t {session}"\n'
                "end tell"
            )
        if not _osascript(script):
            return False
        if self.fullscreen:
            _osascript(
                f'tell application "System Events" to tell process "{self.app.name}" '
                'to set value of attribute "AXFullScreen" of front window to true'
            )
        return True
