"""Plain, elegant burned-in captions (ASS format via libass) — static per-line
subtitle text, movie-subtitle style, no per-word highlight animation.
"""

_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Subtitle,Arial,58,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,1,2,60,60,120,1

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


def get_caption_lines(words, clip_start: float, chunk_size: int = 5) -> list:
    """Group words into short caption lines relative to the clip's own start time.
    Returns a list of {"text", "start", "end"} dicts — decoupled from raw ASR word
    objects so callers (the caption editor, either ASS builder) can consume/produce
    plain data instead of re-deriving from `words` every time.
    """
    lines = []
    for i in range(0, len(words), chunk_size):
        chunk = words[i:i + chunk_size]
        if not chunk:
            continue
        text = " ".join(w.text.strip() for w in chunk if w.text.strip())
        if not text:
            continue
        line_start = max(0.0, chunk[0].start - clip_start)
        line_end = max(line_start + 0.2, chunk[-1].end - clip_start)
        lines.append({"text": text, "start": line_start, "end": line_end})
    return lines


def build_ass_plain(lines) -> str:
    """Build a static ASS subtitle document from caption line dicts ({"text",
    "start", "end"}, clip-relative seconds) — one flat Dialogue line per chunk, no
    per-word animation, styled like a movie subtitle (bottom-center, clean outline).
    """
    out = [_HEADER]
    for line in lines:
        text = line["text"].strip().replace("{", "").replace("}", "")
        if not text:
            continue
        out.append(
            f"Dialogue: 0,{_ass_timestamp(line['start'])},{_ass_timestamp(line['end'])},"
            f"Subtitle,,0,0,0,,{text}"
        )
    return "\n".join(out) + "\n"
