from pathlib import Path

from pm_infra import engine, inbox
from pm_infra.inbox import StabilityTracker, candidate_files, fail_file, run_space
from pm_infra.settings import load_settings


def test_candidate_files_filters(space):
    box = space.dirs.inbox
    for name in ("a.m4a", "b.MP3", "c.txt", "~d.m4a", ".e.m4a", "f.m4a.tmp", "g.mov"):
        (box / name).write_bytes(b"x")
    (box / "sub").mkdir()
    assert [p.name for p in candidate_files(box)] == ["a.m4a", "b.MP3", "g.mov"]


def test_stability_tracker_needs_two_quiet_checks(tmp_path):
    f = tmp_path / "x.m4a"
    f.write_bytes(b"123")
    t = StabilityTracker(min_age=10)
    assert not t.ready(f, now=0)
    assert not t.ready(f, now=5)
    assert t.ready(f, now=11)
    f.write_bytes(b"123456")
    assert not t.ready(f, now=12)
    assert not t.ready(f, now=15)
    assert t.ready(f, now=30)


def test_run_space_moves_failures_and_logs(space, monkeypatch):
    src = space.dirs.inbox / "2026-10-28_1802_Bad.m4a"
    src.write_bytes(b"not audio")
    monkeypatch.setattr(inbox, "wait_until_ready", lambda *a, **k: True)

    def boom(*a, **k):
        raise RuntimeError("ffprobe failed: invalid data")

    monkeypatch.setattr(engine, "process_file", boom)
    out = run_space(space.root, load_settings(space.root), progress=lambda m: None)
    assert len(out) == 1 and not out[0].ok
    assert (space.dirs.failed / src.name).exists()
    assert not src.exists()
    log = (space.dirs.failed / "error.log").read_text(encoding="utf-8")
    assert "RuntimeError: ffprobe failed" in log
    assert not space.dirs.lock.exists()


def test_run_space_success_path(space, monkeypatch):
    src = space.dirs.inbox / "ok.m4a"
    src.write_bytes(b"x")
    monkeypatch.setattr(inbox, "wait_until_ready", lambda *a, **k: True)
    seen = {}

    def fake(path, root, settings, progress, token, with_speakers):
        assert space.dirs.lock.exists()  # lock held during the run
        seen["file"] = path
        meeting = space.dirs.meetings / "2026-10-28_1802_ok"
        meeting.mkdir()
        path.rename(meeting / "audio.m4a")
        return engine.RunResult(path.name, meeting, meeting / "transcript.md", meeting / "audio.m4a",
                                10.0, "de", "large-v3-turbo", 2, "file", 1.0)

    monkeypatch.setattr(engine, "process_file", fake)
    out = run_space(space.root, load_settings(space.root), progress=lambda m: None)
    assert out[0].ok and seen["file"] == src
    assert not space.dirs.lock.exists()


def test_fail_file_numbering(space):
    a = space.dirs.inbox / "x.m4a"
    a.write_bytes(b"1")
    fail_file(a, space.dirs, "r1")
    b = space.dirs.inbox / "x.m4a"
    b.write_bytes(b"2")
    dest = fail_file(b, space.dirs, "r2")
    assert dest == space.dirs.failed / "x_2.m4a"
