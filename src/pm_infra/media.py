"""ffmpeg / ffprobe helpers."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from pm_infra.naming import parse_iso
from pm_infra.paths import tool_exe

SUPPORTED = {
    ".m4a", ".mp3", ".wav", ".aac", ".flac", ".ogg", ".opus", ".wma", ".aiff", ".aif", ".caf", ".amr",
    ".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi", ".wmv", ".mts",
}
VIDEO_EXT = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi", ".wmv", ".mts"}

CREATE_NO_WINDOW = 0x08000000


def _run(args: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(
        args, capture_output=True, text=True, encoding="utf-8", errors="replace",
        creationflags=CREATE_NO_WINDOW, **kw,
    )


@dataclass
class MediaInfo:
    duration: float
    creation_time: datetime | None
    has_video: bool
    audio_codec: str | None


def probe(path: Path) -> MediaInfo:
    cp = _run([
        tool_exe("ffprobe"), "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", str(path),
    ])
    if cp.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {cp.stderr.strip()[:500]}")
    data = json.loads(cp.stdout or "{}")
    fmt = data.get("format", {})
    streams = data.get("streams", [])
    duration = float(fmt.get("duration") or 0.0)
    if not duration:
        for s in streams:
            if s.get("duration"):
                duration = max(duration, float(s["duration"]))
    tags = {k.lower(): v for k, v in (fmt.get("tags") or {}).items()}
    created = parse_iso(tags["creation_time"]) if tags.get("creation_time") else None
    has_video = any(
        s.get("codec_type") == "video"
        and not (s.get("disposition") or {}).get("attached_pic", 0)
        and s.get("avg_frame_rate") not in (None, "0/0")
        for s in streams
    )
    audio_codec = next((s.get("codec_name") for s in streams if s.get("codec_type") == "audio"), None)
    if audio_codec is None:
        raise RuntimeError("no audio stream in file")
    return MediaInfo(duration=duration, creation_time=created, has_video=has_video, audio_codec=audio_codec)


def to_wav16k(src: Path, dst: Path) -> None:
    cp = _run([
        tool_exe("ffmpeg"), "-y", "-v", "error", "-i", str(src), "-vn", "-ac", "1", "-ar", "16000",
        "-c:a", "pcm_s16le", str(dst),
    ])
    if cp.returncode != 0:
        raise RuntimeError(f"ffmpeg (wav) failed: {cp.stderr.strip()[:500]}")


def to_m4a(src: Path, dst: Path) -> None:
    cp = _run([
        tool_exe("ffmpeg"), "-y", "-v", "error", "-i", str(src), "-vn", "-ac", "1", "-c:a", "aac",
        "-b:a", "96k", "-movflags", "+faststart", str(dst),
    ])
    if cp.returncode != 0:
        raise RuntimeError(f"ffmpeg (m4a) failed: {cp.stderr.strip()[:500]}")


def is_plain_m4a(src: Path, info: MediaInfo) -> bool:
    return src.suffix.lower() == ".m4a" and not info.has_video and (info.audio_codec or "") == "aac"
