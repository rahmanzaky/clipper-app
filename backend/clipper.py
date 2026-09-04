"""Cut, crop to 9:16, and burn captions via ffmpeg.

Crop is face-tracked (see face_crop.py) — falls back to a plain center-crop when no
face is detected in the sampled frames, so the pipeline never hard-fails on a bad clip.
"""
import os
import shutil
import subprocess
import tempfile

from face_crop import compute_crop_x, compute_crop_segments
from captions import build_ass_plain, get_caption_lines

# ffmpeg-full (built with libass, for burned-in subtitles) is keg-only on Homebrew;
# prefer it if present, otherwise fall back to whatever "ffmpeg" is on PATH.
FFMPEG_FULL = "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg"
FFMPEG_BIN = FFMPEG_FULL if os.path.exists(FFMPEG_FULL) else shutil.which("ffmpeg") or "ffmpeg"
FFPROBE_FULL = "/opt/homebrew/opt/ffmpeg-full/bin/ffprobe"
FFPROBE_BIN = FFPROBE_FULL if os.path.exists(FFPROBE_FULL) else shutil.which("ffprobe") or "ffprobe"


def _run(cmd: list):
    """subprocess.run wrapper for ffmpeg/ffprobe calls that actually surfaces the
    real failure reason. subprocess.CalledProcessError's default string form is
    just "Command [...] returned non-zero exit status N" — the actual diagnostic
    info (e.g. "No such file or directory", a bad filter graph, a codec error) is
    sitting right there in .stderr but silently discarded by every caller that
    just lets the CalledProcessError propagate as-is (confirmed: every "Re-render
    failed" message surfaced by the API has been this useless generic string,
    never the real ffmpeg error, for as long as this project has had a web UI).
    """
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        stderr_tail = "\n".join(result.stderr.strip().splitlines()[-6:])
        raise RuntimeError(f"{os.path.basename(cmd[0])} failed (exit {result.returncode}):\n{stderr_tail}")
    return result


def get_video_dimensions(path: str) -> tuple:
    out = _run(
        [FFPROBE_BIN, "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=s=x:p=0", path]
    )
    w, h = out.stdout.strip().split("x")
    return int(w), int(h)


def _encode_segment(source_path, abs_start, abs_end, crop_filter, output_path, extra_vf=None):
    vf = f"{crop_filter},{extra_vf}" if extra_vf else crop_filter
    cmd = [
        FFMPEG_BIN, "-y",
        "-ss", str(abs_start), "-to", str(abs_end),
        "-i", source_path,
        "-vf", vf,
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-c:a", "aac", "-b:a", "128k",
        output_path,
    ]
    _run(cmd)


def make_clip(source_path: str, start: float, end: float, words, output_path: str,
              crop_center_frac: float = None, caption_lines: list = None,
              crop_segments: list = None) -> dict:
    """Cut/crop/caption a clip. Returns {"path", "crop_center_frac", "crop_segments",
    "caption_lines"} reflecting what was actually used — either the caller's manual
    override, or the auto-detected face position(s) / auto-derived caption lines, so
    the caller (api.py) can persist these for later re-render (reposition/segment/
    caption-edit endpoints).

    crop_segments (clip-relative {"start", "end", "crop_center_frac"} dicts) lets a
    single clip use a different crop position across different sub-ranges — needed
    because a clip can span more than one hard cut in a multicam-edited source video,
    where no single static crop position is correct throughout. If not given, one is
    computed: crop_center_frac (a single manual override) collapses to one segment
    covering the whole clip; otherwise shot boundaries are auto-detected and each
    resulting sub-range gets its own auto-computed position (see
    face_crop.compute_crop_segments) — a clip with no detected cuts naturally comes
    back as a single segment, identical to the original single-crop behavior.
    """
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    width, height = get_video_dimensions(source_path)
    target_w = int(height * 9 / 16)

    if caption_lines is None:
        clip_words = [w for w in words if w.start >= start and w.end <= end + 0.5]
        caption_lines = get_caption_lines(clip_words, start)

    if crop_segments is None:
        if crop_center_frac is not None:
            crop_segments = [{"start": 0.0, "end": end - start, "crop_center_frac": crop_center_frac}]
        else:
            crop_segments = compute_crop_segments(source_path, start, end, width, target_w)

    if len(crop_segments) == 1:
        # Fast path — one crop position for the whole clip (no detected cuts, or a
        # manual single-position override): identical to the original single-pass
        # behavior, no extra encode/concat overhead.
        seg = crop_segments[0]
        crop_x = compute_crop_x(source_path, start, end, width, target_w, manual_center_x=seg["crop_center_frac"])
        crop_filter = f"crop={target_w}:{height}:{crop_x}:0,scale=1080:1920"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".ass", delete=False) as f:
            f.write(build_ass_plain(caption_lines))
            ass_path = f.name
        try:
            _encode_segment(source_path, start, end, crop_filter, output_path,
                             extra_vf=f"subtitles=filename={ass_path}")
        finally:
            os.unlink(ass_path)
    else:
        # Multiple crop positions across the clip's timeline: encode each segment
        # with its own crop, concat them back together, then burn captions in one
        # final pass over the concatenated result (captions are already
        # clip-relative, so their timing stays correct across the concatenation).
        temp_dir = tempfile.mkdtemp(prefix="clipper_seg_")
        try:
            seg_paths = []
            for i, seg in enumerate(crop_segments):
                abs_s, abs_e = start + seg["start"], start + seg["end"]
                crop_x = compute_crop_x(source_path, abs_s, abs_e, width, target_w,
                                         manual_center_x=seg["crop_center_frac"])
                crop_filter = f"crop={target_w}:{height}:{crop_x}:0,scale=1080:1920"
                seg_path = os.path.join(temp_dir, f"seg{i}.mp4")
                _encode_segment(source_path, abs_s, abs_e, crop_filter, seg_path)
                seg_paths.append(seg_path)

            concat_list_path = os.path.join(temp_dir, "concat_list.txt")
            with open(concat_list_path, "w") as f:
                for p in seg_paths:
                    f.write(f"file '{p}'\n")
            merged_path = os.path.join(temp_dir, "merged.mp4")
            _run([FFMPEG_BIN, "-y", "-f", "concat", "-safe", "0", "-i", concat_list_path,
                  "-c", "copy", merged_path])

            with tempfile.NamedTemporaryFile(mode="w", suffix=".ass", delete=False) as f:
                f.write(build_ass_plain(caption_lines))
                ass_path = f.name
            try:
                cmd = [
                    FFMPEG_BIN, "-y", "-i", merged_path,
                    "-vf", f"subtitles=filename={ass_path}",
                    "-c:v", "libx264", "-preset", "fast", "-crf", "20",
                    "-c:a", "aac", "-b:a", "128k",
                    output_path,
                ]
                _run(cmd)
            finally:
                os.unlink(ass_path)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    return {
        "path": output_path,
        "crop_center_frac": crop_segments[0]["crop_center_frac"],
        "crop_segments": crop_segments,
        "caption_lines": caption_lines,
    }
