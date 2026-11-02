"""Transcription engine: ffmpeg -> pyannote (speaker turns) -> faster-whisper -> transcript.md.

Models are loaded for one run and released afterwards. Diarization runs first and is freed
before Whisper loads, so peak VRAM stays around 3 GB.
"""

from __future__ import annotations

import gc
import os
import shutil
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

from pm_infra import media, paths
from pm_infra.naming import meeting_folder_name, next_index, numbered, recording_start, to_local_iso
from pm_infra.paths import SpaceDirs
from pm_infra.settings import SpaceSettings

PRIMARY_MODEL = "large-v3-turbo"
FALLBACK_MODEL = "medium"
DIARIZATION_MODEL = "pyannote/speaker-diarization-3.1"
COMPUTE_TYPE_GPU = "int8_float16"
COMPUTE_TYPE_CPU = "int8"
MERGE_GAP_SECONDS = 1.0

Progress = Callable[[str], None]


@dataclass
class Segment:
    start: float
    end: float
    text: str
    speaker: str | None = None


@dataclass
class RunResult:
    source_name: str
    meeting_dir: Path
    transcript: Path
    audio: Path
    duration: float
    language: str
    model: str
    speakers: int | None
    time_source: str
    seconds: float


def prepare_runtime():
    """Environment for model loading; returns the torch module."""
    os.environ.setdefault("HF_HOME", str(paths.models_dir()))
    os.environ.setdefault("PYANNOTE_CACHE", str(paths.models_dir() / "pyannote"))  # not ~/.cache/torch/pyannote
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    settle_symlink_support(paths.models_dir())
    import torch  # noqa: WPS433  (heavy import on purpose, only when a run starts)

    lib = Path(torch.__file__).parent / "lib"
    if lib.is_dir() and hasattr(os, "add_dll_directory"):
        os.add_dll_directory(str(lib))  # ctranslate2 finds cuDNN/cuBLAS that torch ships
    allow_pyannote_checkpoints(torch)
    return torch


def allow_pyannote_checkpoints(torch) -> None:
    """Let torch>=2.6 load pyannote 3.x checkpoints without turning the weights-only check off.

    torch.load now refuses pickled objects it does not know. The speaker model's checkpoints carry
    exactly these four classes (the torch version they were saved with and pyannote's task
    description), so they are allowlisted by name; everything else stays blocked.
    """
    try:
        from pyannote.audio.core.task import Problem, Resolution, Specifications
    except ImportError:  # pyannote not installed: no speaker labels, nothing to allow
        return
    torch.serialization.add_safe_globals([torch.torch_version.TorchVersion, Specifications, Problem, Resolution])


def symlinks_work(folder: Path) -> bool:
    """True if this user may create symlinks in folder (needs Developer Mode or admin on Windows)."""
    folder.mkdir(parents=True, exist_ok=True)
    probe = folder / f".symlink_probe_{os.getpid()}"
    try:
        probe.symlink_to("nothing")
        return True
    except OSError:
        return False
    finally:
        try:
            probe.unlink()
        except OSError:
            pass


def settle_symlink_support(models_dir: Path) -> bool:
    """Tell huggingface_hub up front whether symlinks work in the models folder.

    Its own check marks a folder as "supported" before testing it, so parallel download
    threads can read the flag too early and crash with WinError 1314 on a plain Windows
    user account. Deciding once here makes every download fall back to copies instead.
    """
    ok = symlinks_work(models_dir)
    if not ok:
        from huggingface_hub import file_download

        file_download.are_symlinks_supported = lambda cache_dir=None: False
    return ok


def _free(torch) -> None:
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


def process_file(
    src: Path,
    space_root: Path,
    settings: SpaceSettings,
    progress: Progress = print,
    token: str | None = None,
    with_speakers: bool = True,
) -> RunResult:
    t0 = time.time()
    src = Path(src)
    dirs = SpaceDirs(space_root)
    dirs.ensure()

    info = media.probe(src)
    start, time_source = recording_start(src, info.creation_time)
    end = start + timedelta(seconds=info.duration)
    folder = dirs.meetings / meeting_folder_name(start, src.stem)
    folder.mkdir(parents=True, exist_ok=True)
    n = next_index(folder)
    transcript = numbered(folder, "transcript", ".md", n)
    audio = numbered(folder, "audio", ".m4a", n)

    tmp = paths.tmp_dir()
    tmp.mkdir(parents=True, exist_ok=True)
    wav = tmp / f"{uuid.uuid4().hex}.wav"
    try:
        progress(f"Decoding audio ({info.duration / 60:.1f} min)...")
        media.to_wav16k(src, wav)

        torch = prepare_runtime()
        turns: list[tuple[float, float, str]] | None = None
        if with_speakers and token:
            progress("Finding speakers...")
            try:
                turns = diarize(wav, token, torch)
            except Exception as e:  # diarization is optional; the transcript still gets written
                progress(f"Speaker labels skipped: {str(e).splitlines()[0][:200]}")
                turns = None
            _free(torch)
        elif with_speakers:
            progress("No Hugging Face token: transcript without speaker labels.")

        progress("Transcribing...")
        segments, language, model_name = transcribe(wav, settings.language_or_none, progress, info.duration, torch)
        _free(torch)

        lines = assign_speakers(segments, turns)
        speakers = len({s.speaker for s in lines if s.speaker}) if turns is not None else None
        text = render_transcript(src.name, start, end, language, model_name, speakers, time_source, lines)
        transcript.write_text(text, encoding="utf-8")

        if media.is_plain_m4a(src, info):
            shutil.move(str(src), str(audio))
        else:
            progress("Saving audio.m4a...")
            media.to_m4a(src, audio)
            park_original(src, dirs)
    except BaseException:
        discard_partial(folder, [transcript] + ([audio] if src.exists() else []))
        raise
    finally:
        try:
            wav.unlink(missing_ok=True)
        except OSError:
            pass

    return RunResult(
        source_name=src.name, meeting_dir=folder, transcript=transcript, audio=audio,
        duration=info.duration, language=language, model=model_name, speakers=speakers,
        time_source=time_source, seconds=time.time() - t0,
    )


def discard_partial(folder: Path, files: list[Path]) -> None:
    """A failed run leaves nothing in Meetings/: drop what it wrote, and the folder if that empties it.

    The source file goes to _failed/ and may be retried later; a leftover folder would look like
    an unmatched meeting and a retry would produce transcript_2.md next to a half-finished one.
    """
    for f in files:
        try:
            Path(f).unlink(missing_ok=True)
        except OSError:
            pass
    try:
        if folder.is_dir() and not any(folder.iterdir()):
            folder.rmdir()
    except OSError:
        pass


def park_original(src: Path, dirs: SpaceDirs) -> Path:
    """Move a non-m4a original (video, mp3, wav...) to _to_delete/ and stamp it with now."""
    dirs.to_delete.mkdir(parents=True, exist_ok=True)
    dest = dirs.to_delete / src.name
    k = 2
    while dest.exists():
        dest = dirs.to_delete / f"{src.stem}_{k}{src.suffix}"
        k += 1
    shutil.move(str(src), str(dest))
    os.utime(dest, None)
    return dest


def transcribe(wav: Path, language: str | None, progress: Progress, duration: float, torch):
    from faster_whisper import WhisperModel

    use_gpu = torch.cuda.is_available()
    device = "cuda" if use_gpu else "cpu"
    compute = COMPUTE_TYPE_GPU if use_gpu else COMPUTE_TYPE_CPU
    if not use_gpu:
        progress("No CUDA GPU found: transcribing on the CPU, this will be slow.")

    # Hand faster-whisper samples instead of a path: its own decoder goes through PyAV,
    # whose API changes between releases (av 19 broke it). The wav is already 16 kHz mono.
    audio = read_wav16k(wav)

    for model_name in (PRIMARY_MODEL, FALLBACK_MODEL):
        model = None
        try:
            model = _load_whisper(WhisperModel, model_name, device, compute)
            segs, info = model.transcribe(
                audio, language=language, vad_filter=True, beam_size=5, condition_on_previous_text=False,
            )
            out: list[Segment] = []
            report_every = max(120.0, duration / 8) if duration else 120.0
            next_report = report_every
            for s in segs:
                text = s.text.strip()
                if text:
                    out.append(Segment(float(s.start), float(s.end), text))
                if duration and s.end >= next_report:
                    progress(f"  {min(100, s.end / duration * 100):.0f}%")
                    next_report += report_every
            return out, info.language, model_name
        except RuntimeError as e:
            if "out of memory" in str(e).lower() and model_name != FALLBACK_MODEL:
                progress(f"GPU out of memory with {model_name}; retrying with {FALLBACK_MODEL}.")
                del model
                _free(torch)
                continue
            raise
        finally:
            del model
            _free(torch)
    raise RuntimeError("transcription failed")


def read_wav16k(wav: Path):
    """Mono float32 samples of a 16 kHz wav, the form faster-whisper accepts directly."""
    import soundfile as sf

    data, sr = sf.read(str(wav), dtype="float32", always_2d=True)
    if sr != 16000:
        raise ValueError(f"expected a 16 kHz wav, got {sr} Hz: {wav.name}")
    return data.mean(axis=1) if data.shape[1] > 1 else data[:, 0]


def _load_whisper(WhisperModel, name: str, device: str, compute: str):
    root = str(paths.models_dir())
    try:
        return WhisperModel(name, device=device, compute_type=compute, download_root=root, local_files_only=True)
    except Exception:
        return WhisperModel(name, device=device, compute_type=compute, download_root=root)


def diarize(wav: Path, token: str, torch) -> list[tuple[float, float, str]]:
    import numpy as np  # noqa: F401  (soundfile needs it)
    import soundfile as sf
    from pyannote.audio import Pipeline

    pipe = Pipeline.from_pretrained(DIARIZATION_MODEL, use_auth_token=token)
    if pipe is None:
        raise RuntimeError(
            f"{DIARIZATION_MODEL} could not be loaded. Accept its terms (and those of pyannote/segmentation-3.0) "
            "on Hugging Face and check the token."
        )
    if torch.cuda.is_available():
        pipe.to(torch.device("cuda"))
    data, sr = sf.read(str(wav), dtype="float32", always_2d=True)
    waveform = torch.from_numpy(data.T.copy())
    result = pipe({"waveform": waveform, "sample_rate": sr})
    annotation = getattr(result, "speaker_diarization", result)
    turns = [(float(t.start), float(t.end), str(spk)) for t, _, spk in annotation.itertracks(yield_label=True)]
    del pipe, result, annotation, waveform
    return sorted(turns)


def assign_speakers(segments: list[Segment], turns: list[tuple[float, float, str]] | None) -> list[Segment]:
    if not turns:
        return segments
    out: list[Segment] = []
    for seg in segments:
        best, best_overlap = None, 0.0
        nearest, nearest_d = None, float("inf")
        mid = (seg.start + seg.end) / 2
        for s, e, spk in turns:
            overlap = min(e, seg.end) - max(s, seg.start)
            if overlap > best_overlap:
                best, best_overlap = spk, overlap
            d = 0.0 if s <= mid <= e else min(abs(s - mid), abs(e - mid))
            if d < nearest_d:
                nearest, nearest_d = spk, d
        out.append(Segment(seg.start, seg.end, seg.text, best or nearest))
    # rename by first appearance, then merge adjacent lines of one speaker
    names: dict[str, str] = {}
    for seg in out:
        if seg.speaker and seg.speaker not in names:
            names[seg.speaker] = f"SPEAKER_{len(names) + 1}"
        seg.speaker = names.get(seg.speaker) if seg.speaker else None
    merged: list[Segment] = []
    for seg in out:
        if merged and merged[-1].speaker == seg.speaker and seg.start - merged[-1].end <= MERGE_GAP_SECONDS:
            merged[-1].end = seg.end
            merged[-1].text = f"{merged[-1].text} {seg.text}"
        else:
            merged.append(Segment(seg.start, seg.end, seg.text, seg.speaker))
    return merged


def hms(seconds: float) -> str:
    seconds = int(seconds)
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def render_transcript(
    source_name: str, start: datetime, end: datetime, language: str, model: str,
    speakers: int | None, time_source: str, lines: list[Segment],
) -> str:
    head = [
        "---",
        f"source_file: {source_name}",
        f"recorded_start: {to_local_iso(start)}",
        f"recorded_end: {to_local_iso(end)}",
        f"language: {language}",
        f"model: {model}",
        f"speakers: {speakers if speakers is not None else 'none'}",
        f"time_source: {time_source}",
        "---",
        "",
    ]
    body = [
        f"[{hms(s.start)}] {s.speaker + ': ' if s.speaker else ''}{s.text}" for s in lines
    ]
    return "\n".join(head + body) + "\n"


def _retry(action, progress: Progress, attempts: int = 4, pause: float = 5.0):
    """Run action again on network errors; downloads resume where they stopped."""
    for n in range(1, attempts + 1):
        try:
            return action()
        except Exception as exc:  # noqa: BLE001  (requests/urllib3 raise many types)
            if n == attempts:
                raise
            progress(f"  download interrupted ({type(exc).__name__}), retrying in {pause:.0f} s ({n}/{attempts - 1})")
            time.sleep(pause)


def install_models(progress: Progress = print, token: str | None = None) -> None:
    torch = prepare_runtime()
    from faster_whisper.utils import download_model

    for name in (PRIMARY_MODEL, FALLBACK_MODEL):
        progress(f"Whisper model {name}...")
        _retry(lambda: download_model(name, cache_dir=str(paths.models_dir())), progress)
    if token:
        progress(f"Speaker model {DIARIZATION_MODEL}...")
        from pyannote.audio import Pipeline

        pipe = Pipeline.from_pretrained(DIARIZATION_MODEL, use_auth_token=token)
        if pipe is None:
            progress(
                "  Could not load it: accept the terms of pyannote/speaker-diarization-3.1 and "
                "pyannote/segmentation-3.0 on huggingface.co, then run install-models again."
            )
        del pipe
    else:
        progress("No Hugging Face token: speaker model skipped (transcripts will have no speaker labels).")
    progress(f"CUDA available: {torch.cuda.is_available()}")
