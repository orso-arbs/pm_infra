Plan (don't build yet) v1 of `pm_infra`, a local meeting-transcription tool on my Windows laptop. `README.md` in this folder is the spec and `CLAUDE.md` has the working rules; the diagrams in the README show context, containers and the recording flow. Build only what's listed under "v1" below. Ask me open questions first, then propose the plan. Also set up git for this folder and propose how to create the public GitHub repo `pm_infra`.

## Machine
- Dell XPS 15, i7-13700H, 32 GB RAM, RTX 4050 Laptop 6 GB VRAM, Windows 11, PowerShell 7.6. No admin rights needed or wanted for anything.
- Conda env `misc_ml` already has openai-whisper, torch with CUDA working, ffmpeg (conda-forge). Don't modify it; pm_infra gets its own environment.
- Cached openai-whisper models in `%USERPROFILE%\.cache\whisper` (base, small, medium).
- Conda + PowerShell quirk: if `conda install` errors with "invalid choice: ''", run `$Env:_CE_M=$null; $Env:_CE_CONDA=$null`.
- OneDrive is at `%OneDrive%`. Paths contain spaces.

## Engine (challenge it if something's better)
- faster-whisper with `large-v3-turbo` on CUDA (int8_float16), `medium` as fallback.
- Speaker labels via pyannote (or WhisperX, which bundles it). Needs my Hugging Face token once; store it per user in AppData, never in the repo.
- Models cached under `%LOCALAPPDATA%\pm_infra\models\`, not in a synced folder.
- Load the model only for a run; unload when idle.

## v1 scope
1. **Repo `pm_infra`** (public GitHub): no tokens or personal paths committed.
2. **Installer `install_pm_infra.cmd`**: small starter that sets up everything in `%LOCALAPPDATA%\pm_infra\` (environment, models, app), adds the tray app to start at login, registers an uninstall entry under HKCU so it shows in Windows Settings → Apps, asks for the HF token once, and finally creates my personal space at `%OneDrive%\misc\projects\misc_projects\`.
3. **Space layout** exactly as in the README: `Meetings/` and `pm_infra/` with `Audio Inbox/`, `_failed/`, `_to_delete/`, `transcribe.exe`, `install_pm_infra.cmd`, `project_settings.yaml`, `README.md`, hidden `.transcribing.lock`. `project_settings.yaml` gets a generated `space_id` and `calendar_scope: all`.
4. **`transcribe`** (per README "Meeting folders" and "Transcript format"):
   - wait until a file has finished syncing (size stable)
   - recording date/time from the `YYYY-MM-DD_HHMM_` prefix, else media metadata, else file date
   - create `Meetings/YYYY-MM-DD_HHMM_<original name>/` with `audio.m4a` and `transcript.md` (YAML header incl. `recorded_start`/`recorded_end`, `[hh:mm:ss] SPEAKER_n:` lines)
   - video → audio only, original video to `_to_delete/`
   - failures to `_failed/` with `error.log`
   - `.transcribing.lock` so two installs never process the same file
5. **`transcribe.exe`** in each space: a small launcher (not a bundled app) that processes that space's inbox now and registers the space if the app doesn't know it yet. Propose how to build it so antivirus doesn't flag it.
6. **Tray app**, minimal:
   - watches all registered spaces; popup before running: Transcribe now · Later · Always for this space
   - menu: New space (folder picker, `calendar_scope: all`), Move space…, Close space, Run on battery (off by default), Pause watcher, Uninstall
   - daily cleanup: delete `audio.m4a` older than `audio_retention_days` (14) once `transcript.md` exists; delete expired files in `_to_delete/`
7. **Movable spaces**: registry of spaces in `%LOCALAPPDATA%\pm_infra\` keyed by `space_id`; no absolute paths stored inside a space. Move space… pauses the watcher, moves the folder, updates the registry. If a registered folder is missing, the tray asks me to locate it and recognises it by `space_id`.

## Not in v1
The `minutes` step, Notion, calendar matching, folder renaming after a match, team calendar picker, update checks, iPhone Shortcut (I'll build that myself from the README).

## Deliverable of this planning step
A short plan: components and how they talk to each other, file layout of the repo and of `%LOCALAPPDATA%\pm_infra\`, how the installer, launcher and tray app are built and started, install steps, test plan (unit tests for naming, retention, lock and move/locate; first real test: a 62-min German info-session MP3 I have), and an estimated transcription speed on my GPU with and without speaker labels. Then wait for my go.
