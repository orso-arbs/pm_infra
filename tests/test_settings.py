from pm_infra.paths import SpaceDirs
from pm_infra.settings import SpaceSettings, ensure_space_id, load_settings, save_settings


def test_defaults_when_file_missing(tmp_path):
    s = load_settings(tmp_path)
    assert s.space_id is None
    assert s.project == tmp_path.name
    assert s.calendar_scope == "all"
    assert s.default_language == "auto"
    assert s.language_or_none is None
    assert s.on_new_files == "ask"
    assert s.audio_retention_days == 14


def test_roundtrip_keeps_values_and_comments(tmp_path):
    s = SpaceSettings(space_id="abc123", project="Team X", calendar_scope=["cal-1", "cal-2"],
                      fallback_database="https://notion.so/x", default_language="de",
                      on_new_files="always", snapshot_to_folder=False, audio_retention_days=30)
    path = save_settings(tmp_path, s)
    text = path.read_text(encoding="utf-8")
    assert "# set at creation, never edit" in text
    assert "  - cal-1" in text
    back = load_settings(tmp_path)
    assert back.space_id == "abc123"
    assert back.project == "Team X"
    assert back.calendar_scope == ["cal-1", "cal-2"]
    assert back.fallback_database == "https://notion.so/x"
    assert back.language_or_none == "de"
    assert back.on_new_files == "always"
    assert back.snapshot_to_folder is False
    assert back.audio_retention_days == 30


def test_ensure_space_id_adds_one_once(tmp_path):
    SpaceDirs(tmp_path).tool.mkdir(parents=True)
    SpaceDirs(tmp_path).settings.write_text("project: Thesis\n", encoding="utf-8")
    first = ensure_space_id(tmp_path)
    assert first.space_id and first.project == "Thesis"
    second = ensure_space_id(tmp_path)
    assert second.space_id == first.space_id


def test_unknown_keys_survive_in_extra(tmp_path):
    SpaceDirs(tmp_path).tool.mkdir(parents=True)
    SpaceDirs(tmp_path).settings.write_text("project: T\nfuture_key: 1\n", encoding="utf-8")
    assert load_settings(tmp_path).extra == {"future_key": 1}
