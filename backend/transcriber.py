"""Bilingual (EN/ID) transcription with word-level timestamps via faster-whisper."""
import os
from dataclasses import dataclass
from faster_whisper import WhisperModel

_MODEL = None
# "large-v3-turbo" per the plan for best bilingual EN/ID accuracy. Override via
# WHISPER_MODEL env var (e.g. "small") for a faster one-time download while testing.
DEFAULT_MODEL = os.environ.get("WHISPER_MODEL", "large-v3-turbo")


def _get_model() -> WhisperModel:
    global _MODEL
    if _MODEL is None:
        # CPU int8 for Mac compatibility without CUDA.
        _MODEL = WhisperModel(DEFAULT_MODEL, device="cpu", compute_type="int8")
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


def transcribe(audio_path: str) -> list:
    model = _get_model()
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
    result = []
    for seg in segments:
        words = [Word(w.word.strip(), w.start, w.end) for w in (seg.words or [])]
        result.append(
            Segment(
                text=seg.text.strip(),
                start=seg.start,
                end=seg.end,
                language=detected_language,
                words=words,
            )
        )
    return result
