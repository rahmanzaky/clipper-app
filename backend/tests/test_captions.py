"""Pure-logic tests for captions.py — ASS timestamp math and plain caption building,
no ffmpeg call.
"""
import sys
import os
from dataclasses import dataclass

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from captions import _ass_timestamp, build_ass_plain, get_caption_lines


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


def test_get_caption_lines_groups_words_into_chunks():
    words = [Word(f"w{i}", i * 0.5, i * 0.5 + 0.3) for i in range(12)]
    lines = get_caption_lines(words, clip_start=0.0, chunk_size=5)
    assert len(lines) == 3  # 12 words / chunk_size 5 -> 3 lines (5, 5, 2)
    assert lines[0]["text"] == "w0 w1 w2 w3 w4"


def test_get_caption_lines_timestamps_relative_to_clip_start():
    words = [Word("hello", 10.0, 10.5)]
    lines = get_caption_lines(words, clip_start=10.0)
    assert lines[0]["start"] == 0.0


def test_get_caption_lines_empty_words_produces_no_lines():
    assert get_caption_lines([], clip_start=0.0) == []


def test_build_ass_plain_produces_header_and_dialogue():
    lines = [{"text": "hello world", "start": 1.0, "end": 1.8}]
    ass = build_ass_plain(lines)
    assert "[Script Info]" in ass
    assert "[V4+ Styles]" in ass
    assert "Dialogue:" in ass
    assert "hello world" in ass


def test_build_ass_plain_has_no_karaoke_tags():
    lines = [{"text": "hello world", "start": 1.0, "end": 1.8}]
    ass = build_ass_plain(lines)
    assert "\\kf" not in ass


def test_build_ass_plain_empty_lines_produces_no_dialogue():
    ass = build_ass_plain([])
    assert "Dialogue:" not in ass


def test_build_ass_plain_multiple_lines():
    lines = [
        {"text": "first line", "start": 0.0, "end": 1.0},
        {"text": "second line", "start": 1.0, "end": 2.0},
    ]
    ass = build_ass_plain(lines)
    dialogue_lines = [l for l in ass.splitlines() if l.startswith("Dialogue:")]
    assert len(dialogue_lines) == 2
