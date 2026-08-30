"""Highlight + topic-relevance detection.

Two backends:
- keyword (default, no API key, always works): merges transcript segments that
  mention any of the given topic keywords into candidate clip windows.
- groq (optional, used automatically if GROQ_API_KEY is set): asks a fast free-tier
  LLM to judge topic-relevance per segment (with a 0-10 relevance score), catching
  paraphrases keyword matching misses — verified against a real transcript where it
  correctly flagged a segment referencing the topic indirectly ("that describe-it-
  and-it-builds-it tool we mentioned earlier") with no literal keyword match.

Candidates are ranked best-first by `score` so a long podcast's many hits are
triaged instead of returned in transcript order.
"""
import os
import json
from dataclasses import dataclass


@dataclass
class Candidate:
    start: float
    end: float
    text: str
    reason: str
    score: float = 0.0


def _merge_segments(segments, hit_scores: dict, pad_before=2.0, pad_after=2.0):
    """Merge adjacent/nearby hit segments into clip windows with padding.
    hit_scores maps segment index -> relevance score (higher = more relevant).
    """
    if not hit_scores:
        return []
    hit_indices = sorted(hit_scores.keys())
    windows = []
    cur_start_idx = cur_end_idx = hit_indices[0]
    for idx in hit_indices[1:]:
        if segments[idx].start - segments[cur_end_idx].end <= 6.0:
            cur_end_idx = idx
        else:
            windows.append((cur_start_idx, cur_end_idx))
            cur_start_idx = cur_end_idx = idx
    windows.append((cur_start_idx, cur_end_idx))

    candidates = []
    for s_idx, e_idx in windows:
        start = max(0.0, segments[s_idx].start - pad_before)
        end = segments[e_idx].end + pad_after
        text = " ".join(segments[i].text for i in range(s_idx, e_idx + 1))
        window_scores = [hit_scores[i] for i in range(s_idx, e_idx + 1) if i in hit_scores]
        avg_score = sum(window_scores) / len(window_scores) if window_scores else 0.0
        candidates.append(Candidate(start=start, end=end, text=text, reason="keyword match", score=avg_score))
    candidates.sort(key=lambda c: c.score, reverse=True)
    return candidates


def detect_keyword(segments, topics: list) -> list:
    topics_lower = [t.lower() for t in topics if t.strip()]
    if not topics_lower:
        return []
    # Score = number of distinct keyword hits in the segment (hit density proxy).
    hit_scores = {}
    for i, seg in enumerate(segments):
        text_lower = seg.text.lower()
        hits = sum(1 for t in topics_lower if t in text_lower)
        if hits > 0:
            hit_scores[i] = float(hits)
    return _merge_segments(segments, hit_scores)


def detect_groq(segments, topics: list) -> list:
    """Use Groq's free-tier fast LLM to score segments for topic relevance (0-10)."""
    import requests

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY not set")

    numbered = "\n".join(f"[{i}] {seg.text}" for i, seg in enumerate(segments))
    topic_str = ", ".join(topics) if topics else "anything funny, wise, or highlight-worthy"
    prompt = (
        f"Below is a numbered transcript of a podcast. For each segment that discusses "
        f"or relates to: {topic_str} (including indirect references/paraphrases, not just "
        f"literal mentions), give it a relevance score from 1-10. Return ONLY a JSON array "
        f'of objects like [{{"index": 3, "score": 8}}], nothing else. Omit segments with no '
        f"relevance.\n\nTranscript:\n{numbered}"
    )
    resp = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": "openai/gpt-oss-20b",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
        },
        timeout=60,
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    start = content.find("[")
    end = content.rfind("]")
    parsed = json.loads(content[start:end + 1])

    hit_scores = {}
    for item in parsed:
        idx = item.get("index")
        score = item.get("score", 5)
        if isinstance(idx, int) and 0 <= idx < len(segments):
            hit_scores[idx] = float(score)

    candidates = _merge_segments(segments, hit_scores)
    for c in candidates:
        c.reason = f"LLM: relevant to {topic_str}"
    return candidates


def detect_highlights(segments, topics: list) -> list:
    """Try Groq (fast, free-tier) first if configured; fall back to keyword matching."""
    if os.environ.get("GROQ_API_KEY"):
        try:
            return detect_groq(segments, topics)
        except Exception as e:
            print(f"[detector] Groq detection failed ({e}), falling back to keyword match")
    return detect_keyword(segments, topics)
