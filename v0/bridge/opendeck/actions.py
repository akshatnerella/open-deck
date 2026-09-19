"""Actions bound to key gestures.

Each action is a small callable resolved by name from `REGISTRY`, so bindings
stay declarative and configurable.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, Protocol

from .config import Config
from . import harness
from .presence import is_busy
from .slots import SlotTable
from .terminal import Terminal
from .tmux import Tmux

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Context:
    tmux: Tmux
    terminal: Terminal
    slots: SlotTable
    config: Config

    def current_session(self) -> str | None:
        return self.slots.current_session()


class Action(Protocol):
    def __call__(self, ctx: Context) -> None: ...


def summon(slot: int) -> Action:
    """Bring a slot's tmux session onto the screen."""

    def run(ctx: Context) -> None:
        session = ctx.slots.session_for(slot)
        if session is None:
            return
        # A key always means the same session; it just might not exist yet.
        # Creating it here is what makes an unused key still do something.
        if not ctx.slots.exists(slot):
            if ctx.slots.create_for(slot) is None:
                return
        log.info("summon %s (%s)", ctx.slots.label(slot), session)
        if ctx.tmux.has_client():
            ctx.tmux.switch(session)
            ctx.terminal.focus()
        else:
            ctx.terminal.launch_attached(session)

    return run


def interrupt(slot: int) -> Action:
    """Send Escape to a session without switching to it."""

    def run(ctx: Context) -> None:
        session = ctx.slots.session_for(slot)
        # Unlike summon, this must not create: interrupting a session that
        # does not exist should do nothing, not conjure one.
        if session is None or not ctx.slots.exists(slot):
            return
        log.info("interrupt %s (%s)", ctx.slots.label(slot), session)
        ctx.tmux.send_keys(session, "Escape")

    return run


def send_keys(keys: list[str]) -> Action:
    """Deliver keys to the current session's active pane."""

    def run(ctx: Context) -> None:
        session = ctx.current_session()
        if session is None:
            return
        ctx.tmux.send_keys(session, *keys)

    return run


def context_key(role: str) -> Action:
    """Send whatever `role` means inside whatever is running here.

    ENTER, X and MIC are one physical key each but three different keystrokes
    depending on the pane: Ctrl-C interrupts a shell, Escape interrupts an
    agent without killing it, and voice is Space in Claude but Ctrl-Space in
    Grok. Resolving that here keeps the harness differences in one table.
    """

    def run(ctx: Context) -> None:
        session = ctx.current_session()
        if session is None:
            return
        which = harness.for_command(ctx.tmux.active_command(session))
        keys = which.send(role)
        if not keys:
            log.info("%s does nothing in %s", role, which.label)
            return
        log.info("%s -> %s in %s", role, " ".join(keys), which.label)
        ctx.tmux.send_keys(session, *keys)

    return run


def split_pane(below: bool = False) -> Action:
    """A new plain terminal - no agent typed into it.

    Beside by default because a wide split keeps both readable; below when
    ENTER is held, which is the one chord on the deck.
    """

    def run(ctx: Context) -> None:
        session = ctx.current_session()
        if session is None:
            return
        log.info("split %s %s", session, "below" if below else "beside")
        ctx.tmux.split_window(session, horizontal=not below)

    return run


def launch_agent(split: bool = False) -> Action:
    """Start the configured agent in the pane you are looking at.

    Never splits: a new terminal is its own gesture now, so starting an agent
    is "double-tap for a pane, tap to fill it" - two deliberate presses rather
    than one key that sometimes rearranges your screen.
    """

    def run(ctx: Context) -> None:
        session = ctx.current_session()
        if session is None:
            return
        command = ctx.config.launch_command

        running = ctx.tmux.active_command(session)
        if running and command.startswith(running):
            log.info("%r already running in %s", command, session)
            return
        if not ctx.tmux.is_idle_shell(session):
            log.warning("pane is running %r; not launching %r over it", running, command)
            return
        log.info("launch %r in %s", command, session)
        ctx.tmux.run_command(session, command)

    return run




def close_pane() -> Action:
    """Close the pane you are in, the way you would close it yourself.

    `exit` rather than `kill-pane`: it is what a shell expects, it lets the
    shell clean up, and closing the last pane of a session ends that session -
    which is tmux's own behaviour and not something the deck should override.

    Refuses while a program is running. Tapping X already interrupts, so the
    sequence is tap-then-double-tap; a double-tap that could kill a working
    agent outright is not worth the two keystrokes it saves.
    """

    def run(ctx: Context) -> None:
        session = ctx.current_session()
        if session is None:
            return
        running = ctx.tmux.active_command(session)
        if not ctx.tmux.is_idle_shell(session):
            log.info("not closing %s: %r is running", session, running)
            return
        log.info("closing pane in %s", session)
        ctx.tmux.run_command(session, "exit")

    return run


def new_window() -> Action:
    def run(ctx: Context) -> None:
        session = ctx.current_session()
        if session is not None:
            ctx.tmux.new_window(session)

    return run






REGISTRY: dict[str, Callable[..., Action]] = {
    "summon": summon,
    # Not bound by default. Kept because they are the only way to reach a
    # session you are not in, and to send an arbitrary key, from config.json.
    "send_keys": send_keys,
    "interrupt": interrupt,
    "context_key": context_key,
    "split_pane": split_pane,
    "close_pane": close_pane,
    "launch_agent": launch_agent,
    "new_window": new_window,
}


def build(action: str, args: dict) -> Action:
    factory = REGISTRY.get(action)
    if factory is None:
        raise KeyError(f"unknown action: {action!r}")
    return factory(**args)
