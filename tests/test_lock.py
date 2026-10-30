import json
import os
import socket
from datetime import datetime, timedelta

import pytest

from pm_infra.lock import LockHeld, SpaceLock, is_stale, read_info


def test_acquire_release(tmp_path):
    lock = SpaceLock(tmp_path / ".transcribing.lock")
    lock.acquire("a.m4a")
    info = read_info(lock.path)
    assert info["file"] == "a.m4a" and info["pid"] == os.getpid() and info["host"] == socket.gethostname()
    if os.name == "nt":
        assert os.stat(lock.path).st_file_attributes & 0x02  # hidden
    lock.release()
    assert not lock.path.exists()


def test_second_holder_refused(tmp_path):
    a = SpaceLock(tmp_path / "l")
    b = SpaceLock(tmp_path / "l")
    a.acquire("a.m4a")
    with pytest.raises(LockHeld):
        b.acquire("b.m4a")
    a.release()
    b.acquire("b.m4a")
    b.release()


def test_stale_by_age_is_taken_over(tmp_path):
    path = tmp_path / "l"
    old = (datetime.now() - timedelta(hours=7)).isoformat(timespec="seconds")
    path.write_text(json.dumps({"host": "other-laptop", "pid": 1, "file": "x", "started": old}))
    assert is_stale(read_info(path), path)
    lock = SpaceLock(path)
    lock.acquire("new.m4a")
    assert read_info(path)["file"] == "new.m4a"
    lock.release()


def test_dead_pid_on_same_host_is_stale(tmp_path):
    path = tmp_path / "l"
    path.write_text(json.dumps({"host": socket.gethostname(), "pid": 999_999_999, "file": "x",
                                "started": datetime.now().isoformat(timespec="seconds")}))
    assert is_stale(read_info(path), path)


def test_fresh_lock_from_other_host_is_not_stale(tmp_path):
    path = tmp_path / "l"
    path.write_text(json.dumps({"host": "other-laptop", "pid": 1, "file": "x",
                                "started": datetime.now().isoformat(timespec="seconds")}))
    assert not is_stale(read_info(path), path)


def test_context_manager_releases(tmp_path):
    with SpaceLock(tmp_path / "l") as lock:
        lock.acquire("a")
        assert lock.path.exists()
    assert not lock.path.exists()
