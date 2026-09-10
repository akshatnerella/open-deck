"""Command-line entry point."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .config import Config
from .controller import Controller
from .terminal import Terminal, detect
from .tmux import Tmux
from .transport import SerialTransport

log = logging.getLogger("opendeck")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="opendeck", description="Open Deck host bridge")
    parser.add_argument("-c", "--config", type=Path, help="path to config.json")
    parser.add_argument("--command", help="agent command to launch (e.g. 'cla')")
    parser.add_argument("--port", help="serial port (default: autodetect)")
    parser.add_argument("--terminal", help="terminal app name (default: autodetect)")
    parser.add_argument(
        "--sessions", help="comma-separated tmux sessions pinned to the four keys"
    )
    parser.add_argument("--no-fullscreen", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser


def build_config(args: argparse.Namespace) -> Config:
    config = Config.load(args.config)
    sessions = None
    if args.sessions:
        names = [name.strip() or None for name in args.sessions.split(",")]
        sessions = tuple((names + [None] * 4)[:4])
    return config.with_overrides(
        launch_command=args.command,
        serial_port=args.port,
        terminal=args.terminal,
        sessions=sessions,
        fullscreen=False if args.no_fullscreen else None,
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)-22s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )

    config = build_config(args)
    tmux = Tmux()
    if not tmux.available():
        log.error("tmux not found on PATH")
        return 1

    app = detect(config.terminal)
    if app is None:
        log.error("no terminal app found; set --terminal or OPENDECK_TERMINAL")
        return 1
    log.info("terminal: %s | launch command: %r", app.name, config.launch_command)

    transport = SerialTransport(config.serial_port)
    controller = Controller(config, transport, tmux, Terminal(app, config.fullscreen))

    transport.start()
    try:
        controller.run()
    except KeyboardInterrupt:
        log.info("shutting down")
    finally:
        controller.stop()
        transport.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
