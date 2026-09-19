"""Finding and raising the terminal window that shows tmux (macOS).

One fullscreen window, switched between sessions. A window per session was
tried and dropped: the sessions run either way, so the extra window buys
nothing and costs a launch plus a Space animation where switching a tmux
client is immediate.

Three things here came from testing rather than docs, and all three broke a
guess worth recording, because they will break the next one too:

* **Ghostty ignores ``--fullscreen=true`` on the command line.** The flag is
  visibly in the process argv and the window still opens windowed.
* **AXFullScreen cannot be read or written across Spaces.** System Events does
  not enumerate windows on Spaces other than the current one, so a window that
  is already fullscreen reports *zero windows* and no attributes at all.
* **A window is found through tmux, not through argv.** Matching launch
  arguments only finds windows this program opened; a session attached by hand
  would be missed.

The consequence of the second point: a new window has to be fullscreened while
it is still on the current Space, and after that its state is unknowable.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time
from dataclasses import dataclass

log = logging.getLogger(__name__)

TIMEOUT = 10.0

#: How long to wait for a freshly launched window to exist before fullscreening
#: it. Measured at well under a second; the ceiling is for a cold app start.
WINDOW_WAIT = 6.0
WINDOW_POLL = 0.25

#: Activation is asynchronous; let it settle before trusting "frontmost".
FOCUS_SETTLE = 0.6


@dataclass(frozen=True)
class TerminalApp:
    name: str
    path: str
    #: Matched against a process name when walking up from a tmux client's tty.
    process: str


#: Preference order; Terminal.app is the guaranteed fallback on any Mac.
KNOWN_TERMINALS = (
    TerminalApp("Ghostty", "/Applications/Ghostty.app", "ghostty"),
    TerminalApp("iTerm", "/Applications/iTerm.app", "iTerm"),
    TerminalApp("WezTerm", "/Applications/WezTerm.app", "wezterm"),
    TerminalApp("kitty", "/Applications/kitty.app", "kitty"),
    TerminalApp("Alacritty", "/Applications/Alacritty.app", "alacritty"),
    TerminalApp("Terminal", "/System/Applications/Utilities/Terminal.app", "Terminal"),
)

_ARGV_LAUNCHERS = frozenset({"Ghostty", "WezTerm", "kitty", "Alacritty"})

#: Any of these in a process name means we have reached the terminal app.
_APP_HINTS = tuple(app.process.lower() for app in KNOWN_TERMINALS)


def detect(preferred: str | None = None) -> TerminalApp | None:
    preferred = preferred or os.environ.get("OPENDECK_TERMINAL")
    if preferred:
        for app in KNOWN_TERMINALS:
            if app.name.lower() == preferred.lower():
                return app
        return TerminalApp(preferred, f"/Applications/{preferred}.app", preferred.lower())
    return next((app for app in KNOWN_TERMINALS if os.path.isdir(app.path)), None)


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, timeout=TIMEOUT)


def _osascript(script: str) -> subprocess.CompletedProcess[str]:
    result = _run("osascript", "-e", script)
    if result.returncode != 0:
        log.debug("osascript: %s", result.stderr.strip())
    return result


def _ppid(pid: str) -> str:
    return _run("ps", "-o", "ppid=", "-p", pid).stdout.strip()


def _command(pid: str) -> str:
    return _run("ps", "-o", "comm=", "-p", pid).stdout.strip()


class Terminal:
    """Opens and focuses one fullscreen window per session."""

    def __init__(self, app: TerminalApp | None = None, fullscreen: bool = True) -> None:
        self.app = app or detect()
        self.fullscreen = fullscreen

    @property
    def available(self) -> bool:
        return self.app is not None and shutil.which("osascript") is not None

    # ---------- finding an existing window ----------
    def window_pid(self, tty: str) -> str | None:
        """The terminal app process owning a tmux client's tty.

        Walks up from whatever is running on that tty until it reaches a known
        terminal. Going through tmux rather than the launch arguments is what
        makes a session you attached by hand findable.
        """
        if not tty:
            return None
        pid = _run("ps", "-t", tty.removeprefix("/dev/"), "-o", "pid=").stdout.strip()
        pid = pid.splitlines()[0].strip() if pid else ""

        seen = 0
        while pid and pid != "1" and seen < 12:
            name = _command(pid).lower()
            if any(hint in name for hint in _APP_HINTS):
                return pid
            pid = _ppid(pid)
            seen += 1
        return None

    # ---------- acting on it ----------
    def focus_pid(self, pid: str) -> bool:
        """Bring one specific instance forward, switching Space if needed.

        By pid, not by app name: these are separate instances of the same app,
        and activating by name lets macOS pick whichever it feels like.
        """
        script = (
            'tell application "System Events" to set frontmost of '
            f"(first process whose unix id is {pid}) to true"
        )
        return _osascript(script).returncode == 0

    def make_fullscreen(self, pid: str) -> bool:
        """Fullscreen a window that has just been created.

        Sends the app's own toggle_fullscreen shortcut. Writing AXFullScreen
        instead reports success and does nothing, and reading it back is
        impossible once the window has a Space of its own.

        A blind toggle is only safe here because the window was created
        moments ago and so cannot already be fullscreen. Never call this on a
        window that has been around.
        """
        if not self.fullscreen:
            return False
        if not self.focus_pid(pid):
            return False

        # The keystroke lands wherever focus actually is, so confirm the right
        # window took it first. Fullscreening an unrelated app because
        # activation lost a race would be a nasty surprise.
        time.sleep(FOCUS_SETTLE)
        front = _osascript(
            'tell application "System Events" to get unix id of '
            "first process whose frontmost is true"
        ).stdout.strip()
        if front != str(pid):
            log.warning("not fullscreening: %s is frontmost, wanted %s", front, pid)
            return False

        return _osascript(
            'tell application "System Events" to keystroke return using command down'
        ).returncode == 0

    def focus(self, tty: str | None = None) -> bool:
        """Raise the terminal, targeting a specific window when we know it.

        Given a tmux client's tty we can activate that exact instance, which
        matters because several instances of the same terminal can be running
        and activating by app name lets macOS pick between them arbitrarily.
        """
        pid = self.window_pid(tty) if tty else None
        if pid:
            return self.focus_pid(pid)

        if self.app is None:
            return False
        # No specific window: raise the app and take whatever it gives us.
        subprocess.Popen(
            ["osascript", "-e", f'tell application "{self.app.name}" to activate'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return True

    def open_fullscreen(self, session: str) -> bool:
        """Open a new window attached to `session` and fullscreen it."""
        if self.app is None:
            log.error("no terminal app found; set OPENDECK_TERMINAL")
            return False

        before = set(self._instances())
        if not self._launch(session):
            return False

        pid = self._await_new_instance(before)
        if pid is None:
            # The window may still be coming up; leaving it windowed is better
            # than blocking the deck any longer.
            log.warning("no new %s window appeared for %s", self.app.name, session)
            return False

        self.make_fullscreen(pid)
        log.info("opened %s fullscreen (pid %s)", session, pid)
        return True

    # ---------- internals ----------
    def _launch(self, session: str) -> bool:
        assert self.app is not None
        if self.app.name in _ARGV_LAUNCHERS:
            # The command must be separate argv entries; a single quoted string
            # opens a window that runs nothing.
            result = _run("open", "-na", self.app.path, "--args",
                          "-e", "tmux", "attach", "-t", session)
            return result.returncode == 0
        return self._launch_via_applescript(session)

    def _instances(self) -> list[str]:
        assert self.app is not None
        result = _run("pgrep", "-f", f"{self.app.path}/Contents/MacOS/")
        return [p for p in result.stdout.split() if p]

    def _await_new_instance(self, before: set[str]) -> str | None:
        waited = 0.0
        while waited < WINDOW_WAIT:
            fresh = [p for p in self._instances() if p not in before]
            if fresh and self._has_window(fresh[0]):
                return fresh[0]
            time.sleep(WINDOW_POLL)
            waited += WINDOW_POLL
        return None

    def _has_window(self, pid: str) -> bool:
        script = (
            'tell application "System Events" to get count of windows of '
            f"(first process whose unix id is {pid})"
        )
        result = _osascript(script)
        return result.returncode == 0 and result.stdout.strip() not in ("", "0")

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
        return _osascript(script).returncode == 0
