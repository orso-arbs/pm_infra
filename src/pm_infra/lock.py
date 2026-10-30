""".transcribing.lock: one per space, hidden, so two installs never process the same file."""

from __future__ import annotations

import json
import os
import socket
import time
from datetime import datetime, timedelta
from pathlib import Path

import psutil

STALE_AFTER = timedelta(hours=6)
FILE_ATTRIBUTE_HIDDEN = 0x02


class LockHeld(Exception):
    pass


def _hide(path: Path) -> None:
    if os.name != "nt":
        return
    import ctypes

    ctypes.windll.kernel32.SetFileAttributesW(str(path), FILE_ATTRIBUTE_HIDDEN)


def read_info(path: Path) -> dict | None:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def is_stale(info: dict | None, path: Path, now: datetime | None = None) -> bool:
    now = now or datetime.now()
    started = None
    if info:
        try:
            started = datetime.fromisoformat(info.get("started", ""))
        except (ValueError, TypeError):
            started = None
    if started is None:
        try:
            started = datetime.fromtimestamp(path.stat().st_mtime)
        except OSError:
            return True
    if now - started > STALE_AFTER:
        return True
    if info and info.get("host") == socket.gethostname():
        pid = info.get("pid")
        if isinstance(pid, int) and not psutil.pid_exists(pid):
            return True
    return False


class SpaceLock:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.held = False

    def acquire(self, file_name: str, now: datetime | None = None) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(2):
            try:
                fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                info = read_info(self.path)
                if is_stale(info, self.path, now):
                    try:
                        os.remove(self.path)
                    except OSError:
                        pass
                    continue
                who = (info or {}).get("host", "another install")
                what = (info or {}).get("file", "a file")
                raise LockHeld(f"{who} is transcribing {what} in this space")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "host": socket.gethostname(),
                        "pid": os.getpid(),
                        "file": file_name,
                        "started": (now or datetime.now()).isoformat(timespec="seconds"),
                    },
                    f,
                )
            _hide(self.path)
            self.held = True
            return
        raise LockHeld("could not take the lock")

    def release(self) -> None:
        if not self.held:
            return
        for _ in range(5):
            try:
                os.remove(self.path)
                break
            except FileNotFoundError:
                break
            except PermissionError:
                time.sleep(0.2)
        self.held = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.release()
