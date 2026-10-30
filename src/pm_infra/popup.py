"""Small tkinter dialogs for the tray app. All of them run on the tk main thread; other threads
go through UI.call(), which blocks until the dialog is answered."""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog
from typing import Any, Callable

TITLE = "pm_infra"


class UI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title(TITLE)
        self._jobs: queue.Queue = queue.Queue()
        self.root.after(100, self._pump)

    # ---- threading bridge -------------------------------------------------
    def _pump(self) -> None:
        try:
            while True:
                fn, args, done, box = self._jobs.get_nowait()
                try:
                    box["result"] = fn(*args)
                except Exception as e:  # noqa: BLE001
                    box["error"] = e
                done.set()
        except queue.Empty:
            pass
        self.root.after(100, self._pump)

    def call(self, fn: Callable, *args) -> Any:
        if threading.current_thread() is threading.main_thread():
            return fn(*args)
        done = threading.Event()
        box: dict = {}
        self._jobs.put((fn, args, done, box))
        done.wait()
        if "error" in box:
            raise box["error"]
        return box.get("result")

    def quit(self) -> None:
        self.root.after(0, self.root.quit)

    # ---- dialogs ------------------------------------------------------------
    def _top(self, title: str) -> tk.Toplevel:
        win = tk.Toplevel(self.root)
        win.title(title)
        win.resizable(False, False)
        win.attributes("-topmost", True)
        win.lift()
        win.focus_force()
        return win

    def ask_new_files(self, space_name: str, count: int, battery_blocked: bool) -> str:
        """Returns 'now' | 'when_plugged' | 'later' | 'always' | 'closed'."""
        result = {"value": "closed"}
        win = self._top(TITLE)
        noun = "recording" if count == 1 else "recordings"
        tk.Label(win, text=f"{count} new {noun} in {space_name}", font=("Segoe UI", 11), padx=20, pady=14).pack()
        if battery_blocked:
            tk.Label(win, text="On battery: \"Run on battery\" is off in the tray menu.",
                     font=("Segoe UI", 9), fg="#666").pack(padx=20)
        row = tk.Frame(win, padx=16, pady=12)
        row.pack()

        def choose(v: str):
            result["value"] = v
            win.destroy()

        first = ("Transcribe when plugged in", "when_plugged") if battery_blocked else ("Transcribe now", "now")
        for text, value in (first, ("Later", "later"), ("Always for this space", "always")):
            tk.Button(row, text=text, width=24 if value == "when_plugged" else 18,
                      command=lambda v=value: choose(v)).pack(side="left", padx=4)
        win.protocol("WM_DELETE_WINDOW", lambda: choose("closed"))
        win.bind("<Escape>", lambda e: choose("closed"))
        self._center(win)
        win.wait_window()
        return result["value"]

    def pick_folder(self, title: str, initial: str | None = None) -> Path | None:
        self.root.attributes("-topmost", True)
        chosen = filedialog.askdirectory(title=title, initialdir=initial or None, mustexist=True, parent=self.root)
        self.root.attributes("-topmost", False)
        return Path(chosen) if chosen else None

    def confirm(self, title: str, message: str) -> bool:
        self.root.attributes("-topmost", True)
        ok = messagebox.askyesno(title, message, parent=self.root)
        self.root.attributes("-topmost", False)
        return bool(ok)

    def info(self, title: str, message: str) -> None:
        self.root.attributes("-topmost", True)
        messagebox.showinfo(title, message, parent=self.root)
        self.root.attributes("-topmost", False)

    def error(self, title: str, message: str) -> None:
        self.root.attributes("-topmost", True)
        messagebox.showerror(title, message, parent=self.root)
        self.root.attributes("-topmost", False)

    def ask_text(self, title: str, prompt: str, default: str = "") -> str | None:
        self.root.attributes("-topmost", True)
        value = simpledialog.askstring(title, prompt, initialvalue=default, parent=self.root)
        self.root.attributes("-topmost", False)
        return value

    @staticmethod
    def _center(win: tk.Toplevel) -> None:
        win.update_idletasks()
        w, h = win.winfo_width(), win.winfo_height()
        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        win.geometry(f"+{(sw - w) // 2}+{(sh - h) // 3}")
