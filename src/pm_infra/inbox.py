"""Inbox scanning, sync-stability checks, and running the engine on ready files."""

from __future__ import annotations

import os
import time
import traceback
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from pm_infra import engine, media, paths
from pm_infra.lock import LockHeld, SpaceLock
from pm_infra.paths import SpaceDirs
from pm_infra.settings import SpaceSettings

IGNORED_PREFIXES = ("~", ".", "_")
PARTIAL_SUFFIXES = (".tmp", ".part", ".crdownload", ".partial", ".download")
FILE_ATTRIBUTE_OFFLINE = 0x1000
FILE_ATTRIBUTE_RECALL_ON_OPEN = 0x40000
FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x400000
CLOUD_ONLY = FILE_ATTRIBUTE_OFFLINE | FILE_ATTRIBUTE_RECALL_ON_OPEN | FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS

Progress = Callable[[str], None]


def candidate_files(inbox: Path) -> list[Path]:
    if not inbox.is_dir():
        return []
    out = []
    for f in sorted(inbox.iterdir(), key=lambda p: p.name.lower()):
        if not f.is_file() or f.name.startswith(IGNORED_PREFIXES):
            continue
        if f.suffix.lower() in PARTIAL_SUFFIXES or f.suffix.lower() not in media.SUPPORTED:
            continue
        out.append(f)
    return out


def is_cloud_only(path: Path) -> bool:
    try:
        attrs = os.stat(path).st_file_attributes  # type: ignore[attr-defined]
    except (OSError, AttributeError):
        return False
    return bool(attrs & CLOUD_ONLY)


def hydrate(path: Path) -> None:
    """Reading a cloud-only OneDrive file makes OneDrive download it."""
    try:
        with open(path, "rb") as f:
            while f.read(1024 * 1024):
                pass
    except OSError:
        pass


def can_open_exclusively(path: Path) -> bool:
    if os.name != "nt":
        try:
            with open(path, "rb"):
                return True
        except OSError:
            return False
    import ctypes
    from ctypes import wintypes

    GENERIC_READ = 0x80000000
    OPEN_EXISTING = 3
    INVALID = wintypes.HANDLE(-1).value
    k32 = ctypes.windll.kernel32
    k32.CreateFileW.restype = wintypes.HANDLE
    h = k32.CreateFileW(str(path), GENERIC_READ, 0, None, OPEN_EXISTING, 0, None)
    if h == INVALID or h is None:
        return False
    k32.CloseHandle(h)
    return True


class StabilityTracker:
    """A file is ready once size and mtime are unchanged for `min_age` seconds and nobody holds it open."""

    def __init__(self, min_age: float = 10.0):
        self.min_age = min_age
        self.seen: dict[str, tuple[tuple[int, float], float]] = {}

    def ready(self, path: Path, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        try:
            st = path.stat()
        except OSError:
            self.seen.pop(str(path), None)
            return False
        sig = (st.st_size, st.st_mtime)
        prev = self.seen.get(str(path))
        if prev is None or prev[0] != sig:
            self.seen[str(path)] = (sig, now)
            return False
        if now - prev[1] < self.min_age:
            return False
        if is_cloud_only(path):
            return False
        return can_open_exclusively(path)

    def forget(self, path: Path) -> None:
        self.seen.pop(str(path), None)


def wait_until_ready(path: Path, timeout: float = 900.0, poll: float = 2.0, min_age: float = 4.0,
                     progress: Progress | None = None) -> bool:
    tracker = StabilityTracker(min_age=min_age)
    deadline = time.time() + timeout
    said = False
    while time.time() < deadline:
        if not path.exists():
            return False  # taken by another run or removed by hand: do not wait for it
        if is_cloud_only(path):
            if progress and not said:
                progress(f"  waiting for OneDrive to download {path.name}...")
                said = True
            hydrate(path)
        if tracker.ready(path):
            return True
        if progress and not said:
            progress(f"  waiting for {path.name} to finish syncing...")
            said = True
        time.sleep(poll)
    return False


@dataclass
class Outcome:
    file: Path
    ok: bool
    message: str
    result: engine.RunResult | None = None


def run_space(
    space_root: Path,
    settings: SpaceSettings,
    progress: Progress = print,
    files: list[Path] | None = None,
    token: str | None = None,
    with_speakers: bool = True,
    logger=None,
) -> list[Outcome]:
    dirs = SpaceDirs(space_root)
    dirs.ensure()
    outcomes: list[Outcome] = []
    todo = list(files) if files else candidate_files(dirs.inbox)
    if not todo:
        progress("Nothing to do: the inbox is empty.")
        return outcomes
    for src in todo:
        progress(f"\n{src.name}")
        if not wait_until_ready(src, progress=progress):
            if not src.exists():
                msg = "no longer in the inbox (processed by another run?)"
            else:
                msg = "still syncing or open elsewhere; left in the inbox"
            progress(f"  skipped: {msg}")
            outcomes.append(Outcome(src, False, msg))
            continue
        lock = SpaceLock(dirs.lock)
        try:
            lock.acquire(src.name)
        except LockHeld as e:
            progress(f"  skipped: {e}")
            outcomes.append(Outcome(src, False, str(e)))
            continue
        try:
            result = engine.process_file(src, space_root, settings, progress=lambda m: progress(f"  {m}"),
                                         token=token, with_speakers=with_speakers)
            progress(f"  done in {result.seconds / 60:.1f} min -> {result.meeting_dir.name}\\{result.transcript.name}")
            if logger:
                logger.info("transcribed %s -> %s (%.0fs, %s, speakers=%s)", src.name, result.transcript,
                            result.seconds, result.model, result.speakers)
            outcomes.append(Outcome(src, True, "ok", result))
        except Exception as e:  # noqa: BLE001  (anything: the file goes to _failed with the reason)
            reason = f"{type(e).__name__}: {str(e).strip()[:400]}"
            progress(f"  FAILED: {reason}")
            if logger:
                logger.exception("failed %s", src.name)
            fail_file(src, dirs, reason, traceback.format_exc())
            outcomes.append(Outcome(src, False, reason))
        finally:
            lock.release()
    return outcomes


def fail_file(src: Path, dirs: SpaceDirs, reason: str, details: str = "") -> Path | None:
    dirs.failed.mkdir(parents=True, exist_ok=True)
    dest = None
    if src.exists():
        dest = dirs.failed / src.name
        k = 2
        while dest.exists():
            dest = dirs.failed / f"{src.stem}_{k}{src.suffix}"
            k += 1
        try:
            os.replace(src, dest)
        except OSError:
            import shutil

            shutil.move(str(src), str(dest))
    stamp = datetime.now().isoformat(timespec="seconds")
    with open(dirs.failed / paths.ERROR_LOG, "a", encoding="utf-8") as f:
        f.write(f"{stamp}  {src.name}\n  {reason}\n")
        if details:
            f.write("".join(f"  {line}\n" for line in details.strip().splitlines()[-12:]))
        f.write("\n")
    return dest
