"""Command line: what the launcher, the tray and the installer call."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from pm_infra import __version__, paths


def _say(msg: str) -> None:
    print(msg, flush=True)


def _console_title(title: str) -> None:
    if os.name == "nt":
        import ctypes

        ctypes.windll.kernel32.SetConsoleTitleW(title)


def _pause(mode: str, failed: bool) -> None:
    if mode == "always" or (mode == "error" and failed):
        try:
            input("\nPress Enter to close this window.")
        except EOFError:
            pass


def cmd_run_now(args) -> int:
    from pm_infra.inbox import run_space
    from pm_infra.log import get_logger
    from pm_infra.settings import load_settings
    from pm_infra.spaces import Registry, SpaceError, register_space

    log = get_logger("run")
    root = Path(args.space).resolve()
    _console_title(f"pm_infra: {root.name}")
    reg = Registry()
    space = reg.by_path(root)
    if space is None:
        try:
            space = register_space(root, reg)
            _say(f"Registered space '{space.name}'.")
        except SpaceError as e:
            _say(str(e))
            _pause(args.pause, True)
            return 2
    settings = load_settings(root)
    files = [Path(f) for f in args.file] if args.file else None
    token = None if args.no_speakers else paths.read_token()
    _say(f"Space: {space.name}  ({root})")
    outcomes = run_space(root, settings, progress=_say, files=files, token=token,
                         with_speakers=not args.no_speakers, logger=log)
    failed = [o for o in outcomes if not o.ok]
    if outcomes:
        _say(f"\n{len(outcomes) - len(failed)} transcribed, {len(failed)} skipped or failed.")
    _pause(args.pause, bool(failed))
    return 1 if failed else 0


def cmd_tray(args) -> int:
    from pm_infra.tray import main as tray_main

    return tray_main()


def cmd_new_space(args) -> int:
    from pm_infra.spaces import create_space

    space = create_space(Path(args.path).resolve(), args.name)
    _say(f"Space '{space.name}' created at {space.root}")
    _say(f"Inbox: {space.dirs.inbox}")
    return 0


def cmd_register(args) -> int:
    from pm_infra.spaces import register_space

    space = register_space(Path(args.path).resolve())
    _say(f"Registered '{space.name}' at {space.root}")
    return 0


def cmd_list(args) -> int:
    from pm_infra.spaces import Registry

    reg = Registry()
    if not reg.spaces:
        _say("No spaces registered.")
    for s in reg.all():
        _say(f"{s.space_id}  {s.name:<24} {s.root}{'' if s.exists() else '  (missing)'}")
    return 0


def cmd_cleanup(args) -> int:
    from pm_infra.retention import cleanup_space
    from pm_infra.settings import load_settings
    from pm_infra.spaces import Registry

    targets = [Path(args.space).resolve()] if args.space else [s.root for s in Registry().all() if s.exists()]
    for root in targets:
        days = load_settings(root).audio_retention_days
        deleted = cleanup_space(root, days)
        _say(f"{root}: {len(deleted)} file(s) deleted (retention {days} days)")
    return 0


def cmd_install_models(args) -> int:
    from pm_infra.engine import install_models

    install_models(progress=_say, token=paths.read_token())
    return 0


def cmd_setup_windows(args) -> int:
    from pm_infra.windows_setup import remove_all, setup_all

    if args.remove:
        remove_all()
        _say("Start-at-login entry and uninstall entry removed.")
    else:
        setup_all()
        _say("Start-at-login entry and uninstall entry written (HKCU).")
    return 0


def cmd_version(args) -> int:
    _say(__version__)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="pm_infra", description="Local meeting transcription.")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run-now", help="process a space's inbox now (what transcribe.exe does)")
    r.add_argument("--space", required=True, help="space folder (the one that contains pm_infra\\ and Meetings\\)")
    r.add_argument("--file", action="append", help="only these files (default: everything in the inbox)")
    r.add_argument("--pause", choices=["always", "error", "never"], default="never",
                   help="wait for Enter before closing the console")
    r.add_argument("--no-speakers", action="store_true", help="skip speaker labels")
    r.set_defaults(fn=cmd_run_now)

    sub.add_parser("tray", help="run the tray app").set_defaults(fn=cmd_tray)

    n = sub.add_parser("new-space", help="create and register a space")
    n.add_argument("--path", required=True)
    n.add_argument("--name")
    n.set_defaults(fn=cmd_new_space)

    g = sub.add_parser("register", help="register an existing space folder")
    g.add_argument("--path", required=True)
    g.set_defaults(fn=cmd_register)

    sub.add_parser("list", help="list registered spaces").set_defaults(fn=cmd_list)

    c = sub.add_parser("cleanup", help="apply audio retention now")
    c.add_argument("--space")
    c.set_defaults(fn=cmd_cleanup)

    sub.add_parser("install-models", help="download the speech models").set_defaults(fn=cmd_install_models)

    w = sub.add_parser("setup-windows", help="start-at-login and uninstall entries (HKCU)")
    w.add_argument("--remove", action="store_true")
    w.set_defaults(fn=cmd_setup_windows)

    sub.add_parser("version").set_defaults(fn=cmd_version)
    return p


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass
    args = build_parser().parse_args(argv)
    return int(args.fn(args) or 0)
