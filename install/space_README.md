# This folder belongs to pm_infra

pm_infra turns meeting recordings into transcripts, filed one folder per meeting.

- **Audio Inbox/**: drop recordings here (m4a, mp3, wav, mp4, mov, ...). Anyone with access to this folder can.
- **transcribe.exe**: double-click to process the inbox now on this laptop. It needs pm_infra installed here.
- **install_pm_infra.cmd**: installs pm_infra on this laptop (no admin rights; needs an NVIDIA GPU) and registers this space.
- **project_settings.yaml**: settings for this space. `space_id` identifies it after a move; never edit that line.
- **_failed/**: recordings that could not be processed, with `error.log` saying why.
- **_to_delete/**: original videos and non-m4a audio, kept 14 days after transcription, then deleted.
- **.transcribing.lock**: hidden, managed by the app while a recording is being processed. Don't edit or delete it.

Transcripts land next to this folder in **Meetings/**, one folder per recording named `YYYY-MM-DD_HHMM_<name>`,
with `audio.m4a` (deleted after 14 days) and `transcript.md`.

Audio never leaves your drives. Project page: https://github.com/OWNER/pm_infra
