"""Word-level karaoke-style burned captions (ASS format via libass).

Each caption line covers a short chunk of words. Within a line, every word carries
an ASS `\\kf` (karaoke fill) tag whose duration is that word's own timing — libass
sweeps the highlight color across each word as it's spoken, the CapCut-style look
real competitors use, instead of the whole chunk lighting up at once.
"""

_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Karaoke,Arial,64,&H00FFFFFF,&H0000FFFF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,3,3,0,2,60,60,120,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _ass_timestamp(seconds: float) -> str:
    if seconds < 0:
        seconds = 0
    cs = int(round(seconds * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"


def build_ass_karaoke(words, clip_start: float, chunk_size: int = 5) -> str:
    """Build an ASS subtitle document with per-word karaoke-fill highlighting."""
    lines = [_HEADER]
    for i in range(0, len(words), chunk_size):
        chunk = words[i:i + chunk_size]
        if not chunk:
            continue
        line_start = max(0.0, chunk[0].start - clip_start)
        line_end = max(line_start + 0.2, chunk[-1].end - clip_start)

        # Build \kf tags: each word's on-screen highlight duration, in centiseconds,
        # relative to the previous word's end (libass advances the fill per tag).
        karaoke_text = ""
        prev_end = line_start
        for w in chunk:
            w_start = max(prev_end, w.start - clip_start)
            w_end = max(w_start + 0.05, w.end - clip_start)
            duration_cs = int(round((w_end - w_start) * 100))
            text = w.text.strip().replace("{", "").replace("}", "")
            if not text:
                continue
            karaoke_text += f"{{\\kf{duration_cs}}}{text} "
            prev_end = w_end

        if not karaoke_text.strip():
            continue

        lines.append(
            f"Dialogue: 0,{_ass_timestamp(line_start)},{_ass_timestamp(line_end)},"
            f"Karaoke,,0,0,0,,{karaoke_text.strip()}"
        )
    return "\n".join(lines) + "\n"
