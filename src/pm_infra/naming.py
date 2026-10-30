"""Recording time and meeting-folder names.

Folder: YYYY-MM-DD_HHMM_<original name>. The time is the recording's: from the file-name
prefix the iPhone Shortcut sets, else media metadata, else the file's modified time.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

PREFIX_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[_ -](\d{2})[:.]?(\d{2})(?:[:.]?(\d{2}))?[_ \-]*(.*)$"
)
INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def parse_prefix(stem: str) -> tuple[datetime | None, str]:
    """Return (recording time, remaining name) if the stem starts with a date-time prefix."""
    m = PREFIX_RE.match(stem.strip())
    if not m:
        return None, stem
    y, mo, d, h, mi, s, rest = m.groups()
    try:
        dt = datetime(int(y), int(mo), int(d), int(h), int(mi), int(s or 0))
    except ValueError:
        return None, stem
    return dt, rest


def clean_name(name: str, fallback: str = "Recording") -> str:
    name = INVALID.sub(" ", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    return name[:80].strip(" .") or fallback


def recording_start(file: Path, metadata_time: datetime | None = None) -> tuple[datetime, str]:
    """Local, naive datetime and where it came from: 'prefix' | 'metadata' | 'file'."""
    dt, _ = parse_prefix(Path(file).stem)
    if dt:
        return dt, "prefix"
    if metadata_time:
        if metadata_time.tzinfo is not None:
            metadata_time = metadata_time.astimezone().replace(tzinfo=None)
        return metadata_time.replace(microsecond=0), "metadata"
    mtime = datetime.fromtimestamp(Path(file).stat().st_mtime)
    return mtime.replace(microsecond=0), "file"


def meeting_folder_name(start: datetime, original_stem: str) -> str:
    _, rest = parse_prefix(original_stem)
    return f"{start:%Y-%m-%d_%H%M}_{clean_name(rest)}"


def folder_time(folder_name: str) -> datetime | None:
    dt, _ = parse_prefix(folder_name)
    return dt


def to_local_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.astimezone()  # attaches the local zone
    return dt.isoformat(timespec="seconds")


def numbered(folder: Path, stem: str, suffix: str, n: int) -> Path:
    return folder / (f"{stem}{suffix}" if n == 1 else f"{stem}_{n}{suffix}")


def next_index(folder: Path, stem: str = "transcript", suffix: str = ".md") -> int:
    n = 1
    while numbered(folder, stem, suffix, n).exists():
        n += 1
    return n


def parse_iso(text: str) -> datetime | None:
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
