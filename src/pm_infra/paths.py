"""Where pm_infra keeps things on the laptop, and the fixed names inside a space.

Everything on the laptop lives under %LOCALAPPDATA%/pm_infra (override with
PM_INFRA_HOME, used by tests). Nothing inside a space ever stores an absolute path.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

APP_NAME = "pm_infra"

# Fixed names inside a space
SPACE_DIR = "pm_infra"
MEETINGS_DIR = "Meetings"
INBOX_DIR = "Audio Inbox"
FAILED_DIR = "_failed"
TO_DELETE_DIR = "_to_delete"
SETTINGS_FILE = "project_settings.yaml"
LOCK_FILE = ".transcribing.lock"
LAUNCHER_FILE = "transcribe.exe"
INSTALLER_FILE = "install_pm_infra.cmd"
SPACE_README = "README.md"
ERROR_LOG = "error.log"


def app_root() -> Path:
    override = os.environ.get("PM_INFRA_HOME")
    if override:
        return Path(override)
    return Path(os.environ["LOCALAPPDATA"]) / APP_NAME


def app_source() -> Path:
    return app_root() / "app"


def registry_file() -> Path:
    return app_root() / "spaces.json"


def app_settings_file() -> Path:
    return app_root() / "settings.json"


def token_file() -> Path:
    return app_root() / "hf_token"


def models_dir() -> Path:
    return app_root() / "models"


def ffmpeg_dir() -> Path:
    return app_root() / "ffmpeg"


def logs_dir() -> Path:
    return app_root() / "logs"


def tmp_dir() -> Path:
    return app_root() / "tmp"


def bin_dir() -> Path:
    return app_root() / "bin"


def env_dir() -> Path:
    return app_root() / "env"


def env_python() -> Path:
    return env_dir() / "Scripts" / "python.exe"


def env_pythonw() -> Path:
    return env_dir() / "Scripts" / "pythonw.exe"


def read_token() -> str | None:
    try:
        text = token_file().read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return text or None


def tool_exe(name: str) -> str:
    """ffmpeg/ffprobe: the private copy first, then PATH."""
    private = ffmpeg_dir() / f"{name}.exe"
    if private.exists():
        return str(private)
    found = shutil.which(name)
    if found:
        return found
    raise FileNotFoundError(
        f"{name}.exe not found in {ffmpeg_dir()} or on PATH. Re-run install_pm_infra.cmd."
    )


class SpaceDirs:
    """The folders of one space, derived from its root."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.tool = self.root / SPACE_DIR
        self.meetings = self.root / MEETINGS_DIR
        self.inbox = self.tool / INBOX_DIR
        self.failed = self.tool / FAILED_DIR
        self.to_delete = self.tool / TO_DELETE_DIR
        self.settings = self.tool / SETTINGS_FILE
        self.lock = self.tool / LOCK_FILE
        self.launcher = self.tool / LAUNCHER_FILE
        self.installer = self.tool / INSTALLER_FILE
        self.readme = self.tool / SPACE_README

    def ensure(self) -> None:
        for d in (self.meetings, self.inbox, self.failed, self.to_delete):
            d.mkdir(parents=True, exist_ok=True)

    def looks_like_space(self) -> bool:
        return self.settings.exists() or self.inbox.exists()
