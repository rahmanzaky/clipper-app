"""Pure-logic tests for detector.py — no network, no models."""
import sys
import os
from dataclasses import dataclass, field
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from detector import detect_keyword, detect_groq, _merge_segments


@dataclass
class Segment:
    text: str
    start: float
    end: float
    language: str = "en"
    words: list = field(default_factory=list)


def make_segments():
    return [
        Segment("Welcome back to the show today", 0.0, 3.0),
        Segment("so tell me about your morning routine", 3.0, 6.0),
        Segment("I actually use Lovable every single day to build prototypes", 6.0, 10.0),
        Segment("it has completely changed how I ship products", 10.0, 13.0),
        Segment("anyway let us talk about something else entirely", 13.0, 16.0),
        Segment("random unrelated topic about coffee", 16.0, 19.0),
        Segment("back to Lovable for a second, Anton built something amazing", 19.0, 23.0),
        Segment("thanks for watching, see you next time", 23.0, 26.0),
    ]


def test_keyword_merges_adjacent_hits():
    """Two keyword hits within the merge window (<=6s gap) become one candidate."""
    segments = [
        Segment("talking about Lovable here", 0.0, 3.0),
        Segment("still on the same topic", 3.0, 6.0),
        Segment("more Lovable talk", 6.0, 9.0),
    ]
    candidates = detect_keyword(segments, ["Lovable"])
    assert len(candidates) == 1
    assert candidates[0].start == max(0.0, 0.0 - 2.0)  # padded start, clamped at 0
    assert candidates[0].end == 9.0 + 2.0  # padded end


def test_keyword_does_not_merge_distant_hits():
    """Two keyword hits far apart (per the real Phase 1 test) stay as separate candidates."""
    candidates = detect_keyword(make_segments(), ["Lovable", "Anton"])
    assert len(candidates) == 2
    starts = sorted(c.start for c in candidates)
    # Window 1: segment 2 (6.0-10.0) padded -> starts at 4.0
    # Window 2: segment 6 (19.0-23.0) padded -> starts at 17.0
    assert starts == [4.0, 17.0]


def test_keyword_no_topics_returns_empty():
    assert detect_keyword(make_segments(), []) == []
    assert detect_keyword(make_segments(), [""]) == []


def test_keyword_no_match_returns_empty():
    assert detect_keyword(make_segments(), ["nonexistent_keyword_xyz"]) == []


def test_keyword_scores_by_hit_density():
    """A segment mentioning the topic twice scores higher than one mentioning it once."""
    segments = [
        Segment("Lovable Lovable Lovable everywhere", 0.0, 3.0),
        Segment("completely unrelated", 30.0, 33.0),
        Segment("just one mention of Lovable here", 60.0, 63.0),
    ]
    candidates = detect_keyword(segments, ["Lovable"])
    assert len(candidates) == 2
    # Ranked best-first: the triple-mention segment should score higher and come first.
    assert candidates[0].score > candidates[1].score


def test_candidates_ranked_best_first():
    """_merge_segments sorts by score descending regardless of input order."""
    segments = [Segment(f"seg{i}", i * 10.0, i * 10.0 + 3.0) for i in range(5)]
    hit_scores = {0: 2.0, 1: 9.0, 2: 5.0}
    candidates = _merge_segments(segments, hit_scores)
    scores = [c.score for c in candidates]
    assert scores == sorted(scores, reverse=True)


def test_groq_parses_scored_response_and_ranks():
    """detect_groq parses the LLM's [{"index":.., "score":..}] response and ranks results."""
    segments = make_segments()
    fake_response = MagicMock()
    fake_response.raise_for_status = MagicMock()
    fake_response.json.return_value = {
        "choices": [{"message": {"content": '[{"index": 2, "score": 9}, {"index": 6, "score": 7}]'}}]
    }
    with patch.dict(os.environ, {"GROQ_API_KEY": "fake-key-for-test"}):
        with patch("requests.post", return_value=fake_response):
            candidates = detect_groq(segments, ["Lovable", "Anton"])
    assert len(candidates) == 2
    # Higher-scored segment (index 2, score 9) should rank first.
    assert candidates[0].score == 9.0
    assert candidates[1].score == 7.0
    assert all("LLM" in c.reason for c in candidates)


def test_groq_uses_per_segment_why_when_given():
    """Each candidate should carry Groq's own specific reason for its best segment,
    not the same generic templated string for every candidate in the job — the
    real gap this was built to fix: two completely different clips both showing
    the identical "LLM: relevant to <topics>" text with zero specificity.
    """
    segments = make_segments()
    fake_response = MagicMock()
    fake_response.raise_for_status = MagicMock()
    fake_response.json.return_value = {
        "choices": [{"message": {"content": (
            '[{"index": 2, "score": 9, "why": "names the product directly"}, '
            '{"index": 6, "score": 7, "why": "compares it to a competitor"}]'
        )}}]
    }
    with patch.dict(os.environ, {"GROQ_API_KEY": "fake-key-for-test"}):
        with patch("requests.post", return_value=fake_response):
            candidates = detect_groq(segments, ["Lovable", "Anton"])
    assert len(candidates) == 2
    reasons = {c.reason for c in candidates}
    assert "names the product directly" in reasons
    assert "compares it to a competitor" in reasons
    # The two candidates must NOT share one identical generic reason.
    assert len(reasons) == 2


def test_groq_raises_without_api_key():
    with patch.dict(os.environ, {}, clear=True):
        try:
            detect_groq(make_segments(), ["Lovable"])
            assert False, "expected RuntimeError"
        except RuntimeError:
            pass
