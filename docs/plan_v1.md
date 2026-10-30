# pm_infra v1: build plan

Status: proposed, 30 October 2026. Waiting for go. Scope is the "v1 scope" list in `claude_code_prompt_v1.md`; the `minutes` step, Notion and matching are not touched.

## What the machine has

| Checked | Result |
|---|---|
| GPU | RTX 4050 Laptop, 6141 MiB, driver 610.60 |
| Python | 3.13.1 system; `uv` 0.9.5 in `~/.local/bin` |
| ffmpeg | only inside conda env `misc_ml` (not on PATH); pm_infra brings its own |
| C# compiler | `C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe` present (ships with Windows) |
| `gh` CLI | not installed |
| `%OneDrive%` | points to the business drive `OneDrive - ETH juniors`. The personal drive is `%USERPROFILE%\OneDrive`; the personal space is `misc\Projects\` there, next to the existing project folders (decided 30 Oct). |
| HF cache | faster-whisper `small` and `medium` already in `~/.cache/huggingface`; no token stored |

## Components and how they talk

```
space\pm_infra\transcribe.exe  --double-click-->  env\python.exe -m pm_infra run-now --space <dir>
                                                     | registers the space if unknown
                                                     | takes .transcribing.lock, runs the engine in a console window
Tray app (pythonw -m pm_infra tray)
   polls every registered Audio Inbox/ every 5 s  -->  popup (Now / Later / Always)  -->  same engine, same lock
   daily cleanup (audio retention, _to_delete/)
   menu: New space, Move space…, Close space, Run on battery, Pause watcher, Uninstall, Quit
```

No inter-process messaging: launcher and tray run the same code against the same registry file and the same per-space lock, so whichever starts first processes the file and the other skips it.

### Python package `pm_infra` (in `src/pm_infra/`)

| Module | Responsibility |
|---|---|
| `cli.py` | `run-now`, `register`, `tray`, `new-space`, `cleanup`, `install-models`, `uninstall` subcommands |
| `spaces.py` | registry `spaces.json` keyed by `space_id`; create space (folders, settings, launcher, installer, README); move; locate; close |
| `settings.py` | `project_settings.yaml` read/write with defaults; `space_id` generation |
| `naming.py` | recording time from `YYYY-MM-DD_HHMM_` prefix, else ffprobe `creation_time`, else file mtime; meeting-folder name; `_2` suffixes |
| `inbox.py` | scan inbox, size-stable check (two polls ≥ 10 s apart, file opens for exclusive read), hand files to the engine, `_failed/` + `error.log` |
| `lock.py` | `.transcribing.lock`, hidden, created with `O_CREAT|O_EXCL`, JSON `{host, pid, file, started}`; stale takeover if same host and pid dead, or older than 6 h |
| `engine.py` | ffmpeg → `audio.m4a` + temp 16 kHz wav; pyannote diarization; faster-whisper transcription; merge; write `transcript.md`; unload models |
| `retention.py` | delete `audio.m4a` older than `audio_retention_days` once `transcript.md` exists; purge `_to_delete/` |
| `tray.py`, `popup.py` | pystray icon and menu; tkinter dialogs (folder picker, 3-button popup); psutil battery check; single-instance mutex |
| `log.py` | rotating log in `%LOCALAPPDATA%\pm_infra\logs\` |

### Engine choices (challenging the brief where it matters)

- **faster-whisper + pyannote.audio directly**, not WhisperX. WhisperX bundles both but pins old torch/pyannote versions and has broken on Windows repeatedly. The segment-to-speaker assignment WhisperX does is 30 lines: each Whisper segment gets the speaker with the largest time overlap. Word-level alignment is not needed for `[hh:mm:ss] SPEAKER_n:` lines.
- Models: `large-v3-turbo` (int8_float16, ~1.5 GB VRAM), fallback `medium` on CUDA out-of-memory; `pyannote/speaker-diarization-3.1` (needs token and accepted terms for it and `pyannote/segmentation-3.0`). Run diarization first, free it, then Whisper, so peak VRAM stays around 3 GB. VAD filter on.
- No token or no accepted terms: transcribe without speaker labels, header `speakers: none`, warning in the log and popup. The run never fails because of diarization alone.
- Known Windows pitfall: ctranslate2 needs cuDNN 9 and cuBLAS DLLs on PATH. Fix: import torch before faster-whisper (torch's wheel ships the DLLs) and add `torch\lib` to the DLL search path. Will be handled in `engine.py`.
- Audio: m4a input is moved as-is; anything else is re-encoded to AAC 96 kbit/s mono via ffmpeg; video gets audio extracted and the original goes to `_to_delete/`. ffmpeg + ffprobe come from the gyan.dev "essentials" build, downloaded by the installer into `%LOCALAPPDATA%\pm_infra\ffmpeg\`.

### Launcher `transcribe.exe`

A 40-line C# program, `install/launcher/transcribe.cs`, compiled on each laptop at install time with the `csc.exe` that ships with Windows. Locally compiled, unpacked, plain .NET Framework executables carry no mark-of-the-web and are not the pattern antivirus heuristics flag (PyInstaller bundles are). It:

1. takes its own directory's parent as the space,
2. looks for `%LOCALAPPDATA%\pm_infra\env\Scripts\python.exe`; if missing, shows a message box pointing at `install_pm_infra.cmd` next to it,
3. runs `python.exe -m pm_infra run-now --space "<space>"` in a visible console so progress is shown.

The compiled exe is kept in `%LOCALAPPDATA%\pm_infra\bin\` and copied into each new space's `pm_infra\`.

### Installer `install_pm_infra.cmd`

A ~30-line starter (same file lives in the repo root and in every space). Steps:

1. Source: `--from <folder>` uses a local checkout (how this laptop installs before a release exists); otherwise `curl.exe` (ships with Windows) downloads the latest release zip from GitHub.
2. Unpacks to `%LOCALAPPDATA%\pm_infra\app\` and hands over to `app\install\install.ps1` (run with `-ExecutionPolicy Bypass`, so no policy change).
3. `install.ps1`: downloads a private copy of `uv` → installs Python 3.12 → creates `env\` from the repo's `uv.lock` (torch CUDA 12.x wheels from the PyTorch index) → downloads ffmpeg → compiles the launcher → asks for the Hugging Face token (stored in `%LOCALAPPDATA%\pm_infra\hf_token`, file only, never in a space) → downloads models with `HF_HOME=%LOCALAPPDATA%\pm_infra\models\` → writes the HKCU `Run` entry for the tray and the HKCU `Uninstall` entry (shows in Settings → Apps) → creates the personal space → starts the tray.
4. Re-running it on an installed machine updates `app\` and `env\` and keeps spaces, token and models.

`uninstall.cmd` reverses the Run and Uninstall keys and removes `%LOCALAPPDATA%\pm_infra\`. Spaces are never touched.

Both registry keys get a `_changelog` entry when first applied on this machine.

## File layout

### Repository

```
pm_infra/
├── README.md, CLAUDE.md, LICENSE, .gitignore
├── pyproject.toml, uv.lock             package + pinned deps
├── install_pm_infra.cmd                starter (also copied into spaces)
├── install/
│   ├── install.ps1, uninstall.cmd
│   ├── launcher/transcribe.cs
│   └── space_README.md                 README placed in each space
├── src/pm_infra/                       modules above + assets/icon.png
├── tests/                              pytest
└── docs/                               spec history, diagrams, this plan
```

### `%LOCALAPPDATA%\pm_infra\`

```
app\            unpacked release (src, install, pyproject)
uv\uv.exe       private uv
python\         uv-managed CPython 3.12
env\            venv
ffmpeg\         ffmpeg.exe, ffprobe.exe
models\         HF_HOME: whisper turbo, medium, pyannote
bin\transcribe.exe
spaces.json     registry: {space_id: {path, name, last_seen, snooze_until}}
settings.json   run_on_battery, paused, installed_version
hf_token
logs\
```

## Tray behaviour details

- Polling, not filesystem events: OneDrive and cloud-only placeholders make `watchdog` unreliable. Five-second polls of a few folders cost nothing measurable.
- Popup "N new recordings in <space>": **Transcribe now** runs; **Later** snoozes that space for an hour or until another file arrives; **Always for this space** writes `on_new_files: always` into the space's `project_settings.yaml` (shared by every install, as the spec wants).
- On battery with "Run on battery" off, the popup offers "Transcribe when plugged in" and the run starts on the next poll that sees AC power.
- Missing space folder: menu shows it with "Locate…"; the chosen folder is accepted only if its `project_settings.yaml` carries the same `space_id`.
- Move space…: pause watcher, `shutil.move`, update registry, resume. Refuses while a lock is held.
- Cleanup runs at tray start and every 24 h.
- Extra item **Quit** (not in the spec, needed in practice).

## Test plan

1. **Unit (pytest, no GPU):** naming and date parsing (prefix, metadata, mtime, `_2` suffix); retention with a fake clock (keeps audio without transcript, deletes expired, purges `_to_delete/`); lock (create, refuse second, stale takeover); registry move and locate (`space_id` match and mismatch); settings defaults and round-trip; space creation layout.
2. **Engine smoke:** a 30-second clip through the full pipeline, with and without token.
3. **First real test:** the 62-minute German MP3, timing both passes.
4. **Manual:** install from `--from`, popup paths, battery toggle, New space, Move space via tray and via Explorer, Close space, uninstall.

## Expected speed on the RTX 4050 (estimates, to be measured in step 3)

| Pass | 62-minute file |
|---|---|
| Whisper large-v3-turbo, int8_float16, VAD | ~1 to 1.5 min |
| pyannote 3.1 diarization | ~1.5 to 3 min |
| ffmpeg + model loads | ~20 s |
| Total without speakers | ~1.5 to 2.5 min |
| Total with speakers | ~3 to 5 min |
| Fallback `medium` instead of turbo | adds ~2 min |

First run after install is slower while cuDNN autotunes.

## GitHub

No `gh` CLI on the machine. Either install it user-scope (`winget install GitHub.cli`) so the repo can be created from here, or create `pm_infra` (public, empty, no README) in the browser and the local `main` is pushed to it. Releases: a tag triggers a GitHub Actions workflow that zips the repo as `pm_infra-<version>.zip`; the installer downloads the latest.

## Decisions taken on 30 October 2026

- Personal space: `OneDrive\misc\Projects\` itself (the tool adds `pm_infra\` and `Meetings\` next to the existing project folders).
- Speaker labels: yes, with a Hugging Face token.
- Launcher: C# compiled at install time.
- GitHub: public repo `pm_infra` from the start, MIT licence.
- Popup: ask first (`on_new_files: ask`).
- Test recordings: a long and a short one, in `..	est_audio\` outside the repo.
- The brief was written by Claude from an earlier conversation; the 62-minute German test file it mentions was dropped.
