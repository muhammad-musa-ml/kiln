"""Hear a saved video, because Claude cannot.

A free video model gets a reel's speech as part of reading it. When every
one of them is out of quota the reel still has to be read, and the Claude
fallback only ever sees frames, so a post whose whole point is spoken came
out with nothing: the reel listing the companies that hire without an
interview names all four of them out loud and writes none of them down.

This transcribes the audio track that acquire.py already saves beside the
video. Local, so it costs no quota and needs no network, which matters
because the only time it is wanted is when the quotas are gone.

The transcript is cached next to the audio, so a reel is heard once however
many passes read it.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import threading
from pathlib import Path

# Anything longer than this is not a reel, and an hour of audio would hold
# a pass up for the better part of an hour.
MAX_SECONDS = float(os.environ.get("KILN_LISTEN_MAX_SECONDS", "900"))
# Held down so a transcription does not starve the rest of the pass.
THREADS = int(os.environ.get("KILN_LISTEN_THREADS", "8"))
OFF = os.environ.get("KILN_LISTEN", "1") == "0"

_lock = threading.Lock()
_model = None
_model_why = ""


def _model_dir() -> str:
    """The cached faster-whisper model, or "" if there is not one.

    Keyed on the directory holding model.bin rather than on a revision
    hash, which would rot the first time the cache was refreshed.
    """
    override = os.environ.get("KILN_WHISPER_DIR")
    if override:
        return override if (Path(override) / "model.bin").is_file() else ""
    hub = Path(os.path.expanduser("~/.cache/huggingface/hub"))
    if not hub.is_dir():
        return ""
    # Largest first: large-v3 says more than tiny, and both are already paid
    # for on disk.
    best = ""
    best_size = -1
    for repo in sorted(hub.glob("models--*faster-whisper*")):
        for snap in sorted(repo.glob("snapshots/*")):
            bin_ = snap / "model.bin"
            if not bin_.is_file():
                continue
            size = bin_.stat().st_size
            if size > best_size:
                best, best_size = str(snap), size
    return best


def _get_model():
    """Load once a process. Loading costs about eight seconds."""
    global _model, _model_why
    with _lock:
        if _model is not None or _model_why:
            return _model
        d = _model_dir()
        if not d:
            _model_why = "no faster-whisper model is cached"
            return None
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            _model_why = "faster-whisper is not installed"
            return None
        try:
            _model = WhisperModel(d, device="cpu", compute_type="int8",
                                  cpu_threads=THREADS)
        except Exception as e:  # noqa: BLE001 - a bad cache must not stop a pass
            _model_why = "%s: %s" % (type(e).__name__, e)
            return None
        return _model


def _has_audio(path: Path) -> bool:
    fp = shutil.which("ffprobe")
    if not fp:
        return True  # let whisper decide rather than refusing on a missing probe
    try:
        p = subprocess.run(
            [fp, "-v", "error", "-select_streams", "a", "-show_entries",
             "stream=codec_type", "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, timeout=60)
        return "audio" in (p.stdout or "")
    except (OSError, subprocess.SubprocessError):
        return True


def _seconds(path: Path) -> float:
    fp = shutil.which("ffprobe")
    if not fp:
        return 0.0
    try:
        p = subprocess.run(
            [fp, "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, timeout=60)
        return float((p.stdout or "").strip() or 0)
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0.0


def _pick(media_dir: Path) -> Path | None:
    """The audio track if it was saved on its own, else the merged file.

    The picture-only file is last: it often has no sound at all, and
    reading a 20 MB file to find that out is wasteful.
    """
    files = [p for p in sorted(media_dir.iterdir()) if p.is_file()]
    for suffix in ("_audio", "_av", "_video"):
        for p in files:
            if p.stem.endswith(suffix) and p.suffix.lower() in (
                    ".mp4", ".m4a", ".mov", ".webm", ".mkv", ".aac", ".mp3"):
                return p
    return None


def _cache_path(media_dir: Path) -> Path:
    return media_dir / "transcript.txt"


def transcribe(media_dir: str | Path) -> tuple[str, str]:
    """Return (transcript, why_not). Exactly one of the two is set.

    Never raises: a pass that cannot hear a reel still has to read it.
    """
    if OFF:
        return "", "listening is off (KILN_LISTEN=0)"
    # Path("") is Path("."), which is a directory and would have this
    # listing the repo root looking for a sound track.
    if not media_dir:
        return "", "no media was saved for this item"
    d = Path(media_dir)
    if not d.is_dir():
        return "", "no media was saved for this item"

    cache = _cache_path(d)
    if cache.is_file():
        try:
            got = cache.read_text(encoding="utf-8").strip()
        except OSError:
            got = ""
        if got:
            return got, ""
        return "", "heard before and there was no speech"

    src = _pick(d)
    if src is None:
        return "", "nothing with a sound track was saved"
    if not _has_audio(src):
        return "", "the saved video has no sound track"
    secs = _seconds(src)
    if secs > MAX_SECONDS:
        return "", "%.0f minutes is too long to transcribe" % (secs / 60)

    model = _get_model()
    if model is None:
        return "", _model_why or "no local transcriber"

    try:
        segments, _info = model.transcribe(str(src), beam_size=1,
                                           vad_filter=True)
        text = " ".join(s.text.strip() for s in segments).strip()
    except Exception as e:  # noqa: BLE001 - never take the pass down
        return "", "%s: %s" % (type(e).__name__, e)

    # Written even when empty, so a silent reel is not transcribed again on
    # every pass that reads it.
    try:
        cache.write_text(text, encoding="utf-8")
    except OSError:
        pass
    if not text:
        return "", "there was no speech to hear"
    return text, ""


def for_item(it: dict) -> tuple[str, str]:
    """(transcript, why_not) for a stored item, by its saved media."""
    return transcribe(it.get("media_dir") or "")
