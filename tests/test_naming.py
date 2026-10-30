from datetime import datetime, timezone
from pathlib import Path

from pm_infra.naming import (
    clean_name, folder_time, meeting_folder_name, next_index, numbered, parse_prefix, recording_start,
)


def test_parse_prefix_shortcut_format():
    dt, rest = parse_prefix("2026-10-28_1405_Kickoff")
    assert dt == datetime(2026, 10, 28, 14, 5)
    assert rest == "Kickoff"


def test_parse_prefix_with_seconds_and_spaces():
    dt, rest = parse_prefix("2026-10-28 14.05.33 Team sync")
    assert dt == datetime(2026, 10, 28, 14, 5, 33)
    assert rest == "Team sync"


def test_parse_prefix_absent_or_invalid():
    assert parse_prefix("Kickoff") == (None, "Kickoff")
    assert parse_prefix("2026-13-40_9999_x")[0] is None


def test_recording_start_prefers_prefix_then_metadata_then_file(tmp_path):
    f = tmp_path / "2026-10-28_1802_Recording.m4a"
    f.write_bytes(b"x")
    meta = datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc)
    assert recording_start(f, meta) == (datetime(2026, 10, 28, 18, 2), "prefix")

    g = tmp_path / "Recording.m4a"
    g.write_bytes(b"x")
    start, source = recording_start(g, meta)
    assert source == "metadata"
    assert start == meta.astimezone().replace(tzinfo=None)

    start, source = recording_start(g, None)
    assert source == "file"
    assert abs((start - datetime.now()).total_seconds()) < 120


def test_meeting_folder_name_strips_existing_prefix_and_bad_chars():
    start = datetime(2026, 10, 28, 18, 2)
    assert meeting_folder_name(start, "2026-10-28_1802_Recording") == "2026-10-28_1802_Recording"
    assert meeting_folder_name(start, "Kick: off? <v2>") == "2026-10-28_1802_Kick off v2"
    assert meeting_folder_name(start, "") == "2026-10-28_1802_Recording"


def test_clean_name_limits_length():
    assert len(clean_name("a" * 200)) == 80


def test_folder_time_roundtrip():
    assert folder_time("2026-10-28_1800_Project kickoff") == datetime(2026, 10, 28, 18, 0)
    assert folder_time("not a meeting") is None


def test_numbered_and_next_index(tmp_path: Path):
    assert numbered(tmp_path, "transcript", ".md", 1).name == "transcript.md"
    assert numbered(tmp_path, "audio", ".m4a", 2).name == "audio_2.m4a"
    assert next_index(tmp_path) == 1
    (tmp_path / "transcript.md").write_text("x")
    assert next_index(tmp_path) == 2
    (tmp_path / "transcript_2.md").write_text("x")
    assert next_index(tmp_path) == 3
