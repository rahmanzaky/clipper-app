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
import time
from dataclasses import dataclass

from retry import retry_with_backoff


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


def _keyword_hit_score(segment, topics_lower: list) -> float:
    """Score = total keyword occurrence count in the segment (hit density proxy) —
    counts repeats of each topic, not just whether it's present at all. Factored out
    of detect_keyword so incremental/streaming scoring (one new segment at a time,
    used by the web API to show highlight markers while transcription is still
    running) can reuse the exact same scoring rule instead of duplicating it.
    """
    text_lower = segment.text.lower()
    return float(sum(text_lower.count(t) for t in topics_lower))


def detect_keyword(segments, topics: list) -> list:
    topics_lower = [t.lower() for t in topics if t.strip()]
    if not topics_lower:
        return []
    hit_scores = {}
    for i, seg in enumerate(segments):
        hits = _keyword_hit_score(seg, topics_lower)
        if hits > 0:
            hit_scores[i] = hits
    return _merge_segments(segments, hit_scores)


BATCH_SIZE = 25  # segments per Groq call — a real 328-segment transcript (a ~16 min
# podcast) sent as one giant prompt was confirmed (real test) to fail outright with
# an empty/invalid response, then hit a 429 rate limit on retry. Batching keeps each
# prompt small enough to get a reliable response and spreads calls to avoid bursting
# the free-tier rate limit.


def _score_batch(segments, index_offset, topics, api_key):
    """Send one batch of segments to Groq, return {global_index: score}."""
    import requests

    numbered = "\n".join(f"[{i + index_offset}] {seg.text}" for i, seg in enumerate(segments))
    topic_str = ", ".join(topics) if topics else "anything funny, wise, or highlight-worthy"
    prompt = (
        f"Below is a numbered transcript excerpt from a podcast. For each segment that "
        f"discusses or relates to: {topic_str} (including indirect references/paraphrases, "
        f"not just literal mentions), give it a relevance score from 1-10. Return ONLY a "
        f'JSON array of objects like [{{"index": 3, "score": 8}}], nothing else. Omit '
        f"segments with no relevance.\n\nTranscript:\n{numbered}"
    )
    resp = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": "openai/gpt-oss-20b",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
            "max_tokens": 4000,  # real testing found responses truncating mid-JSON
                                 # on a 40-segment batch at the previous default
        },
        timeout=60,
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    start = content.find("[")
    end = content.rfind("]")
    if start == -1 or end == -1:
        raise ValueError(f"No JSON array found in Groq response: {content[:200]!r}")
    parsed = json.loads(content[start:end + 1])

    hit_scores = {}
    for item in parsed:
        idx = item.get("index")
        score = item.get("score", 5)
        if isinstance(idx, int) and 0 <= idx < index_offset + len(segments):
            hit_scores[idx] = float(score)
    return hit_scores


def detect_groq(segments, topics: list) -> list:
    """Use Groq's free-tier fast LLM to score segments for topic relevance (0-10).
    Splits long transcripts into batches (see BATCH_SIZE) — sending everything in one
    prompt doesn't scale to real podcast-length transcripts.
    """
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY not set")

    topic_str = ", ".join(topics) if topics else "anything funny, wise, or highlight-worthy"
    hit_scores = {}
    num_batches = (len(segments) + BATCH_SIZE - 1) // BATCH_SIZE
    for batch_num, i in enumerate(range(0, len(segments), BATCH_SIZE)):
        batch = segments[i:i + BATCH_SIZE]

        def on_retry(attempt, exc, i=i):
            print(f"[detector] Groq batch at segment {i} failed (attempt {attempt}/3): {exc}. Retrying...")

        try:
            # Longer backoff than the default (5s base, not 2s) — free-tier rate
            # limits (429) confirmed during real testing need more than a couple
            # seconds to clear; a short backoff just burns retries against a limit
            # that hasn't reset yet.
            batch_scores = retry_with_backoff(
                lambda i=i, batch=batch: _score_batch(batch, i, topics, api_key),
                attempts=3, base_delay=5.0, on_retry=on_retry,
            )
            hit_scores.update(batch_scores)
        except Exception as e:
            # One batch permanently failing shouldn't sink the whole transcript's
            # detection — skip it (that stretch just gets no LLM-scored candidates)
            # rather than falling all the way back to keyword-only for everything.
            print(f"[detector] Groq batch at segment {i} failed after retries ({e}), skipping this batch")

        # Pace requests between batches (not just on retry) — confirmed during real
        # testing that firing batches back-to-back trips Groq's free-tier rate limit
        # well before a long transcript's batches are done.
        if batch_num < num_batches - 1:
            time.sleep(3.0)

    if not hit_scores:
        raise RuntimeError("Groq scored zero segments across all batches")

    candidates = _merge_segments(segments, hit_scores)
    for c in candidates:
        c.reason = f"LLM: relevant to {topic_str}"
    return candidates


def detect_highlights(segments, topics: list) -> list:
    """Try Groq (fast, free-tier) first if configured, retrying transient failures
    before giving up — a single flaky network blip shouldn't permanently degrade a
    whole run to the weaker keyword-only path. Falls back to keyword matching only
    after retries are exhausted (or if no API key is set at all).
    """
    if os.environ.get("GROQ_API_KEY"):
        def on_retry(attempt, exc):
            print(f"[detector] Groq detection failed (attempt {attempt}/3): {exc}. Retrying...")

        try:
            return retry_with_backoff(
                lambda: detect_groq(segments, topics), attempts=3, on_retry=on_retry
            )
        except Exception as e:
            print(f"[detector] Groq detection failed after 3 attempts ({e}), falling back to keyword match")
    return detect_keyword(segments, topics)
