"""Test doubles for tmux and the terminal app."""

from __future__ import annotations

from opendeck.tmux import Pane, Session, Window


class FakeTmux:
    def __init__(self, sessions=(), windows=None, active_command="zsh", client=True,
                 panes=None):
        self._sessions = [
            Session(name=n, windows=1, attached=False) if isinstance(n, str) else n
            for n in sessions
        ]
        self._windows = windows or {}
        self._active_command = active_command
        self._client = client
        self._panes = panes or {}
        self.calls: list[tuple] = []

    def available(self):
        return True

    def sessions(self):
        return list(self._sessions)

    def windows(self, session):
        return list(self._windows.get(session, []))

    def client_tty(self, session):
        if self._client and self._sessions and self._sessions[0].name == session:
            return "/dev/ttys999"
        return None

    def attached_session(self):
        return self._sessions[0].name if self._sessions and self._client else None

    def has_client(self):
        return self._client

    def select_pane(self, session, pane):
        self.calls.append(("select_pane", session, pane.target))
        return True

    def switch(self, session):
        self.calls.append(("switch", session))
        return True

    def send_keys(self, target, *keys):
        self.calls.append(("send_keys", target, *keys))
        return True

    def run_command(self, session, command):
        self.calls.append(("run_command", session, command))
        return True

    def split_window(self, session, horizontal=True):
        self.calls.append(("split_window", session, horizontal))
        return True

    def new_session(self, name):
        self.calls.append(("new_session", name))
        self._sessions.append(Session(name=name, windows=1, attached=False))
        return True

    def new_window(self, session):
        self.calls.append(("new_window", session))
        return True

    def panes(self, session, whole_session=True):
        return list(self._panes.get(session, []))

    def active_command(self, session):
        return self._active_command

    def is_idle_shell(self, session):
        from opendeck.tmux import SHELLS

        return self._active_command in SHELLS


class FakeTerminal:
    def __init__(self, window_found=True):
        self.calls: list[tuple] = []
        self._window_found = window_found

    def focus(self, tty=None):
        self.calls.append(("focus", tty))
        return self._window_found

    def open_fullscreen(self, session):
        self.calls.append(("open_fullscreen", session))
        return True


def window(index=0, name="zsh", command="zsh", active=False, activity=False, bell=False):
    return Window(index, name, command, active, activity, bell)


def pane(window=0, index=0, command="zsh", window_active=False, pane_active=False):
    return Pane(window, index, command, window_active, pane_active)
