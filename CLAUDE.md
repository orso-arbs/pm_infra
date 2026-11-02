# pm_infra: working rules for Claude Code

## What this is
A local meeting-transcription suite for one Windows laptop, with optional team spaces. `README.md` is the spec. The current milestone is v1; its brief is `docs/claude_code_prompt_v1.md`.

## Environment
- Windows 11, PowerShell 7.6, Dell XPS 15, RTX 4050 Laptop (6 GB VRAM), 32 GB RAM.
- Never require admin rights.
- Never modify the conda env `misc_ml`; pm_infra has its own environment under `%LOCALAPPDATA%\pm_infra\`.
- Paths contain spaces (OneDrive). Quote every path.
- Conda + PowerShell quirk: if `conda install` errors with "invalid choice: ''", run `$Env:_CE_M=$null; $Env:_CE_CONDA=$null`.

## Rules
- Plan before building anything non-trivial, and wait for my go.
- Nothing personal in the repo: no tokens, no absolute paths from my machine, no recordings or transcripts. The Hugging Face token lives in AppData only.
- Nothing inside a space may store an absolute path; spaces must stay movable (see README, *Moving a space*).
- Keep `README.md` in sync with what's built. When a design decision changes, update the *Decisions log* in the same change.
- Destructive file actions (deleting audio, moving spaces) only as specified in the README, and with tests.
- Ask short, concrete questions when something in the spec is ambiguous; push back when something in it looks wrong.

## Repo layout
See the *Repository* section in `README.md`. The two diagrams in `README.md` are hand-written SVG in `docs/diagrams/*.svg` (self-contained, light and dark via `prefers-color-scheme`); if the architecture changes, update them and the prose next to them.
