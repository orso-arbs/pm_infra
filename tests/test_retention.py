import os
import time
from datetime import datetime, timedelta

from pm_infra.retention import cleanup_space


def _meeting(space, name, audio=True, transcript=True, n=1):
    d = space.dirs.meetings / name
    d.mkdir(parents=True, exist_ok=True)
    if audio:
        (d / ("audio.m4a" if n == 1 else f"audio_{n}.m4a")).write_bytes(b"a")
    if transcript:
        (d / ("transcript.md" if n == 1 else f"transcript_{n}.md")).write_text("t")
    return d


def test_deletes_old_audio_only_with_transcript(space):
    now = datetime(2026, 11, 20, 12, 0)
    old = _meeting(space, "2026-11-01_1000_Old")
    old2 = _meeting(space, "2026-11-01_1000_Old", n=2)
    no_transcript = _meeting(space, "2026-11-01_1100_NoTranscript", transcript=False)
    recent = _meeting(space, "2026-11-15_1000_Recent")
    deleted = cleanup_space(space.root, 14, now=now)
    assert (old / "audio.m4a") in deleted and (old2 / "audio_2.m4a") in deleted
    assert (old / "transcript.md").exists() and (old2 / "transcript_2.md").exists()
    assert (no_transcript / "audio.m4a").exists()
    assert (recent / "audio.m4a").exists()


def test_exact_boundary_and_zero_retention(space):
    now = datetime(2026, 11, 15, 10, 0)
    m = _meeting(space, "2026-11-01_1000_Boundary")
    assert cleanup_space(space.root, 0, now=now) == []
    assert cleanup_space(space.root, 14, now=now) == [m / "audio.m4a"]


def test_to_delete_uses_mtime(space):
    d = space.dirs.to_delete
    old = d / "old.mp4"
    old.write_bytes(b"v")
    stamp = time.time() - 20 * 86400
    os.utime(old, (stamp, stamp))
    fresh = d / "fresh.mp4"
    fresh.write_bytes(b"v")
    deleted = cleanup_space(space.root, 14)
    assert deleted == [old]
    assert fresh.exists()


def test_folder_without_prefix_falls_back_to_file_time(space):
    d = space.dirs.meetings / "Odd name"
    d.mkdir()
    (d / "audio.m4a").write_bytes(b"a")
    (d / "transcript.md").write_text("t")
    stamp = (datetime.now() - timedelta(days=30)).timestamp()
    os.utime(d / "audio.m4a", (stamp, stamp))
    assert cleanup_space(space.root, 14) == [d / "audio.m4a"]
