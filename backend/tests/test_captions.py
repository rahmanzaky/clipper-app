"""Pure-logic tests for captions.py — ASS timestamp math, no ffmpeg call."""
import sys
import os
from dataclasses import dataclass

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from captions import _ass_timestamp, build_ass_karaoke


def test_ass_timestamp_zero():
    assert _ass_timestamp(0.0) == "0:00:00.00"


def test_ass_timestamp_sub_minute():
    assert _ass_timestamp(5.25) == "0:00:05.25"


def test_ass_timestamp_minutes():
    assert _ass_timestamp(65.5) == "0:01:05.50"


def test_ass_timestamp_hours():
    assert _ass_timestamp(3661.1) == "1:01:01.10"


def test_ass_timestamp_negative_clamped_to_zero():
    assert _ass_timestamp(-5.0) == "0:00:00.00"


@dataclass
class Word:
    text: str
    start: float
    end: float


def test_build_ass_karaoke_produces_header_and_dialogue():
    words = [Word("hello", 1.0, 1.3), Word("world", 1.4, 1.8)]
    ass = build_ass_karaoke(words, clip_start=0.0, chunk_size=5)
    assert "[Script Info]" in ass
    assert "[V4+ Styles]" in ass
    assert "Dialogue:" in ass
    assert "\\kf" in ass
    assert "hello" in ass
    assert "world" in ass


def test_build_ass_karaoke_empty_words_produces_no_dialogue():
    ass = build_ass_karaoke([], clip_start=0.0)
    assert "Dialogue:" not in ass


def test_build_ass_karaoke_chunks_split_into_multiple_lines():
    words = [Word(f"w{i}", i * 0.5, i * 0.5 + 0.3) for i in range(12)]
    ass = build_ass_karaoke(words, clip_start=0.0, chunk_size=5)
    dialogue_lines = [l for l in ass.splitlines() if l.startswith("Dialogue:")]
    assert len(dialogue_lines) == 3  # 12 words / chunk_size 5 -> 3 lines (5,5,2)


def test_build_ass_karaoke_timestamps_relative_to_clip_start():
    words = [Word("hello", 10.0, 10.5)]
    ass = build_ass_karaoke(words, clip_start=10.0, chunk_size=5)
    # Word starts exactly at clip_start -> relative time should be 0:00:00.00
    assert "0:00:00.00" in ass
