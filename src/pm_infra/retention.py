"""Audio retention: delete meeting audio once its transcript exists and the recording is old enough,
and purge expired originals in _to_delete/. A retention of 0 or less keeps everything."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from pathlib import Path

from pm_infra.naming import folder_time, numbered
from pm_infra.paths import SpaceDirs

AUDIO_RE = re.compile(r"^audio(?:_(\d+))?\.m4a$", re.IGNORECASE)


def cleanup_space(space_root: Path, retention_days: int, now: datetime | None = None) -> list[Path]:
    if retention_days is None or retention_days <= 0:
        return []
    now = now or datetime.now()
    cutoff = now - timedelta(days=retention_days)
    dirs = SpaceDirs(space_root)
    deleted: list[Path] = []

    if dirs.meetings.is_dir():
        for meeting in dirs.meetings.iterdir():
            if not meeting.is_dir():
                continue
            recorded = folder_time(meeting.name)
            for audio in meeting.iterdir():
                m = AUDIO_RE.match(audio.name)
                if not m or not audio.is_file():
                    continue
                n = int(m.group(1) or 1)
                if not numbered(meeting, "transcript", ".md", n).exists():
                    continue
                when = recorded or datetime.fromtimestamp(audio.stat().st_mtime)
                if when <= cutoff:
                    audio.unlink()
                    deleted.append(audio)

    if dirs.to_delete.is_dir():
        for f in dirs.to_delete.iterdir():
            if f.is_file() and datetime.fromtimestamp(f.stat().st_mtime) <= cutoff:
                f.unlink()
                deleted.append(f)
    return deleted
