"""Tray app: watches every registered space's inbox, asks before running, starts runs in their own
console window, cleans up old audio daily, and offers the space menu."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import datetime, timedelta
from pathlib import Path

import psutil
import pystray
from PIL import Image, ImageDraw

from pm_infra import __version__, paths, retention
from pm_infra.inbox import StabilityTracker, candidate_files
from pm_infra.log import get_logger
from pm_infra.popup import UI
from pm_infra.settings import load_settings
from pm_infra.spaces import Registry, Space, SpaceError, close_space, create_space, locate_space, move_space, set_on_new_files

POLL_SECONDS = 5
SNOOZE = timedelta(hours=1)
CLEANUP_EVERY = timedelta(hours=24)
CREATE_NEW_CONSOLE = 0x00000010
MUTEX_NAME = "Local\\pm_infra_tray"


class AppSettings:
    def __init__(self):
        self.run_on_battery = False
        self.paused = False
        self.load()

    def load(self) -> None:
        try:
            data = json.loads(paths.app_settings_file().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        self.run_on_battery = bool(data.get("run_on_battery", False))
        self.paused = bool(data.get("paused", False))

    def save(self) -> None:
        paths.app_settings_file().parent.mkdir(parents=True, exist_ok=True)
        paths.app_settings_file().write_text(
            json.dumps({"run_on_battery": self.run_on_battery, "paused": self.paused}, indent=2), encoding="utf-8"
        )


def single_instance() -> bool:
    if os.name != "nt":
        return True
    import ctypes

    ctypes.windll.kernel32.CreateMutexW(None, False, MUTEX_NAME)
    return ctypes.windll.kernel32.GetLastError() != 183  # ERROR_ALREADY_EXISTS


def make_icon(paused: bool = False) -> Image.Image:
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    color = (120, 120, 120, 255) if paused else (15, 110, 86, 255)
    d.rounded_rectangle((4, 4, 60, 60), radius=14, fill=color)
    d.ellipse((22, 14, 42, 38), fill=(255, 255, 255, 255))   # microphone head
    d.rectangle((29, 38, 35, 48), fill=(255, 255, 255, 255))  # stem
    d.rectangle((20, 48, 44, 52), fill=(255, 255, 255, 255))  # base
    return img


def plugged_in() -> bool:
    try:
        b = psutil.sensors_battery()
    except Exception:  # noqa: BLE001
        return True
    return True if b is None else bool(b.power_plugged)


class TrayApp:
    def __init__(self):
        self.log = get_logger("tray")
        self.reg = Registry()
        self.settings = AppSettings()
        self.ui = UI()
        self.trackers: dict[str, StabilityTracker] = {}
        self.running: dict[str, subprocess.Popen] = {}
        self.prompting: set[str] = set()
        self.when_plugged: set[str] = set()
        self.missing: set[str] = set()
        self.snoozed: dict[str, datetime] = {}
        self.busy = threading.Lock()
        self.stop = threading.Event()
        self.icon: pystray.Icon | None = None

    # ---- lifecycle ------------------------------------------------------------
    def run(self) -> None:
        if not single_instance():
            self.log.info("tray already running; exiting")
            return
        self.log.info("tray starting, version %s", __version__)
        self.icon = pystray.Icon("pm_infra", make_icon(self.settings.paused), "pm_infra", menu=self.menu())
        self.icon.run_detached()
        threading.Thread(target=self.watch_loop, name="watcher", daemon=True).start()
        threading.Thread(target=self.cleanup_loop, name="cleanup", daemon=True).start()
        try:
            self.ui.root.mainloop()
        finally:
            self.stop.set()
            if self.icon:
                self.icon.stop()
            self.log.info("tray stopped")

    def quit(self) -> None:
        self.stop.set()
        self.ui.quit()

    # ---- watcher ----------------------------------------------------------------
    def watch_loop(self) -> None:
        while not self.stop.is_set():
            try:
                if not self.busy.locked():
                    self.reg.load()
                    for space in self.reg.all():
                        self.tick(space)
            except Exception:  # noqa: BLE001
                self.log.exception("watcher error")
            self.stop.wait(POLL_SECONDS)

    def tick(self, space: Space) -> None:
        sid = space.space_id
        proc = self.running.get(sid)
        if proc is not None:
            if proc.poll() is None:
                return
            self.log.info("run in %s finished with code %s", space.name, proc.returncode)
            del self.running[sid]
            self.trackers.pop(sid, None)
        if not space.exists():
            if sid not in self.missing:
                self.log.warning("space folder missing: %s (%s)", space.name, space.root)
                self.missing.add(sid)
                self.refresh_menu()
            return
        if sid in self.missing:
            self.missing.discard(sid)
            self.refresh_menu()
        if self.settings.paused or sid in self.prompting:
            return
        tracker = self.trackers.setdefault(sid, StabilityTracker())
        ready = [f for f in candidate_files(space.dirs.inbox) if tracker.ready(f)]
        if not ready:
            return
        if sid in self.when_plugged:
            if plugged_in():
                self.when_plugged.discard(sid)
                self.start_run(space)
            return
        until = self.snoozed.get(sid)
        if until and datetime.now() < until:
            return
        settings = load_settings(space.root)
        if settings.on_new_files.lower() == "always":
            if self.battery_ok():
                self.start_run(space)
            else:
                self.when_plugged.add(sid)
            return
        self.prompting.add(sid)
        threading.Thread(target=self.prompt, args=(space, len(ready)), daemon=True).start()

    def prompt(self, space: Space, count: int) -> None:
        try:
            blocked = not self.battery_ok()
            answer = self.ui.call(self.ui.ask_new_files, space.name, count, blocked)
            self.log.info("popup for %s (%d files): %s", space.name, count, answer)
            if answer == "now":
                self.start_run(space)
            elif answer == "when_plugged":
                self.when_plugged.add(space.space_id)
            elif answer == "always":
                set_on_new_files(space.root, "always")
                if self.battery_ok():
                    self.start_run(space)
                else:
                    self.when_plugged.add(space.space_id)
            else:  # later / closed
                self.snoozed[space.space_id] = datetime.now() + SNOOZE
        finally:
            self.prompting.discard(space.space_id)

    def battery_ok(self) -> bool:
        return self.settings.run_on_battery or plugged_in()

    def start_run(self, space: Space) -> None:
        if space.space_id in self.running:
            return
        cmd = [str(paths.env_python()), "-m", "pm_infra", "run-now", "--space", str(space.root), "--pause", "error"]
        self.log.info("starting run in %s", space.name)
        self.running[space.space_id] = subprocess.Popen(cmd, creationflags=CREATE_NEW_CONSOLE, cwd=str(paths.app_root()))
        self.snoozed.pop(space.space_id, None)

    # ---- cleanup ------------------------------------------------------------------
    def cleanup_loop(self) -> None:
        while not self.stop.is_set():
            try:
                self.cleanup_all()
            except Exception:  # noqa: BLE001
                self.log.exception("cleanup error")
            self.stop.wait(CLEANUP_EVERY.total_seconds())

    def cleanup_all(self) -> None:
        for space in self.reg.all():
            if not space.exists():
                continue
            days = load_settings(space.root).audio_retention_days
            deleted = retention.cleanup_space(space.root, days)
            for f in deleted:
                self.log.info("retention: deleted %s", f)

    # ---- menu -----------------------------------------------------------------------
    def menu(self) -> pystray.Menu:
        M = pystray.MenuItem
        return pystray.Menu(
            M(lambda item: f"pm_infra {__version__}", None, enabled=False),
            M(lambda item: self.status_text(), None, enabled=False),
            pystray.Menu.SEPARATOR,
            M("New space...", self.act_new_space),
            M("Move space", pystray.Menu(lambda: self.space_items(self.act_move_space, exclude_missing=True))),
            M("Locate missing space", pystray.Menu(lambda: self.space_items(self.act_locate, only_missing=True)),
              visible=lambda item: bool(self.missing)),
            M("Close space", pystray.Menu(lambda: self.space_items(self.act_close_space))),
            M("Transcribe now", pystray.Menu(lambda: self.space_items(self.act_run_now, exclude_missing=True))),
            pystray.Menu.SEPARATOR,
            M("Run on battery", self.act_toggle_battery, checked=lambda item: self.settings.run_on_battery),
            M("Pause watcher", self.act_toggle_pause, checked=lambda item: self.settings.paused),
            pystray.Menu.SEPARATOR,
            M("Open log folder", lambda: webbrowser.open(str(paths.logs_dir()))),
            M("Uninstall...", self.act_uninstall),
            M("Quit", lambda: self.quit()),
        )

    def status_text(self) -> str:
        n = len(self.reg.spaces)
        if self.settings.paused:
            return "Watcher paused"
        if self.running:
            return "Transcribing..."
        return f"Watching {n} space{'s' if n != 1 else ''}"

    def space_items(self, action, exclude_missing: bool = False, only_missing: bool = False):
        items = []
        for s in self.reg.all():
            missing = s.space_id in self.missing
            if (exclude_missing and missing) or (only_missing and not missing):
                continue
            label = f"{s.name}  (missing)" if missing else s.name
            items.append(pystray.MenuItem(label, lambda icon, item, sp=s: action(sp)))
        if not items:
            items.append(pystray.MenuItem("(none)", None, enabled=False))
        return items

    def refresh_menu(self) -> None:
        if self.icon:
            self.icon.update_menu()

    # ---- actions -----------------------------------------------------------------
    def act_new_space(self, *_):
        folder = self.ui.call(self.ui.pick_folder, "Choose the folder that becomes the space")
        if not folder:
            return
        name = self.ui.call(self.ui.ask_text, "New space", "Name of this space:", folder.name)
        if not name:
            return
        try:
            space = create_space(folder, name, self.reg)
        except (SpaceError, OSError) as e:
            self.ui.call(self.ui.error, "New space", str(e))
            return
        self.log.info("new space %s at %s", space.name, space.root)
        self.ui.call(self.ui.info, "New space", f"{space.name} is set up.\n\nDrop recordings into:\n{space.dirs.inbox}")
        self.refresh_menu()

    def act_move_space(self, space: Space):
        parent = self.ui.call(self.ui.pick_folder, f"Choose the new parent folder for '{space.name}'")
        if not parent:
            return
        with self.busy:
            try:
                moved = move_space(space.space_id, parent, self.reg)
            except (SpaceError, OSError) as e:
                self.ui.call(self.ui.error, "Move space", str(e))
                return
        self.trackers.pop(space.space_id, None)
        self.log.info("moved space %s to %s", moved.name, moved.root)
        self.ui.call(self.ui.info, "Move space",
                     f"{moved.name} now lives at:\n{moved.root}\n\nRemember to update the inbox path in the iPhone Shortcut.")
        self.refresh_menu()

    def act_locate(self, space: Space):
        folder = self.ui.call(self.ui.pick_folder, f"Where is '{space.name}' now?")
        if not folder:
            return
        try:
            found = locate_space(space.space_id, folder, self.reg)
        except SpaceError as e:
            self.ui.call(self.ui.error, "Locate space", str(e))
            return
        self.missing.discard(space.space_id)
        self.trackers.pop(space.space_id, None)
        self.log.info("located space %s at %s", found.name, found.root)
        self.refresh_menu()

    def act_close_space(self, space: Space):
        if not self.ui.call(self.ui.confirm, "Close space",
                            f"Stop watching '{space.name}'?\n\nTranscripts and minutes stay. The folder is not deleted."):
            return
        delete_audio = False
        if space.exists():
            delete_audio = self.ui.call(self.ui.confirm, "Close space",
                                        "Also delete the remaining audio files in this space now?\n\n"
                                        "(audio.m4a in meeting folders and everything in _to_delete)")
        try:
            deleted = close_space(space.space_id, delete_audio, self.reg)
        except (SpaceError, OSError) as e:
            self.ui.call(self.ui.error, "Close space", str(e))
            return
        self.trackers.pop(space.space_id, None)
        self.missing.discard(space.space_id)
        self.log.info("closed space %s, deleted %d audio files", space.name, len(deleted))
        self.refresh_menu()

    def act_run_now(self, space: Space):
        if not space.exists():
            return
        self.start_run(space)

    def act_toggle_battery(self, *_):
        self.settings.run_on_battery = not self.settings.run_on_battery
        self.settings.save()

    def act_toggle_pause(self, *_):
        self.settings.paused = not self.settings.paused
        self.settings.save()
        if self.icon:
            self.icon.icon = make_icon(self.settings.paused)

    def act_uninstall(self, *_):
        if not self.ui.call(self.ui.confirm, "Uninstall pm_infra",
                            "Remove pm_infra from this laptop (app, environment, models)?\n\nSpaces are never touched."):
            return
        script = paths.app_source() / "install" / "uninstall.cmd"
        subprocess.Popen(["cmd.exe", "/c", str(script), "--yes"], creationflags=CREATE_NEW_CONSOLE)
        self.quit()


def main() -> int:
    TrayApp().run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
