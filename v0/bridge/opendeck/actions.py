"""Actions bound to key gestures.

Each action is a small callable resolved by name from `REGISTRY`, so bindings
stay declarative and configurable.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, Protocol

from .config import Config
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
            session = ctx.slots.create_for(slot)
            if session is None:
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
        if session is None:
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


def launch_agent(split: bool = False) -> Action:
    """Start the configured agent command.

    Without `split`, this refuses to type into a pane that is running a
    program; a freshly split pane is always an idle shell, so the split path
    needs no such check.
    """

    def run(ctx: Context) -> None:
        session = ctx.current_session()
        if session is None:
            return
        command = ctx.config.launch_command

        if split:
            if not ctx.tmux.split_window(session, ctx.config.split_horizontal):
                return
            log.info("launch %r in split of %s", command, session)
            ctx.tmux.run_command(session, command)
            return

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


def cancel() -> Action:
    """Interrupt a running program, or close an idle pane.

    Closing the last pane of a session ends that session; tmux behaves this
    way for a plain `exit` and the deck does not override it.
    """

    def run(ctx: Context) -> None:
        session = ctx.current_session()
        if session is None:
            return
        command = ctx.tmux.active_command(session)
        if is_busy(command):
            log.info("interrupt %r in %s", command, session)
            ctx.tmux.send_keys(session, "C-c")
        else:
            log.info("closing idle pane in %s", session)
            ctx.tmux.run_command(session, "exit")

    return run


def new_window() -> Action:
    def run(ctx: Context) -> None:
        session = ctx.current_session()
        if session is not None:
            ctx.tmux.new_window(session)

    return run


def cycle_window(delta: int) -> Action:
    def run(ctx: Context) -> None:
        session = ctx.current_session()
        if session is not None:
            ctx.tmux.cycle_window(session, delta)

    return run


def cycle_pane(delta: int) -> Action:
    """Step through terminals, honouring the configured encoder scope."""

    def run(ctx: Context) -> None:
        session = ctx.current_session()
        if session is not None:
            ctx.tmux.cycle_pane(
                session, delta, whole_session=ctx.config.encoder_scope == "session"
            )

    return run


REGISTRY: dict[str, Callable[..., Action]] = {
    "summon": summon,
    "interrupt": interrupt,
    "send_keys": send_keys,
    "launch_agent": launch_agent,
    "cancel": cancel,
    "new_window": new_window,
    "cycle_window": cycle_window,
    "cycle_pane": cycle_pane,
}


def build(action: str, args: dict) -> Action:
    factory = REGISTRY.get(action)
    if factory is None:
        raise KeyError(f"unknown action: {action!r}")
    return factory(**args)
