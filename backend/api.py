"""FastAPI backend for the Auto Video Clipper web UI.

Wraps the existing CLI pipeline (downloader/transcriber/detector/clipper/compliance)
behind an HTTP API so the React frontend can drive it: submit a job, watch the source
video immediately while highlight markers stream in progressively during
transcription, review/re-crop/re-caption ranked candidate clips, cut a manual clip at
any time without waiting for the automated pipeline, and re-trim any clip's duration
after the fact (re-running the same face-crop + caption + compliance logic on the new
bounds).
"""
import json
import os
import shutil
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from fastapi import FastAPI, HTTPException, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from downloader import download_video
from transcriber import transcribe_stream
from detector import _score_batch, _merge_segments, _keyword_hit_score, BATCH_SIZE
from clipper import make_clip
from compliance import CampaignProfile, check_clip
from profiles import list_profiles, load_profile, save_profile

WORK_DIR = os.path.join(os.path.dirname(__file__), "..", "work")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "output")
FAILED_DIR = os.path.join(OUTPUT_DIR, "_dev_failed")
os.makedirs(WORK_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(FAILED_DIR, exist_ok=True)

RENDER_WORKERS = 3  # ffmpeg is a subprocess — no GIL contention, so a few clips can
                     # render concurrently instead of the old strictly-sequential loop.
KEYWORD_UPDATE_EVERY = 5  # segments — how often to refresh highlight_markers in
                           # keyword mode, where scoring a segment is free.
MANUAL_INDEX_BASE = 100_000  # manual clips are indexed well above any realistic
                              # automatic-candidate count, so the two index spaces
                              # never collide regardless of processing order.

app = FastAPI(title="Auto Video Clipper API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory job store. Single-user local tool — no DB needed. Keyed by job_id.
JOBS = {}


class ProcessRequest(BaseModel):
    url: str
    topics: list[str] = []
    min_duration: float = 8.0
    max_duration: float = 60.0
    hashtag: str = ""


class TrimRequest(BaseModel):
    start: float
    end: float


class RepositionRequest(BaseModel):
    crop_center_frac: float


class CaptionLine(BaseModel):
    text: str
    start: float
    end: float


class CaptionsRequest(BaseModel):
    lines: list[CaptionLine]


class ManualClipRequest(BaseModel):
    start: float
    end: float


class SaveProfileRequest(BaseModel):
    name: str
    topics: list[str] = []
    min_duration: float = 8.0
    max_duration: float = 60.0
    hashtag: str = ""


def _quarantine_if_failed(job, clip_dict, rendered_path):
    """Move a non-compliant clip's file out of the main output/ dir into a dev-only
    folder with a sidecar of why it failed — keeps the main results clean for the
    user while still letting them inspect failures for development/testing.
    Returns True if the clip was quarantined (caller should not surface it).
    """
    if clip_dict["compliance"]["passed"]:
        return False
    job_failed_dir = os.path.join(FAILED_DIR, job["id"])
    os.makedirs(job_failed_dir, exist_ok=True)
    dest = os.path.join(job_failed_dir, os.path.basename(rendered_path))
    if os.path.exists(rendered_path):
        shutil.move(rendered_path, dest)
    with open(dest + ".json", "w") as f:
        json.dump(clip_dict, f, indent=2)
    return True


def _render_one(video_path, cand_start, cand_end, words, out_path, profile, index, text, reason, score):
    result_meta = make_clip(video_path, cand_start, cand_end, words, out_path)
    compliance = check_clip(cand_start, cand_end, text, profile)
    return {
        "index": index,
        "start": cand_start,
        "end": cand_end,
        "duration": cand_end - cand_start,
        "text": text,
        "reason": reason,
        "score": score,
        "compliance": {"passed": compliance.passed, "issues": compliance.issues},
        "clip_filename": os.path.basename(out_path),
        "crop_center_frac": result_meta["crop_center_frac"],
        "caption_lines": result_meta["caption_lines"],
        "_rendered_path": out_path,
    }


def _run_pipeline(job_id: str, req: ProcessRequest, local_video_path: str = None):
    job = JOBS[job_id]
    profile = CampaignProfile(
        topics=req.topics,
        min_duration=req.min_duration,
        max_duration=req.max_duration,
        required_hashtag=req.hashtag,
    )
    job["profile"] = profile
    use_groq = bool(os.environ.get("GROQ_API_KEY"))

    try:
        if local_video_path is None:
            job["stage"] = "downloading"

            def on_progress(info):
                job["download_percent"] = info["percent"]

            video_path = download_video(req.url, WORK_DIR, progress_callback=on_progress)
        else:
            video_path = local_video_path
        job["video_path"] = video_path
        job["video_ready"] = True

        job["stage"] = "transcribing"
        job["words"] = []
        segments = []
        buffer = []  # (index, segment) not yet scored
        hit_scores = {}
        topics_lower = [t.lower() for t in req.topics if t.strip()]

        def refresh_markers():
            candidates = _merge_segments(segments, hit_scores)
            job["highlight_markers"] = [
                {"start": c.start, "end": c.end, "score": c.score, "reason": c.reason}
                for c in candidates
            ]

        for seg in transcribe_stream(video_path):
            idx = len(segments)
            segments.append(seg)
            job["words"].extend(seg.words)
            buffer.append((idx, seg))

            if use_groq:
                if len(buffer) >= BATCH_SIZE:
                    offset = buffer[0][0]
                    batch_segs = [s for _, s in buffer]
                    try:
                        hit_scores.update(_score_batch(batch_segs, offset, req.topics, os.environ["GROQ_API_KEY"]))
                    except Exception as e:
                        print(f"[api] Incremental Groq batch at segment {offset} failed, skipping: {e}")
                    buffer = []
                    refresh_markers()
            else:
                if topics_lower:
                    hits = _keyword_hit_score(seg, topics_lower)
                    if hits > 0:
                        hit_scores[idx] = hits
                if idx % KEYWORD_UPDATE_EVERY == 0:
                    refresh_markers()

        # Flush any remaining buffered segments (Groq mode only — keyword mode
        # scores immediately per-segment, nothing to buffer).
        if use_groq and buffer:
            offset = buffer[0][0]
            batch_segs = [s for _, s in buffer]
            try:
                hit_scores.update(_score_batch(batch_segs, offset, req.topics, os.environ["GROQ_API_KEY"]))
            except Exception as e:
                print(f"[api] Final Groq batch at segment {offset} failed, skipping: {e}")

        job["segments"] = segments

        job["stage"] = "detecting"
        candidates = _merge_segments(segments, hit_scores)
        for c in candidates:
            if use_groq:
                c.reason = f"LLM: relevant to {', '.join(req.topics) or 'anything highlight-worthy'}"
        job["candidates"] = candidates
        job["highlight_markers"] = [
            {"start": c.start, "end": c.end, "score": c.score, "reason": c.reason} for c in candidates
        ]

        if not candidates:
            job["stage"] = "done"
            job.setdefault("clips", [])  # preserve any manual clips created while waiting
            return

        job["stage"] = "rendering"
        base = os.path.splitext(os.path.basename(video_path))[0]
        all_words = job["words"]
        clips = []

        with ThreadPoolExecutor(max_workers=RENDER_WORKERS) as pool:
            futures = []
            for i, cand in enumerate(candidates):
                out_name = f"{base}_clip{i}.mp4"
                out_path = os.path.join(OUTPUT_DIR, out_name)
                futures.append(pool.submit(
                    _render_one, video_path, cand.start, cand.end, all_words, out_path,
                    profile, i, cand.text, cand.reason, cand.score,
                ))
            for i, fut in enumerate(futures):
                try:
                    clip = fut.result()
                except Exception as e:
                    job.setdefault("render_errors", []).append(f"Clip {i}: {e}")
                    continue
                rendered_path = clip.pop("_rendered_path")
                if _quarantine_if_failed(job, clip, rendered_path):
                    continue
                clips.append(clip)

        # Merge with any manual clips already created (and appended directly to
        # job["clips"]) while the automatic pipeline was still running — don't
        # discard them. Manual indices live in a separate numeric range
        # (MANUAL_INDEX_BASE+) so there's never a collision to resolve. Locked
        # against manual_clip's concurrent append (see job["lock"]) — without this,
        # a "Create clip now" click landing between this read and the reassignment
        # below gets silently lost (confirmed as a real bug during testing).
        with job["lock"]:
            manual_clips = job.get("clips", [])
            clips.extend(manual_clips)
            clips.sort(key=lambda c: c["index"])
            job["clips"] = clips
        job["stage"] = "done"
    except Exception as e:
        job["stage"] = "error"
        job["error"] = str(e)


def _start_job(req: ProcessRequest, local_video_path: str = None) -> str:
    job_id = str(uuid.uuid4())
    JOBS[job_id] = {
        "id": job_id, "stage": "queued", "request": req.model_dump(),
        "next_manual_index": MANUAL_INDEX_BASE,
        # Guards job["clips"] and job["next_manual_index"] against the real race
        # between the background pipeline thread finalizing rendered clips and a
        # concurrent /manual-clip request (e.g. two quick "Create clip now" clicks,
        # or one landing right as auto-rendering finishes).
        "lock": threading.Lock(),
    }
    thread = threading.Thread(target=_run_pipeline, args=(job_id, req, local_video_path), daemon=True)
    thread.start()
    return job_id


@app.post("/api/process")
def process(req: ProcessRequest):
    return {"job_id": _start_job(req)}


@app.post("/api/process/upload")
def process_upload(
    file: UploadFile,
    topics: str = Form(""),
    min_duration: float = Form(8.0),
    max_duration: float = Form(60.0),
    hashtag: str = Form(""),
):
    """Accept a directly-uploaded local video file instead of a URL — same pipeline,
    but skips the downloading stage entirely since the file is already local.
    """
    dest_name = f"{uuid.uuid4().hex}_{os.path.basename(file.filename)}"
    dest_path = os.path.join(WORK_DIR, dest_name)
    with open(dest_path, "wb") as out:
        shutil.copyfileobj(file.file, out)

    req = ProcessRequest(
        url="",
        topics=[t.strip() for t in topics.split(",") if t.strip()],
        min_duration=min_duration,
        max_duration=max_duration,
        hashtag=hashtag,
    )
    return {"job_id": _start_job(req, local_video_path=dest_path)}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    response = {"stage": job["stage"], "video_ready": job.get("video_ready", False)}
    if "download_percent" in job:
        response["download_percent"] = job["download_percent"]
    if job.get("highlight_markers"):
        response["highlight_markers"] = job["highlight_markers"]
    if job["stage"] == "error":
        response["error"] = job["error"]
    # Include clips whenever any exist — not just once the whole job is "done" —
    # so a manual clip created mid-processing (while automatic detection/rendering
    # is still running) shows up on the very next poll instead of being hidden
    # until the automatic pipeline finishes.
    if job.get("clips"):
        response["clips"] = job["clips"]
    if job["stage"] == "done":
        response.setdefault("clips", [])
        response["render_errors"] = job.get("render_errors", [])
    return response


def _find_clip(job, clip_index):
    for clip in job.get("clips", []):
        if clip["index"] == clip_index:
            return clip
    return None


@app.post("/api/clips/{job_id}/{clip_index}/trim")
def trim_clip(job_id: str, clip_index: int, req: TrimRequest):
    job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    if "video_path" not in job:
        raise HTTPException(400, "Source video not ready yet")
    if req.end <= req.start:
        raise HTTPException(400, "End must be after start")

    clip = _find_clip(job, clip_index)
    if clip is None:
        raise HTTPException(404, "Clip not found")
    video_path = job["video_path"]
    words = job.get("words", [])
    profile = job.get("profile") or CampaignProfile()
    base = os.path.splitext(os.path.basename(video_path))[0]
    out_name = f"{base}_clip{clip_index}.mp4"
    out_path = os.path.join(OUTPUT_DIR, out_name)

    # Trimming to a new range invalidates the old caption lines (different words in
    # range) but keeps any manual crop override the user had already applied.
    crop_frac = clip["crop_center_frac"]
    try:
        result_meta = make_clip(video_path, req.start, req.end, words, out_path, crop_center_frac=crop_frac)
    except Exception as e:
        raise HTTPException(500, f"Re-render failed: {e}")

    result = check_clip(req.start, req.end, "", profile)
    clip["start"] = req.start
    clip["end"] = req.end
    clip["duration"] = req.end - req.start
    clip["compliance"] = {"passed": result.passed, "issues": result.issues}
    clip["crop_center_frac"] = result_meta["crop_center_frac"]
    clip["caption_lines"] = result_meta["caption_lines"]

    return {
        "index": clip_index,
        "start": req.start,
        "end": req.end,
        "duration": req.end - req.start,
        "compliance": {"passed": result.passed, "issues": result.issues},
        "clip_filename": out_name,
        "crop_center_frac": result_meta["crop_center_frac"],
        "caption_lines": result_meta["caption_lines"],
    }


@app.post("/api/clips/{job_id}/{clip_index}/reposition")
def reposition_clip(job_id: str, clip_index: int, req: RepositionRequest):
    job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    clip = _find_clip(job, clip_index)
    if clip is None:
        raise HTTPException(404, "Clip not found")
    if not (0.0 <= req.crop_center_frac <= 1.0):
        raise HTTPException(400, "crop_center_frac must be between 0.0 and 1.0")

    video_path = job["video_path"]
    words = job["words"]
    base = os.path.splitext(os.path.basename(video_path))[0]
    out_name = f"{base}_clip{clip_index}.mp4"
    out_path = os.path.join(OUTPUT_DIR, out_name)

    try:
        result_meta = make_clip(
            video_path, clip["start"], clip["end"], words, out_path,
            crop_center_frac=req.crop_center_frac, caption_lines=clip.get("caption_lines"),
        )
    except Exception as e:
        raise HTTPException(500, f"Re-render failed: {e}")

    clip["crop_center_frac"] = result_meta["crop_center_frac"]
    return {"index": clip_index, "crop_center_frac": clip["crop_center_frac"], "clip_filename": out_name}


@app.post("/api/clips/{job_id}/{clip_index}/captions")
def edit_captions(job_id: str, clip_index: int, req: CaptionsRequest):
    job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    clip = _find_clip(job, clip_index)
    if clip is None:
        raise HTTPException(404, "Clip not found")

    video_path = job["video_path"]
    words = job["words"]
    base = os.path.splitext(os.path.basename(video_path))[0]
    out_name = f"{base}_clip{clip_index}.mp4"
    out_path = os.path.join(OUTPUT_DIR, out_name)
    new_lines = [line.model_dump() for line in req.lines]

    try:
        result_meta = make_clip(
            video_path, clip["start"], clip["end"], words, out_path,
            crop_center_frac=clip.get("crop_center_frac"), caption_lines=new_lines,
        )
    except Exception as e:
        raise HTTPException(500, f"Re-render failed: {e}")

    clip["caption_lines"] = result_meta["caption_lines"]
    # Re-check compliance against the edited text — the required-hashtag rule reads
    # caption text, so editing it (e.g. typing in the campaign hashtag by hand) can
    # flip pass/fail. Without this, the badge would silently go stale after an edit.
    profile = job.get("profile") or CampaignProfile()
    joined_text = " ".join(line["text"] for line in clip["caption_lines"])
    result = check_clip(clip["start"], clip["end"], joined_text, profile)
    clip["compliance"] = {"passed": result.passed, "issues": result.issues}
    return {
        "index": clip_index,
        "caption_lines": clip["caption_lines"],
        "compliance": clip["compliance"],
        "clip_filename": out_name,
    }


@app.post("/api/jobs/{job_id}/manual-clip")
def manual_clip(job_id: str, req: ManualClipRequest):
    """Cut a clip right now from whatever's been transcribed so far — lets the user
    clip manually while the automatic pipeline is still running, instead of waiting.
    """
    job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    if "video_path" not in job:
        raise HTTPException(400, "Source video not ready yet")
    if req.end <= req.start:
        raise HTTPException(400, "End must be after start")

    video_path = job["video_path"]
    words = job.get("words", [])
    profile = job.get("profile") or CampaignProfile()
    with job["lock"]:
        index = job.get("next_manual_index", MANUAL_INDEX_BASE)
        job["next_manual_index"] = index + 1

    base = os.path.splitext(os.path.basename(video_path))[0]
    out_name = f"{base}_clip{index}.mp4"
    out_path = os.path.join(OUTPUT_DIR, out_name)

    try:
        result_meta = make_clip(video_path, req.start, req.end, words, out_path)
    except Exception as e:
        raise HTTPException(500, f"Render failed: {e}")

    result = check_clip(req.start, req.end, "", profile)
    clip = {
        "index": index,
        "start": req.start,
        "end": req.end,
        "duration": req.end - req.start,
        "text": "",
        "reason": "manual selection",
        "score": 0.0,
        "compliance": {"passed": result.passed, "issues": result.issues},
        "clip_filename": out_name,
        "crop_center_frac": result_meta["crop_center_frac"],
        "caption_lines": result_meta["caption_lines"],
        "manual": True,
    }
    with job["lock"]:
        job.setdefault("clips", []).append(clip)
    return clip


@app.get("/api/video/source/{job_id}")
def get_source_video(job_id: str):
    job = JOBS.get(job_id)
    if job is None or "video_path" not in job:
        raise HTTPException(404, "Source video not available")
    return FileResponse(job["video_path"], media_type="video/mp4")


@app.get("/api/video/clip/{filename}")
def get_clip_video(filename: str):
    # filename is a bare basename (never a path) — reject anything that could escape
    # OUTPUT_DIR before it ever touches the filesystem.
    if "/" in filename or "\\" in filename or filename in (".", ".."):
        raise HTTPException(400, "Invalid filename")
    path = os.path.join(OUTPUT_DIR, filename)
    if not os.path.exists(path):
        raise HTTPException(404, "Clip not found")
    return FileResponse(path, media_type="video/mp4")


@app.get("/api/source-duration/{job_id}")
def get_source_duration(job_id: str):
    """Return the full source video's duration, so the frontend can bound the trim
    sliders and timeline to the actual video length rather than just a clip's range.
    """
    from clipper import FFPROBE_BIN
    import subprocess

    job = JOBS.get(job_id)
    if job is None or "video_path" not in job:
        raise HTTPException(404, "Source video not available")
    out = subprocess.run(
        [FFPROBE_BIN, "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", job["video_path"]],
        capture_output=True, text=True, check=True,
    )
    return {"duration": float(out.stdout.strip())}


@app.get("/api/profiles")
def get_profiles():
    return list_profiles()


@app.post("/api/profiles")
def post_profile(req: SaveProfileRequest):
    save_profile(req.name, req.topics, req.min_duration, req.max_duration, req.hashtag)
    return {"saved": req.name}
