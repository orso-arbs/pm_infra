from datetime import datetime

from pm_infra.engine import Segment, assign_speakers, hms, render_transcript


def test_assign_speakers_by_overlap_then_merge():
    segs = [Segment(0, 2, "Hallo"), Segment(2.5, 4, "zusammen"), Segment(6, 8, "Hi"), Segment(9.5, 11, "Ja")]
    turns = [(0, 4.5, "SPK_B"), (5.5, 12, "SPK_A")]
    out = assign_speakers(segs, turns)
    assert [(s.speaker, s.text) for s in out] == [("SPEAKER_1", "Hallo zusammen"), ("SPEAKER_2", "Hi"), ("SPEAKER_2", "Ja")]
    assert out[0].start == 0 and out[0].end == 4


def test_assign_speakers_nearest_when_no_overlap():
    out = assign_speakers([Segment(10, 11, "x")], [(0, 5, "A"), (20, 25, "B")])
    assert out[0].speaker == "SPEAKER_1"


def test_assign_speakers_without_turns_is_identity():
    segs = [Segment(0, 1, "a")]
    assert assign_speakers(segs, None) is segs


def test_render_transcript_format():
    text = render_transcript("2026-10-28_1802_Recording.m4a", datetime(2026, 10, 28, 18, 2),
                             datetime(2026, 10, 28, 19, 30), "de", "large-v3-turbo", 3, "prefix",
                             [Segment(4, 9, "Guten Abend.", "SPEAKER_1"), Segment(3600, 3610, "Tschüss.", None)])
    assert text.startswith("---\nsource_file: 2026-10-28_1802_Recording.m4a\nrecorded_start: 2026-10-28T18:02:00")
    assert "recorded_end: 2026-10-28T19:30:00" in text
    assert "\nspeakers: 3\n" in text and "time_source: prefix" in text
    assert "[00:00:04] SPEAKER_1: Guten Abend.\n[01:00:00] Tschüss.\n" in text


def test_render_without_speakers():
    text = render_transcript("a.m4a", datetime(2026, 1, 1, 9), datetime(2026, 1, 1, 10), "en", "medium", None, "file", [])
    assert "speakers: none" in text


def test_hms():
    assert hms(0) == "00:00:00" and hms(3661.9) == "01:01:01"


def test_settle_symlink_support_matches_probe(tmp_path):
    from huggingface_hub import file_download

    from pm_infra import engine

    original = file_download.are_symlinks_supported
    try:
        ok = engine.settle_symlink_support(tmp_path / "models")
        assert ok == engine.symlinks_work(tmp_path / "models")
        assert not list((tmp_path / "models").iterdir())  # probe cleaned up
        if ok:
            assert file_download.are_symlinks_supported is original
        else:
            assert file_download.are_symlinks_supported(str(tmp_path)) is False
    finally:
        file_download.are_symlinks_supported = original
