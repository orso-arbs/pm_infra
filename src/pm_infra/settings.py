"""project_settings.yaml: per-space settings, optional, defaults apply when missing.

The file is rewritten from a template so its comments survive edits made by the app.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from pm_infra.paths import SpaceDirs

DEFAULT_LANGUAGE = "auto"
DEFAULT_ON_NEW_FILES = "ask"
DEFAULT_RETENTION_DAYS = 14

TEMPLATE = """\
space_id: {space_id}                    # set at creation, never edit; identifies the space after a move
project: {project}
calendar_scope: {calendar_scope}        # all | list of calendar IDs
fallback_database: {fallback_database}  # minutes for events without a Notion page (v2)
transcribe:
  default_language: {default_language}  # auto | de | en | it
  on_new_files: {on_new_files}          # ask | always
minutes:
  snapshot_to_folder: {snapshot_to_folder}  # write minutes.md (v2)
audio_retention_days: {audio_retention_days}
"""


def new_space_id() -> str:
    return uuid.uuid4().hex[:12]


@dataclass
class SpaceSettings:
    space_id: str | None = None
    project: str | None = None
    calendar_scope: str | list[str] = "all"
    fallback_database: str | None = None
    default_language: str = DEFAULT_LANGUAGE
    on_new_files: str = DEFAULT_ON_NEW_FILES
    snapshot_to_folder: bool = True
    audio_retention_days: int = DEFAULT_RETENTION_DAYS
    extra: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict | None) -> "SpaceSettings":
        data = dict(data or {})
        transcribe = data.pop("transcribe", None) or {}
        minutes = data.pop("minutes", None) or {}
        retention = data.pop("audio_retention_days", DEFAULT_RETENTION_DAYS)
        s = cls(
            space_id=_str_or_none(data.pop("space_id", None)),
            project=_str_or_none(data.pop("project", None)),
            calendar_scope=data.pop("calendar_scope", "all") or "all",
            fallback_database=_str_or_none(data.pop("fallback_database", None)),
            default_language=str(transcribe.get("default_language") or DEFAULT_LANGUAGE),
            on_new_files=str(transcribe.get("on_new_files") or DEFAULT_ON_NEW_FILES),
            snapshot_to_folder=bool(minutes.get("snapshot_to_folder", True)),
            audio_retention_days=int(retention if retention is not None else DEFAULT_RETENTION_DAYS),
        )
        s.extra = data
        return s

    def render(self) -> str:
        scope = self.calendar_scope
        if isinstance(scope, list):
            scope_text = "\n" + "".join(f"  - {c}\n" for c in scope)
            scope_text = scope_text.rstrip("\n")
        else:
            scope_text = str(scope or "all")
        return TEMPLATE.format(
            space_id=self.space_id or "",
            project=self.project or "",
            calendar_scope=scope_text,
            fallback_database=self.fallback_database or "",
            default_language=self.default_language,
            on_new_files=self.on_new_files,
            snapshot_to_folder="true" if self.snapshot_to_folder else "false",
            audio_retention_days=self.audio_retention_days,
        )

    @property
    def language_or_none(self) -> str | None:
        lang = (self.default_language or "auto").strip().lower()
        return None if lang in ("", "auto") else lang


def _str_or_none(v) -> str | None:
    if v is None:
        return None
    v = str(v).strip()
    return v or None


def load_settings(space_root: Path) -> SpaceSettings:
    path = SpaceDirs(space_root).settings
    if not path.exists():
        return SpaceSettings(project=Path(space_root).name)
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        data = {}
    s = SpaceSettings.from_dict(data)
    if not s.project:
        s.project = Path(space_root).name
    return s


def save_settings(space_root: Path, settings: SpaceSettings) -> Path:
    dirs = SpaceDirs(space_root)
    dirs.tool.mkdir(parents=True, exist_ok=True)
    tmp = dirs.settings.with_suffix(".yaml.tmp")
    tmp.write_text(settings.render(), encoding="utf-8")
    tmp.replace(dirs.settings)
    return dirs.settings


def ensure_space_id(space_root: Path) -> SpaceSettings:
    """Load settings, adding a space_id if missing (and saving)."""
    s = load_settings(space_root)
    if not s.space_id:
        s.space_id = new_space_id()
        save_settings(space_root, s)
    return s
