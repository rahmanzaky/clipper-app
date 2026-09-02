"""Bilingual (EN/ID) transcription with word-level timestamps via faster-whisper."""
import os
import threading
from dataclasses import dataclass
from faster_whisper import WhisperModel

_MODEL = None
_MODEL_LOCK = threading.Lock()
# "large-v3-turbo" per the plan for best bilingual EN/ID accuracy. Override via
# WHISPER_MODEL env var (e.g. "small") for a faster one-time download while testing.
DEFAULT_MODEL = os.environ.get("WHISPER_MODEL", "large-v3-turbo")


def _get_model() -> WhisperModel:
    global _MODEL
    if _MODEL is None:
        # api.py runs each job's pipeline in its own background thread, so two
        # jobs submitted close together could both reach this line while _MODEL is
        # still None — without the lock, both construct a full WhisperModel (real
        # cost: up to ~1.5GB for large-v3-turbo, doubled), and whichever finishes
        # last silently wins the module-level reference.
        with _MODEL_LOCK:
            if _MODEL is None:  # re-check: another thread may have built it first
                try:
                    # CPU int8 for Mac compatibility without CUDA.
                    _MODEL = WhisperModel(DEFAULT_MODEL, device="cpu", compute_type="int8")
                except Exception as e:
                    # huggingface_hub already retries transient failures internally: if it
                    # still failed, this is usually a genuinely broken/unstable connection —
                    # point at the documented workaround instead of a raw traceback.
                    raise RuntimeError(
                        f"Failed to load/download Whisper model '{DEFAULT_MODEL}': {e}\n"
                        f"If this looks like a download error (e.g. 'CAS Client Error'), try:\n"
                        f"  export HF_HUB_DISABLE_XET=1\n"
                        f"and re-run. See README.md for details."
                    ) from e
    return _MODEL


@dataclass
class Word:
    text: str
    start: float
    end: float


@dataclass
class Segment:
    text: str
    start: float
    end: float
    language: str
    words: list


def transcribe_stream(audio_path: str):
    """Yield Segment objects as faster-whisper produces them, instead of blocking
    until the entire file is transcribed. faster-whisper's model.transcribe() already
    returns a lazy generator internally — this just avoids eagerly draining it into a
    list, so a caller (the web API) can react to segments as they arrive and show
    incremental progress/highlights during a long transcription instead of only after
    it completes.
    """
    model = _get_model()
    # Held for this whole generator's lifetime (a `with` block inside a generator
    # stays acquired across `yield` and only releases once the generator is fully
    # consumed or closed) — serializes transcription across concurrently-submitted
    # jobs instead of risking two threads calling into the same ctranslate2 model
    # instance at once, which isn't confirmed safe. Only matters when two jobs are
    # transcribing at literally the same time; the (rare) second job just waits.
    with _MODEL_LOCK:
        segments, info = model.transcribe(
            audio_path,
            word_timestamps=True,
            vad_filter=True,
        )
        # Known limitation: faster-whisper detects language once for the whole file
        # (info.language), not per segment — it has no built-in per-segment language ID.
        # For genuinely code-switched audio (like the bilingual test clip), this whole-file
        # label is an approximation, not a per-segment ground truth.
        detected_language = info.language
        for seg in segments:
            words = [Word(w.word.strip(), w.start, w.end) for w in (seg.words or [])]
            yield Segment(
                text=seg.text.strip(),
                start=seg.start,
                end=seg.end,
                language=detected_language,
                words=words,
            )


def transcribe(audio_path: str) -> list:
    return list(transcribe_stream(audio_path))
