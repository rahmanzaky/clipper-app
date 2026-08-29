"""Cut, crop to 9:16, and burn captions via ffmpeg.

MVP note: crop is a simple center-crop (not the face-tracked MediaPipe crop from
the full plan) — good enough to validate the end-to-end pipeline; swap in
MediaPipe-based tracking as a follow-up once this core path is proven.
"""
import os
import shutil
import subprocess
import tempfile

# ffmpeg-full (built with libass, for burned-in subtitles) is keg-only on Homebrew;
# prefer it if present, otherwise fall back to whatever "ffmpeg" is on PATH.
FFMPEG_FULL = "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg"
FFMPEG_BIN = FFMPEG_FULL if os.path.exists(FFMPEG_FULL) else shutil.which("ffmpeg") or "ffmpeg"
FFPROBE_FULL = "/opt/homebrew/opt/ffmpeg-full/bin/ffprobe"
FFPROBE_BIN = FFPROBE_FULL if os.path.exists(FFPROBE_FULL) else shutil.which("ffprobe") or "ffprobe"


def _srt_timestamp(seconds: float) -> str:
    if seconds < 0:
        seconds = 0
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _build_srt(words, clip_start: float, chunk_size: int = 5) -> str:
    """Group words into short caption chunks, timestamps relative to clip_start."""
    lines = []
    idx = 1
    for i in range(0, len(words), chunk_size):
        chunk = words[i:i + chunk_size]
        if not chunk:
            continue
        start = max(0.0, chunk[0].start - clip_start)
        end = max(start + 0.2, chunk[-1].end - clip_start)
        text = " ".join(w.text for w in chunk).strip()
        if not text:
            continue
        lines.append(f"{idx}\n{_srt_timestamp(start)} --> {_srt_timestamp(end)}\n{text}\n")
        idx += 1
    return "\n".join(lines)


def get_video_dimensions(path: str) -> tuple:
    out = subprocess.run(
        [FFPROBE_BIN, "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=s=x:p=0", path],
        capture_output=True, text=True, check=True,
    )
    w, h = out.stdout.strip().split("x")
    return int(w), int(h)


def make_clip(source_path: str, start: float, end: float, words, output_path: str) -> str:
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    width, height = get_video_dimensions(source_path)

    # Center-crop to 9:16, then scale to 1080x1920.
    target_w = int(height * 9 / 16)
    crop_x = max(0, (width - target_w) // 2)
    crop_filter = f"crop={target_w}:{height}:{crop_x}:0,scale=1080:1920"

    with tempfile.NamedTemporaryFile(mode="w", suffix=".srt", delete=False) as f:
        clip_words = [w for w in words if w.start >= start and w.end <= end + 0.5]
        f.write(_build_srt(clip_words, start))
        srt_path = f.name

    try:
        vf = f"{crop_filter},subtitles=filename={srt_path}:force_style='Fontsize=16,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=3'"
        cmd = [
            FFMPEG_BIN, "-y",
            "-ss", str(start), "-to", str(end),
            "-i", source_path,
            "-vf", vf,
            "-c:v", "libx264", "-preset", "fast", "-crf", "20",
            "-c:a", "aac", "-b:a", "128k",
            output_path,
        ]
        subprocess.run(cmd, capture_output=True, text=True, check=True)
    finally:
        os.unlink(srt_path)

    return output_path
