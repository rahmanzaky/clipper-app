# Auto Video Clipper

Paste a video (YouTube URL, a public Google Drive link, or upload a file directly),
get compliance-checked vertical clips out. Built for competing in paid clipping
campaigns (Whop/Evangelist-style — e.g. Lovable Clipping).

A FastAPI backend wraps the full pipeline (download → transcribe → detect → crop →
caption → compliance-check); a React web UI drives it — submit a job, watch progress
live, review ranked candidate clips, and edit any of them (duration, crop, captions)
after the fact without re-running the whole pipeline.

## What it does

1. **Gets the source video** — a YouTube URL, a public Google Drive share link (both
   via `yt-dlp`), or a directly-uploaded local file (skips the download step entirely).
2. **Transcribes it bilingually** (EN/ID, word-level timestamps, `faster-whisper`) —
   streamed, so highlight detection can start working before transcription finishes.
3. **Finds candidate clips**, ranked best-first by relevance score:
   - If `GROQ_API_KEY` is set: asks Groq's free-tier LLM which segments discuss your
     topic (0–10 relevance score each) — catches paraphrases keyword matching misses.
   - Otherwise: falls back to plain keyword matching (zero setup, always works),
     scored by keyword-hit density.
   - Highlight markers appear on the source-video timeline progressively as
     detection runs, not just after the whole job finishes — you can also select
     your own range and cut a clip manually at any time, without waiting.
4. **Cuts, crops to 9:16, and captions each candidate**:
   - Face-tracked crop (OpenCV Haar cascade), clustering multiple sampled face
     positions instead of averaging them — averaging blends two different
     speakers' positions into the empty gap between them, clustering picks the
     more consistently-detected one instead.
   - **Multi-segment crop**: a clip can span more than one camera cut in the
     source (a multicam-edited podcast switching between a wide shot and
     close-ups) — shot boundaries are auto-detected (via sustained face-presence
     changes, not color, since same-set/same-lighting camera angles don't
     reliably differ in color) and each resulting segment gets its own
     independently-computed crop position. A manual segment editor (numbered,
     clickable timeline blocks; split/merge; per-segment pan slider; live
     masked-overlay preview of exactly what stays in frame) lets you override
     auto-detection per segment.
   - Plain, elegant burned-in captions (movie-subtitle style — no karaoke-style
     word-highlight animation), editable per line after the fact (text only,
     same timing), Descript/CapCut-style transcript-based editing.
5. **Checks each clip against your campaign's rules** (min/max duration, required
   hashtag) and reports pass/fail before you submit anywhere. Non-compliant clips
   are quarantined to `output/_dev_failed/` instead of cluttering your results.
6. **Campaign profiles** — save a named set of topic/duration/hashtag rules once,
   reload (or delete) it from a dropdown on future runs instead of re-typing them.

## Running it

Two processes: the backend API and the frontend dev server.

```bash
# Backend
cd backend
source ../venv/bin/activate          # see Setup below if this doesn't exist yet
HF_HUB_DISABLE_XET=1 WHISPER_MODEL=small uvicorn api:app --host 127.0.0.1 --port 8000
```

```bash
# Frontend (separate terminal)
cd frontend
npm install                          # first time only
npm run dev
```

Then open **http://localhost:5173**. `WHISPER_MODEL=small` above is for fast local
iteration — drop it (or set `WHISPER_MODEL=large-v3-turbo`, the default) for real
campaign submissions where bilingual transcription accuracy matters more than speed.

**Job state lives in memory only** — restarting the backend loses all in-progress
and completed jobs (their rendered files on disk are cleaned up automatically after
24h, or immediately via the "Clean up old files now" button). A browser page refresh
does *not* lose your job — the job ID is kept in the URL and reattaches automatically;
only an actual backend restart does.

## Setup

```bash
cd backend
python3 -m venv ../venv          # already done if you're reading this after setup
source ../venv/bin/activate
pip install -r requirements.txt
```

```bash
cd frontend
npm install
```

**Requires `ffmpeg-full`, not plain `ffmpeg`** — burned-in captions use libass,
which Homebrew's regular `ffmpeg` formula doesn't include:

```bash
brew install ffmpeg-full
```

`ffmpeg-full` is keg-only (won't overwrite a plain `ffmpeg` you already have) —
`clipper.py` automatically looks for it at `/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg`
first and falls back to whatever `ffmpeg` is on PATH otherwise.

**Face detection** uses OpenCV's Haar cascade (not MediaPipe — MediaPipe 1.0.1's
package import chain pulls in matplotlib, whose font manager crashes on this
machine's macOS version; OpenCV avoids that entirely). The model file
(`backend/models/haarcascade_frontalface_default.xml`) is checked into the repo, no
extra download needed.

**Groq API key** (optional but recommended) — get a free one at console.groq.com and
put it in a `.env` file at the project root (never committed — already in
`.gitignore`):

```
GROQ_API_KEY=your-key-here
```

Both `api.py` (web backend) and `main.py` (CLI) load this automatically via
`python-dotenv`. Without a key, the tool still works using keyword matching instead —
weaker recall on paraphrases, but zero setup.

The first run downloads the Whisper model weights from Hugging Face (one-time,
~150MB for `small`, ~1.5GB for `large-v3-turbo`). If your connection is flaky and
downloads keep failing with a "CAS Client Error" or similar, disable Hugging Face's
newer Xet transfer backend, which handles unstable connections worse than plain HTTP:

```bash
export HF_HUB_DISABLE_XET=1
```

You can also override which Whisper model size is used (default is `large-v3-turbo`,
best bilingual accuracy but the biggest download):

```bash
export WHISPER_MODEL=small   # faster first run, weaker Indonesian accuracy
```

## CLI mode (still available)

The original CLI entry point still works, useful for scripting a single run without
the web UI:

```bash
source venv/bin/activate
cd backend
python main.py --url "https://youtube.com/watch?v=..." \
  --topic "Lovable" --topic "Anton" \
  --min-duration 15 --max-duration 60 \
  --hashtag "#LovablePartner"
```

```bash
# Save a campaign's rules once, reuse by name later
python main.py --url "..." --topic "Lovable" --min-duration 15 --max-duration 60 \
  --hashtag "#LovablePartner" --save-profile lovable
python main.py --url "https://youtube.com/watch?v=DIFFERENT_VIDEO" --profile lovable
```

Clips land in `output/`, ranked best-first by relevance score. The web UI is the
primary interface now — this remains for quick one-off scripted runs. Profiles saved
via the CLI and the web UI share the same `campaigns.json` (gitignored — your
personal campaign list, not committed).

## Known limitations

- **Per-segment language tagging is a whole-file approximation.** faster-whisper
  detects one language for the entire audio file, not per segment — for genuinely
  code-switched EN/ID content, the reported `language` on each segment is the
  whole-file majority language, not a true per-segment detection. Transcription
  *accuracy* on code-switched speech is still strong — only the per-segment
  *language label* is approximate.
- **Multi-segment crop detection is presence-based, not identity-based.** It detects
  *when the framing changes* (a face appears/disappears, or shifts position) well
  enough to split a clip at real camera cuts, but it doesn't track *which specific
  person* is on screen — two different segments both showing "a face" are each
  cropped independently and correctly, but the system has no concept of "this is
  speaker A again." Good enough for the wide-shot/close-up cut problem it was built
  to fix; not full active-speaker tracking.
- **Backend restart loses all job state** (by design — no database; see "Running
  it" above). A page refresh alone is fine.
- **Compliance checks are clip-level only.** Account-level campaign requirements
  (comments-on, minimum-tier viewership, etc.) aren't and can't be checked here.

## Testing

```bash
cd backend
source ../venv/bin/activate
pytest tests/ -v
```

67 tests, no network/model calls, runs in well under a second. Covers
`detector.py`'s merge/scoring/ranking logic, `compliance.py`'s pass/fail rules,
`captions.py`'s ASS timestamp math and plain-caption building, `face_crop.py`'s
crop-clamping boundary logic, clustering, and shot-boundary detection (the latter's
test fixtures are real recorded sample sequences from two calibration videos, not
invented data — see the module docstring for how the detection approach was chosen),
and `tests/test_api.py`'s FastAPI-`TestClient`-based coverage of the web API's
request validation, 404 handling, and endpoint logic (with `make_clip` mocked out
where an endpoint would otherwise shell out to ffmpeg).

**Real end-to-end smoke test** — the above is all pure-logic/mocked; to actually
exercise a real job against a running backend (real download, transcription,
rendering, every edit endpoint), with the backend already running:

```bash
cd backend
./scripts/smoke_test.sh
```

Formalizes the manual curl-based verification this project has relied on every
session into something you don't have to re-derive from scratch each time.

## Error handling

`downloader.py` and `detector.py`'s Groq path both retry transient failures with
exponential backoff (`retry.py`) before giving up. `api.py` wraps each pipeline stage
so a failure produces a clear `stage: "error"` with a readable message instead of a
raw traceback; a single clip's cut/crop/caption failure skips that clip and continues
with the rest of the batch rather than aborting everything.

## Verification performed

Every feature has been tested with real execution, not just written and assumed to
work — this caught real bugs along the way, including: an ffmpeg filter syntax issue,
a missing libass dependency, a MediaPipe/matplotlib/macOS incompatibility, a stale
React closure that silently re-fetched an endpoint on every poll instead of once, a
missing Cache-Control header that made Safari serve pre-edit video bytes after a
real, correctly-applied crop change, and a shot-detection approach (color histograms)
that looked reasonable but failed on real same-lighting multicam footage — caught by
testing against an actual problem clip, not just a synthetic one, before shipping it.

Full history of what was built, tested, and fixed in each phase is in the git log —
each phase's commits describe the real testing performed, not just the feature added.
