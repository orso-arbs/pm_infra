"""Behaviour added after the v1 spec review (2 Nov 2026)."""

from datetime import datetime, timedelta
import json
import time

import pytest

from pm_infra import engine, inbox, media
from pm_infra.inbox import run_space, wait_until_ready
from pm_infra.paths import SpaceDirs
from pm_infra.settings import load_settings
from pm_infra.spaces import Registry, SpaceError, move_space, place_tool_files, refresh_tool_files, register_space
from pm_infra.tray import snooze_blocks


# --- a file that vanished (taken by another run) is skipped at once, not polled for 15 minutes ----

def test_wait_until_ready_returns_at_once_for_missing_file(tmp_path):
    t0 = time.time()
    assert wait_until_ready(tmp_path / "gone.m4a", timeout=60, poll=5) is False
    assert time.time() - t0 < 1


def test_run_space_reports_vanished_file(space):
    gone = space.dirs.inbox / "gone.m4a"
    out = run_space(space.root, load_settings(space.root), progress=lambda m: None, files=[gone])
    assert len(out) == 1 and not out[0].ok
    assert "no longer in the inbox" in out[0].message
    assert not (space.dirs.failed / "error.log").exists()  # not a failure of the file itself


# --- a failed run leaves nothing behind in Meetings/ -------------------------------------------

def test_failed_run_removes_empty_meeting_folder(space, monkeypatch):
    src = space.dirs.inbox / "2026-10-28_1802_Kickoff.m4a"
    src.write_bytes(b"x")
    monkeypatch.setattr(media, "probe", lambda p: media.MediaInfo(60.0, None, False, "aac"))

    def boom(*a, **k):
        raise RuntimeError("ffmpeg failed")

    monkeypatch.setattr(media, "to_wav16k", boom)
    with pytest.raises(RuntimeError):
        engine.process_file(src, space.root, load_settings(space.root), progress=lambda m: None)
    assert not (space.dirs.meetings / "2026-10-28_1802_Kickoff").exists()
    assert src.exists()  # run_space decides what happens to the source, not the engine


def test_failed_run_keeps_folder_that_already_had_content(space, monkeypatch):
    folder = space.dirs.meetings / "2026-10-28_1802_Kickoff"
    folder.mkdir()
    (folder / "transcript.md").write_text("earlier run")
    src = space.dirs.inbox / "2026-10-28_1802_Kickoff.m4a"
    src.write_bytes(b"x")
    monkeypatch.setattr(media, "probe", lambda p: media.MediaInfo(60.0, None, False, "aac"))
    monkeypatch.setattr(media, "to_wav16k", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    with pytest.raises(RuntimeError):
        engine.process_file(src, space.root, load_settings(space.root), progress=lambda m: None)
    assert (folder / "transcript.md").read_text() == "earlier run"
    assert not (folder / "transcript_2.md").exists()


# --- Move: a stale lock from a crash does not block forever ------------------------------------

def test_move_clears_stale_lock(space, tmp_path):
    old = (datetime.now() - timedelta(hours=7)).isoformat(timespec="seconds")
    space.dirs.lock.write_text(json.dumps({"host": "other-laptop", "pid": 1, "file": "a.m4a", "started": old}))
    dest = tmp_path / "elsewhere"
    dest.mkdir()
    moved = move_space(space.space_id, dest)
    assert moved.root == dest / "Projects"
    assert not SpaceDirs(moved.root).lock.exists()


def test_move_still_refused_for_live_lock(space, tmp_path):
    now = datetime.now().isoformat(timespec="seconds")
    space.dirs.lock.write_text(json.dumps({"host": "other-laptop", "pid": 1, "file": "a.m4a", "started": now}))
    with pytest.raises(SpaceError):
        move_space(space.space_id, tmp_path)


# --- tool files land in registered spaces and are refreshed on reinstall -------------------------

def _fake_app_files(home, version: bytes):
    (home / "bin").mkdir(exist_ok=True)
    (home / "app" / "install").mkdir(parents=True, exist_ok=True)
    (home / "bin" / "transcribe.exe").write_bytes(b"EXE " + version)
    (home / "app" / "install_pm_infra.cmd").write_bytes(b"CMD " + version)
    (home / "app" / "install" / "space_README.md").write_bytes(b"README " + version)


def test_register_places_tool_files(tmp_path, home):
    _fake_app_files(home, b"v1")
    root = tmp_path / "Team X"
    SpaceDirs(root).inbox.mkdir(parents=True)
    s = register_space(root)
    assert s.dirs.launcher.read_bytes() == b"EXE v1"
    assert s.dirs.installer.read_bytes() == b"CMD v1"
    assert s.dirs.readme.read_bytes() == b"README v1"


def test_refresh_updates_only_changed_files(space, home):
    _fake_app_files(home, b"v1")
    place_tool_files(space.dirs)
    assert place_tool_files(space.dirs) == []  # nothing differs: nothing written, OneDrive stays quiet
    _fake_app_files(home, b"v2")
    written = refresh_tool_files(Registry())
    assert sorted(p.name for p in written) == ["README.md", "install_pm_infra.cmd", "transcribe.exe"]
    assert space.dirs.launcher.read_bytes() == b"EXE v2"


# --- "Later" in the popup: an hour, or until another file arrives -------------------------------

def test_snooze_blocks_until_expiry_or_new_file():
    t = datetime(2026, 11, 2, 12, 0)
    snooze = (t + timedelta(hours=1), frozenset({"a.m4a"}))
    assert snooze_blocks(None, frozenset({"a.m4a"}), now=t) is False
    assert snooze_blocks(snooze, frozenset({"a.m4a"}), now=t + timedelta(minutes=10)) is True
    assert snooze_blocks(snooze, frozenset({"a.m4a", "b.m4a"}), now=t + timedelta(minutes=10)) is False
    assert snooze_blocks(snooze, frozenset({"a.m4a"}), now=t + timedelta(hours=1)) is False


# --- cloud-only files are detected, so the tray can ask OneDrive to download them ----------------

def test_is_cloud_only_false_for_local_file(tmp_path):
    f = tmp_path / "x.m4a"
    f.write_bytes(b"x")
    assert inbox.is_cloud_only(f) is False
