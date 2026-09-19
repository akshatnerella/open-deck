"""tmux adapter.

Every deck action ultimately lands here. Nothing in this module kills a
session: switching detaches the previous one and leaves it running.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

TIMEOUT = 5.0

#: Panes running one of these sit at a prompt and are safe to type into.
#: Anything else is a live program, where injected text would land in an
#: editor, a REPL, or a half-typed command.
SHELLS = frozenset({"zsh", "bash", "sh", "fish", "tcsh", "ksh", "dash", "-zsh", "-bash"})

_GENERIC_WINDOW_NAMES = frozenset({"zsh", "bash", "sh", "fish"})

_SESSION_FORMAT = "#{session_name}\t#{session_windows}\t#{session_attached}"
_PANE_FORMAT = (
    "#{window_index}\t#{pane_index}\t#{pane_current_command}\t"
    "#{window_active}\t#{pane_active}\t#{pane_title}"
)
_WINDOW_FORMAT = (
    "#{window_index}\t#{window_name}\t#{pane_current_command}\t"
    "#{window_active}\t#{window_activity_flag}\t#{window_bell_flag}"
)


@dataclass(frozen=True)
class Window:
    index: int
    name: str
    command: str
    active: bool
    activity: bool
    bell: bool

    @property
    def label(self) -> str:
        if self.name and self.name not in _GENERIC_WINDOW_NAMES:
            return self.name
        return self.command or self.name

    @property
    def flag(self) -> str:
        if self.bell:
            return "!"
        return "*" if self.activity else " "


@dataclass(frozen=True)
class Pane:
    """One terminal, addressed as ``window.pane``.

    Panes are the unit the encoder steps through: a split pane and a separate
    window are both just "another terminal" to the user.
    """

    window: int
    index: int
    command: str
    window_active: bool
    pane_active: bool
    #: The terminal title the program set. Claude Code puts its session name
    #: here; most programs put junk. See harness.clean_title.
    title: str = ""

    @property
    def target(self) -> str:
        return f"{self.window}.{self.index}"

    @property
    def active(self) -> bool:
        return self.window_active and self.pane_active


@dataclass(frozen=True)
class Session:
    name: str
    windows: int
    attached: bool


class TmuxError(RuntimeError):
    pass


class Tmux:
    def __init__(self, executable: str = "tmux") -> None:
        self._exe = executable

    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [self._exe, *args], capture_output=True, text=True, timeout=TIMEOUT
        )

    def _ok(self, *args: str) -> bool:
        result = self._run(*args)
        if result.returncode != 0:
            log.debug("tmux %s failed: %s", " ".join(args), result.stderr.strip())
        return result.returncode == 0

    def available(self) -> bool:
        try:
            return self._run("-V").returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def sessions(self) -> list[Session]:
        result = self._run("list-sessions", "-F", _SESSION_FORMAT)
        if result.returncode != 0:
            return []
        sessions = []
        for line in result.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) == 3:
                sessions.append(
                    Session(name=parts[0], windows=int(parts[1]), attached=parts[2] == "1")
                )
        return sessions

    def windows(self, session: str) -> list[Window]:
        result = self._run("list-windows", "-t", session, "-F", _WINDOW_FORMAT)
        if result.returncode != 0:
            return []
        windows = []
        for line in result.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) == 6:
                windows.append(
                    Window(
                        index=int(parts[0]),
                        name=parts[1],
                        command=parts[2],
                        active=parts[3] == "1",
                        activity=parts[4] == "1",
                        bell=parts[5] == "1",
                    )
                )
        return windows

    def attached_session(self) -> str | None:
        result = self._run("list-clients", "-F", "#{client_session}")
        if result.returncode != 0:
            return None
        names = [name for name in result.stdout.splitlines() if name]
        return names[0] if names else None

    def client_tty(self, session: str) -> str | None:
        """The tty of a client attached to `session`, if any.

        This is the handle onto the terminal window showing that session -
        the deck walks up from it to find the window to focus.
        """
        result = self._run("list-clients", "-F", "#{client_session}\t#{client_tty}")
        if result.returncode != 0:
            return None
        for line in result.stdout.splitlines():
            name, _, tty = line.partition("\t")
            if name == session and tty:
                return tty
        return None

    def has_client(self) -> bool:
        result = self._run("list-clients", "-F", "#{client_name}")
        return result.returncode == 0 and bool(result.stdout.strip())

    def session_exists(self, session: str) -> bool:
        return self._run("has-session", "-t", session).returncode == 0

    def switch(self, session: str) -> bool:
        if not self.has_client():
            log.warning("no tmux client attached; cannot switch to %s", session)
            return False
        return self._ok("switch-client", "-t", session)

    def select_window(self, session: str, index: int) -> bool:
        return self._ok("select-window", "-t", f"{session}:{index}")

    def panes(self, session: str, whole_session: bool = True) -> list[Pane]:
        scope = ["-s"] if whole_session else []
        result = self._run("list-panes", *scope, "-t", session, "-F", _PANE_FORMAT)
        if result.returncode != 0:
            return []
        panes = []
        for line in result.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) >= 5:
                panes.append(
                    Pane(
                        window=int(parts[0]),
                        index=int(parts[1]),
                        command=parts[2],
                        window_active=parts[3] == "1",
                        pane_active=parts[4] == "1",
                        title=parts[5] if len(parts) > 5 else "",
                    )
                )
        return panes

    def select_pane(self, session: str, pane: Pane) -> bool:
        return self._ok(
            "select-window", "-t", f"{session}:{pane.window}",
            ";", "select-pane", "-t", f"{session}:{pane.target}",
        )

    def new_window(self, session: str) -> bool:
        return self._ok("new-window", "-t", session)

    def split_window(self, session: str, horizontal: bool = True) -> bool:
        args = ["split-window", "-t", session]
        if horizontal:
            args.append("-h")
        return self._ok(*args)

    def new_session(self, name: str) -> bool:
        return self._ok("new-session", "-d", "-s", name)

    def active_command(self, session: str) -> str:
        result = self._run("display-message", "-p", "-t", session, "#{pane_current_command}")
        return result.stdout.strip() if result.returncode == 0 else ""

    def is_idle_shell(self, session: str) -> bool:
        return self.active_command(session) in SHELLS

    def send_keys(self, target: str, *keys: str) -> bool:
        return self._ok("send-keys", "-t", target, *keys)

    def run_command(self, session: str, command: str) -> bool:
        """Type `command` into the active pane and submit it.

        Callers are responsible for checking `is_idle_shell` first.
        """
        return self.send_keys(session, command, "Enter")
