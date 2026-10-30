import pytest

from pm_infra.paths import SpaceDirs
from pm_infra.settings import load_settings
from pm_infra.spaces import (
    Registry, SpaceError, close_space, create_space, locate_space, move_space, register_space, set_on_new_files,
)


def test_create_space_layout_and_registry(space, home):
    d = space.dirs
    for p in (d.meetings, d.inbox, d.failed, d.to_delete, d.settings):
        assert p.exists(), p
    settings = load_settings(space.root)
    assert settings.space_id == space.space_id
    assert settings.project == "Projects"
    assert settings.calendar_scope == "all"
    reg = Registry()
    assert reg.get(space.space_id).root == space.root
    assert (home / "spaces.json").exists()


def test_create_on_existing_space_registers_instead(space):
    again = create_space(space.root, "Other name")
    assert again.space_id == space.space_id
    assert load_settings(space.root).project == "Projects"


def test_register_adds_space_id_to_team_folder(tmp_path, home):
    root = tmp_path / "Team X"
    SpaceDirs(root).inbox.mkdir(parents=True)
    s = register_space(root)
    assert s.space_id
    assert load_settings(root).space_id == s.space_id
    assert Registry().by_path(root).space_id == s.space_id


def test_register_rejects_non_space(tmp_path, home):
    (tmp_path / "plain").mkdir()
    with pytest.raises(SpaceError):
        register_space(tmp_path / "plain")


def test_move_space_updates_registry(space, tmp_path):
    dest_parent = tmp_path / "elsewhere"
    dest_parent.mkdir()
    (space.dirs.meetings / "2026-10-28_1800_Kickoff").mkdir()
    moved = move_space(space.space_id, dest_parent)
    assert moved.root == dest_parent / "Projects"
    assert (moved.root / "Meetings" / "2026-10-28_1800_Kickoff").is_dir()
    assert not space.root.exists()
    assert Registry().get(space.space_id).root == moved.root


def test_move_refused_while_locked_or_dest_exists(space, tmp_path):
    space.dirs.lock.write_text("{}")
    with pytest.raises(SpaceError):
        move_space(space.space_id, tmp_path)
    space.dirs.lock.unlink()
    (tmp_path / "x").mkdir()
    (tmp_path / "x" / "Projects").mkdir()
    with pytest.raises(SpaceError):
        move_space(space.space_id, tmp_path / "x")


def test_locate_after_explorer_move(space, tmp_path):
    new_root = tmp_path / "moved" / "Projects"
    new_root.parent.mkdir()
    space.root.rename(new_root)
    assert not Registry().get(space.space_id).exists()
    found = locate_space(space.space_id, new_root)
    assert found.root == new_root
    assert Registry().get(space.space_id).exists()


def test_locate_rejects_wrong_folder(space, tmp_path):
    other = tmp_path / "Other"
    other.mkdir()
    create_space(other, "Other")
    with pytest.raises(SpaceError):
        locate_space(space.space_id, other)


def test_close_space_deletes_audio_keeps_transcripts(space):
    m = space.dirs.meetings / "2026-10-28_1800_Kickoff"
    m.mkdir()
    (m / "audio.m4a").write_bytes(b"a")
    (m / "transcript.md").write_text("t")
    (space.dirs.to_delete / "orig.mp4").write_bytes(b"v")
    deleted = close_space(space.space_id, delete_audio=True)
    assert set(deleted) == {m / "audio.m4a", space.dirs.to_delete / "orig.mp4"}
    assert (m / "transcript.md").exists()
    assert Registry().get(space.space_id) is None


def test_close_without_delete(space):
    m = space.dirs.meetings / "2026-10-28_1800_Kickoff"
    m.mkdir()
    (m / "audio.m4a").write_bytes(b"a")
    assert close_space(space.space_id, delete_audio=False) == []
    assert (m / "audio.m4a").exists()


def test_set_on_new_files(space):
    set_on_new_files(space.root, "always")
    assert load_settings(space.root).on_new_files == "always"
    assert load_settings(space.root).space_id == space.space_id
