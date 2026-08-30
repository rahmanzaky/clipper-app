"""Cut, crop to 9:16, and burn captions via ffmpeg.

Crop is face-tracked (see face_crop.py) — falls back to a plain center-crop when no
face is detected in the sampled frames, so the pipeline never hard-fails on a bad clip.
"""
import os
import shutil
import subprocess
import tempfile

from face_crop import compute_crop_x
from captions import build_ass_karaoke

# ffmpeg-full (built with libass, for burned-in subtitles) is keg-only on Homebrew;
# prefer it if present, otherwise fall back to whatever "ffmpeg" is on PATH.
FFMPEG_FULL = "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg"
FFMPEG_BIN = FFMPEG_FULL if os.path.exists(FFMPEG_FULL) else shutil.which("ffmpeg") or "ffmpeg"
FFPROBE_FULL = "/opt/homebrew/opt/ffmpeg-full/bin/ffprobe"
FFPROBE_BIN = FFPROBE_FULL if os.path.exists(FFPROBE_FULL) else shutil.which("ffprobe") or "ffprobe"


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

    # Face-tracked crop to 9:16 (falls back to center-crop if no face found),
    # then scale to 1080x1920.
    target_w = int(height * 9 / 16)
    crop_x = compute_crop_x(source_path, start, end, width, target_w)
    crop_filter = f"crop={target_w}:{height}:{crop_x}:0,scale=1080:1920"

    with tempfile.NamedTemporaryFile(mode="w", suffix=".ass", delete=False) as f:
        clip_words = [w for w in words if w.start >= start and w.end <= end + 0.5]
        f.write(build_ass_karaoke(clip_words, start))
        ass_path = f.name

    try:
        vf = f"{crop_filter},subtitles=filename={ass_path}"
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
        os.unlink(ass_path)

    return output_path
