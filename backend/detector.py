"""Highlight + topic-relevance detection.

Two backends:
- keyword (default, no API key, always works): merges transcript segments that
  mention any of the given topic keywords into candidate clip windows.
- groq (optional, used automatically if GROQ_API_KEY is set): asks a fast free-tier
  LLM to judge topic-relevance and highlight-worthiness per segment, for better
  recall than plain keyword matching.
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


def _merge_segments(segments, hit_indices, pad_before=2.0, pad_after=2.0):
    """Merge adjacent/nearby hit segments into clip windows with padding."""
    if not hit_indices:
        return []
    hit_indices = sorted(hit_indices)
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
        candidates.append(Candidate(start=start, end=end, text=text, reason="keyword match"))
    return candidates


def detect_keyword(segments, topics: list) -> list:
    topics_lower = [t.lower() for t in topics if t.strip()]
    if not topics_lower:
        return []
    hits = [
        i for i, seg in enumerate(segments)
        if any(t in seg.text.lower() for t in topics_lower)
    ]
    return _merge_segments(segments, hits)


def detect_groq(segments, topics: list) -> list:
    """Use Groq's free-tier fast LLM to score segments for topic relevance."""
    import requests

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY not set")

    numbered = "\n".join(f"[{i}] {seg.text}" for i, seg in enumerate(segments))
    topic_str = ", ".join(topics) if topics else "anything funny, wise, or highlight-worthy"
    prompt = (
        f"Below is a numbered transcript of a podcast. Identify which segment numbers "
        f"discuss or relate to: {topic_str}. Return ONLY a JSON array of segment index "
        f"integers, nothing else.\n\nTranscript:\n{numbered}"
    )
    resp = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": "llama-3.1-8b-instant",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
        },
        timeout=60,
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    start = content.find("[")
    end = content.rfind("]")
    indices = json.loads(content[start:end + 1])
    valid = [i for i in indices if isinstance(i, int) and 0 <= i < len(segments)]
    candidates = _merge_segments(segments, valid)
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
