"""Per-user Windows integration: start at login (HKCU Run) and the Settings > Apps uninstall entry.
No admin rights: everything is under HKEY_CURRENT_USER."""

from __future__ import annotations

import os
import sys
import winreg
from pathlib import Path

from pm_infra import __version__, paths

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "pm_infra"
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\pm_infra"


def autostart_command() -> str:
    return f'"{paths.env_pythonw()}" -m pm_infra tray'


def set_autostart() -> None:
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
        winreg.SetValueEx(k, RUN_VALUE, 0, winreg.REG_SZ, autostart_command())


def remove_autostart() -> None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, RUN_VALUE)
    except FileNotFoundError:
        pass


def folder_size_kb(root: Path) -> int:
    total = 0
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(dirpath, f))
            except OSError:
                pass
    return total // 1024


def set_uninstall_entry() -> None:
    root = paths.app_root()
    uninstall = root / "app" / "install" / "uninstall.cmd"
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as k:
        winreg.SetValueEx(k, "DisplayName", 0, winreg.REG_SZ, "pm_infra")
        winreg.SetValueEx(k, "DisplayVersion", 0, winreg.REG_SZ, __version__)
        winreg.SetValueEx(k, "Publisher", 0, winreg.REG_SZ, "pm_infra")
        winreg.SetValueEx(k, "InstallLocation", 0, winreg.REG_SZ, str(root))
        winreg.SetValueEx(k, "UninstallString", 0, winreg.REG_SZ, f'"{uninstall}"')
        winreg.SetValueEx(k, "DisplayIcon", 0, winreg.REG_SZ, str(paths.env_python()))
        winreg.SetValueEx(k, "NoModify", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(k, "NoRepair", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(k, "EstimatedSize", 0, winreg.REG_DWORD, min(folder_size_kb(root), 0x7FFFFFFF))


def remove_uninstall_entry() -> None:
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY)
    except FileNotFoundError:
        pass


def setup_all() -> None:
    set_autostart()
    set_uninstall_entry()


def remove_all() -> None:
    remove_autostart()
    remove_uninstall_entry()


if __name__ == "__main__":
    (remove_all if "--remove" in sys.argv else setup_all)()
