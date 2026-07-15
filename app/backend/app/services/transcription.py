"""
Server-side transcription for the in-app Issue Recorder.

Chrome's live Web Speech transcript is unreliable while MediaRecorder holds the
mic — on the Titan recorder it returns empty (n_speech=0) on essentially every
report. So the recorded ``.webm`` audio is the real source of truth, and this
service transcribes it with faster-whisper.

Why faster-whisper: CPU-only (ctranslate2 — no torch), and it decodes the webm
with bundled PyAV/ffmpeg libraries, so it needs NO system ffmpeg (the box has
none). The model is a lazily-loaded singleton, and every transcription is
serialized behind a lock so we never storm the shared box's CPU or call the
(non-thread-safe) model concurrently.

Everything here is best-effort and never raises: if the package is missing,
transcription is disabled, or decoding fails, we simply return ``None`` and the
report stands on its video + clicks. A mic problem must never lose a report.
"""
from __future__ import annotations

import logging
import math
import threading
from pathlib import Path

from app.config import get_settings

logger = logging.getLogger(__name__)
_settings = get_settings()

_model = None
_model_lock = threading.Lock()   # guards the lazy load
_run_lock = threading.Lock()     # serializes transcription (CPU + thread-safety)


def is_enabled() -> bool:
    return bool(getattr(_settings, "transcription_enabled", True))


def _get_model():
    """Lazily load the faster-whisper model once. Import is deferred so the
    backend still boots if the package isn't installed yet."""
    global _model
    if _model is not None:
        return _model
    with _model_lock:
        if _model is None:
            from faster_whisper import WhisperModel  # deferred import
            size = getattr(_settings, "transcription_model", "base.en")
            compute = getattr(_settings, "transcription_compute_type", "int8")
            cache = getattr(_settings, "transcription_cache_dir", "") or None
            logger.info("Loading faster-whisper model=%s compute=%s", size, compute)
            _model = WhisperModel(
                size, device="cpu", compute_type=compute, download_root=cache
            )
    return _model


def _confidence(avg_logprob: float | None) -> float:
    """Map whisper's avg_logprob (~ -1..0) to a rough 0..1 confidence."""
    if avg_logprob is None:
        return 0.0
    return round(max(0.0, min(1.0, math.exp(avg_logprob))), 3)


def _collect(seg_iter):
    """Consume the lazy segment generator into our speech_segments shape."""
    segments, texts = [], []
    for s in seg_iter:
        t = (s.text or "").strip()
        if not t:
            continue
        segments.append({
            "text": t,
            "timestamp_ms": int((s.start or 0) * 1000),
            "confidence": _confidence(getattr(s, "avg_logprob", None)),
        })
        texts.append(t)
    return segments, " ".join(texts).strip()


def transcribe(path: str | Path) -> dict | None:
    """Transcribe an audio/video file. Returns
    ``{text, segments:[{text,timestamp_ms,confidence}], language, duration, model}``
    or ``None`` on failure / silence / when disabled. Never raises.

    CPU-bound — call from a worker thread (``asyncio.to_thread``) so the event
    loop stays responsive; faster-whisper releases the GIL during inference.
    """
    if not is_enabled():
        return None
    p = Path(path)
    if not p.exists() or p.stat().st_size == 0:
        return None
    try:
        model = _get_model()
        with _run_lock:
            try:
                seg_iter, info = model.transcribe(
                    str(p), language="en", vad_filter=True, beam_size=1,
                    condition_on_previous_text=False,
                )
                segments, full = _collect(seg_iter)
            except Exception:
                # VAD needs onnxruntime; if that's unavailable, transcribe raw.
                logger.warning("vad transcribe failed for %s; retrying without vad", p)
                seg_iter, info = model.transcribe(
                    str(p), language="en", vad_filter=False, beam_size=1,
                    condition_on_previous_text=False,
                )
                segments, full = _collect(seg_iter)
        return {
            "text": full,
            "segments": segments,
            "language": getattr(info, "language", "en"),
            "duration": round(getattr(info, "duration", 0.0) or 0.0, 2),
            "model": getattr(_settings, "transcription_model", "base.en"),
        }
    except Exception:
        logger.exception("transcription failed for %s", p)
        return None
