"""Spaces registry (by space_id) and space lifecycle: create, register, move, locate, close."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path

from pm_infra import paths
from pm_infra.paths import SpaceDirs
from pm_infra.settings import SpaceSettings, ensure_space_id, load_settings, new_space_id, save_settings


class SpaceError(Exception):
    pass


@dataclass
class Space:
    space_id: str
    path: str
    name: str
    last_seen: str | None = None
    snooze_until: str | None = None

    @property
    def root(self) -> Path:
        return Path(self.path)

    @property
    def dirs(self) -> SpaceDirs:
        return SpaceDirs(self.root)

    def exists(self) -> bool:
        return self.dirs.settings.exists()


class Registry:
    def __init__(self, file: Path | None = None):
        self.file = file or paths.registry_file()
        self.spaces: dict[str, Space] = {}
        self.load()

    def load(self) -> None:
        self.spaces = {}
        if not self.file.exists():
            return
        try:
            data = json.loads(self.file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        for sid, entry in (data.get("spaces") or {}).items():
            self.spaces[sid] = Space(
                space_id=sid,
                path=entry.get("path", ""),
                name=entry.get("name") or Path(entry.get("path", "")).name,
                last_seen=entry.get("last_seen"),
                snooze_until=entry.get("snooze_until"),
            )

    def save(self) -> None:
        self.file.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "spaces": {
                sid: {k: v for k, v in asdict(s).items() if k != "space_id"} for sid, s in self.spaces.items()
            }
        }
        tmp = self.file.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(self.file)

    def all(self) -> list[Space]:
        return sorted(self.spaces.values(), key=lambda s: s.name.lower())

    def get(self, space_id: str) -> Space | None:
        return self.spaces.get(space_id)

    def by_path(self, path: Path) -> Space | None:
        target = _norm(path)
        for s in self.spaces.values():
            if _norm(s.root) == target:
                return s
        return None

    def put(self, space: Space) -> Space:
        space.last_seen = datetime.now().isoformat(timespec="seconds")
        self.spaces[space.space_id] = space
        self.save()
        return space

    def remove(self, space_id: str) -> None:
        self.spaces.pop(space_id, None)
        self.save()


def _norm(p: Path) -> str:
    return str(Path(p).resolve()).rstrip("\\/").lower()


def create_space(root: Path, name: str | None = None, registry: Registry | None = None) -> Space:
    """Create the two-part layout in `root` (which may already hold other files) and register it."""
    root = Path(root)
    dirs = SpaceDirs(root)
    if dirs.settings.exists():
        return register_space(root, registry)
    dirs.ensure()
    settings = SpaceSettings(space_id=new_space_id(), project=name or root.name)
    save_settings(root, settings)
    place_tool_files(dirs)
    reg = registry or Registry()
    return reg.put(Space(space_id=settings.space_id, path=str(root), name=settings.project))


def place_tool_files(dirs: SpaceDirs) -> None:
    """Copy launcher, installer starter and README into the space's pm_infra folder, if available."""
    launcher = paths.bin_dir() / paths.LAUNCHER_FILE
    installer = paths.app_source() / paths.INSTALLER_FILE
    readme = paths.app_source() / "install" / "space_README.md"
    for src, dst in ((launcher, dirs.launcher), (installer, dirs.installer), (readme, dirs.readme)):
        if src.exists():
            shutil.copyfile(src, dst)


def register_space(root: Path, registry: Registry | None = None) -> Space:
    """Register an existing space folder (e.g. a team space), adding a space_id if it has none."""
    root = Path(root)
    dirs = SpaceDirs(root)
    if not dirs.looks_like_space():
        raise SpaceError(
            f"{root} is not a space: no {paths.SPACE_DIR}\\{paths.SETTINGS_FILE} or {paths.INBOX_DIR} inside it"
        )
    dirs.ensure()
    settings = ensure_space_id(root)
    reg = registry or Registry()
    existing = reg.get(settings.space_id)
    if existing and _norm(existing.root) != _norm(root) and existing.exists():
        raise SpaceError(
            f"Space {settings.space_id} is already registered at {existing.root}. "
            "If this is a copy, delete the space_id line in its project_settings.yaml to make it a new space."
        )
    return reg.put(Space(space_id=settings.space_id, path=str(root), name=settings.project or root.name))


def move_space(space_id: str, new_parent: Path, registry: Registry | None = None) -> Space:
    reg = registry or Registry()
    space = reg.get(space_id)
    if not space:
        raise SpaceError(f"Unknown space {space_id}")
    if not space.exists():
        raise SpaceError(f"Space folder is missing: {space.root}. Use Locate instead.")
    if space.dirs.lock.exists():
        raise SpaceError("A transcription is running in this space. Try again when it has finished.")
    new_parent = Path(new_parent)
    if not new_parent.is_dir():
        raise SpaceError(f"Destination folder does not exist: {new_parent}")
    dest = new_parent / space.root.name
    if dest.exists():
        raise SpaceError(f"Destination already exists: {dest}")
    shutil.move(str(space.root), str(dest))
    space.path = str(dest)
    return reg.put(space)


def locate_space(space_id: str, candidate: Path, registry: Registry | None = None) -> Space:
    reg = registry or Registry()
    space = reg.get(space_id)
    if not space:
        raise SpaceError(f"Unknown space {space_id}")
    candidate = Path(candidate)
    found = load_settings(candidate) if SpaceDirs(candidate).settings.exists() else None
    if not found or found.space_id != space_id:
        raise SpaceError(f"{candidate} is not the space '{space.name}' (space_id does not match)")
    space.path = str(candidate)
    space.name = found.project or candidate.name
    return reg.put(space)


def close_space(space_id: str, delete_audio: bool, registry: Registry | None = None) -> list[Path]:
    """Unregister; optionally delete remaining audio (meeting audio and _to_delete). Transcripts stay."""
    reg = registry or Registry()
    space = reg.get(space_id)
    if not space:
        raise SpaceError(f"Unknown space {space_id}")
    deleted: list[Path] = []
    if delete_audio and space.exists():
        dirs = space.dirs
        for f in dirs.meetings.glob("*/audio*.m4a"):
            f.unlink()
            deleted.append(f)
        if dirs.to_delete.exists():
            for f in dirs.to_delete.iterdir():
                if f.is_file():
                    f.unlink()
                    deleted.append(f)
    reg.remove(space_id)
    return deleted


def set_on_new_files(space_root: Path, value: str) -> None:
    s = load_settings(space_root)
    s.on_new_files = value
    save_settings(space_root, s)
