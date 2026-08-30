# Auto Video Clipper — Phase 3

Paste a YouTube URL, get compliance-checked vertical clips out. Built for competing
in paid clipping campaigns (Whop/Evangelist-style — e.g. Lovable Clipping).

## What it does

1. Downloads the source video (`yt-dlp`)
2. Transcribes it bilingually, EN/ID, with word-level timestamps (`faster-whisper`,
   large-v3-turbo model)
3. Finds candidate clips two ways, ranked best-first by relevance score:
   - If `GROQ_API_KEY` is set: asks Groq's free-tier LLM which segments discuss your
     topic (0-10 relevance score each) — catches paraphrases keyword matching misses
     (verified: correctly flagged a segment referencing a topic indirectly, with no
     literal keyword present, that keyword matching completely missed)
   - Otherwise: falls back to plain keyword matching (zero setup, always works),
     scored by keyword-hit density
4. Cuts each candidate, **face-tracks the crop to 9:16** (OpenCV Haar cascade —
   centers on the detected speaker's face, falls back to a plain center-crop if no
   face is found in the sampled frames), burns in **word-level karaoke-style
   captions** (ASS format, CapCut-style highlight sweep), exports to `output/`
5. Checks each clip against your campaign's rules (min/max duration, required
   hashtag) and reports pass/fail before you submit anywhere
6. **Campaign profiles** — save a named set of topic/duration/hashtag rules once,
   reload it by name on future runs instead of re-typing flags

## Setup

```bash
cd backend
python3 -m venv ../venv          # already done if you're reading this after setup
source ../venv/bin/activate
pip install -r requirements.txt
```

**Requires `ffmpeg-full`, not plain `ffmpeg`** — the burned-in captions use libass,
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

`main.py` loads this automatically via `python-dotenv`. Without a key, the tool still
works using keyword matching instead — weaker recall on paraphrases, but zero setup.

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

## Usage

```bash
source venv/bin/activate
cd backend
python main.py --url "https://youtube.com/watch?v=..." \
  --topic "Lovable" --topic "Anton" \
  --min-duration 15 --max-duration 60 \
  --hashtag "#LovablePartner"
```

Clips land in `output/`, named `<video_id>_clip1.mp4`, `_clip2.mp4`, etc., ranked
best-first by relevance score.

### Campaign profiles

Save a campaign's rules once:

```bash
python main.py --url "..." --topic "Lovable" --topic "Anton" \
  --min-duration 15 --max-duration 60 --hashtag "#LovablePartner" \
  --save-profile lovable
```

Then reuse it on future runs without re-typing the flags:

```bash
python main.py --url "https://youtube.com/watch?v=DIFFERENT_VIDEO" --profile lovable
```

Profiles are stored in `campaigns.json` at the project root (gitignored — it's your
personal campaign list, not committed).

## Real speed benchmark result — processing is slow on long content (not a compliance issue)

**Note on campaign timing:** the Lovable-style "submit within 10 minutes" rule is
about the gap between *posting a clip* and *submitting its URL* to the campaign
platform for view-tracking — it has nothing to do with how long clip production
takes. Nothing below is "failing to meet" that rule. Speed still matters for two
real reasons: more clips produced per hour directly affects pay-per-view earnings,
and nobody wants to sit around waiting unnecessarily long per video.

Tested against a real ~16.4-minute podcast (not a toy clip), using the `small`
Whisper model (the default `large-v3-turbo`'s ~1.5GB download was impractically slow
on this network — actual production use would be *slower* than these numbers, not
faster):

| Stage | Real measured time | Real-time factor |
|---|---|---|
| Transcription | ~460-525s for 16.4 min of audio | ~1.9x realtime |
| Groq detection (328 segments, 9 batches) | 48-137s, highly variable | rate-limit-bound, not compute-bound |

**Extrapolated to a real 30-60 minute campaign podcast**, transcription alone would
take roughly **16-32 minutes** with the `small` model. The actual default model
(`large-v3-turbo`) is larger and would be slower still. That's a real amount of time
to wait per source video, and worth improving for throughput — just not a rule
violation.

**A second, separate real bug this benchmark uncovered and fixed:** the original
`detect_groq()` sent an entire transcript as one prompt. On this real 328-segment
transcript that failed outright (empty/invalid LLM response), and retrying hit
Groq's free-tier rate limit (429) immediately after. Fixed by batching (`BATCH_SIZE`
in `detector.py`, 25 segments/call) with inter-batch pacing and per-batch
retry-then-skip (one failed batch no longer sinks the whole transcript's detection)
— but **Groq's free-tier rate limit is still a real, observed bottleneck** on a
transcript this size; expect multiple 429-triggered retries in practice, not just in
theory.

**What this means practically right now:** processing a real 30-60 minute podcast
takes a real amount of time (tens of minutes), which is worth improving for
throughput/earnings even though it isn't blocking any campaign rule. Honest options
going forward, not yet decided or implemented:
- A faster transcription path (GPU/MLX-accelerated Whisper instead of CPU int8,
  or a smaller model as the real default rather than just a testing fallback)
- A paid Groq tier (removes the rate-limit bottleneck)
- Parallelizing what can be parallelized (transcription is inherently sequential
  per audio stream, but cut/crop/caption across multiple candidate clips currently
  runs one at a time and could run concurrently)

This is exactly the kind of gap that only showed up by testing against real-length
content instead of short clips — flagged here rather than glossed over.

## Known limitations

- **Per-segment language tagging is a whole-file approximation.** faster-whisper
  detects one language for the entire audio file, not per segment — for genuinely
  code-switched EN/ID content, the reported `language` on each segment is the
  whole-file majority language, not a true per-segment detection. Transcription
  *accuracy* on code-switched speech is still strong (verified against a real
  bilingual test clip: correctly transcribed pure Indonesian, a code-switched
  EN→ID sentence, and a mostly-English sentence, all in one file) — only the
  per-segment *language label* is approximate.
- **Face tracking is single-face-oriented.** Picks the largest detected face per
  sampled frame; with two speakers side by side it doesn't yet pick "whichever one
  is currently talking," just the more prominent face. Falls back to center-crop
  cleanly if no face is found at all.
- **No React frontend yet** — this is a CLI tool for now.

## Testing

```bash
cd backend
source ../venv/bin/activate
pytest tests/ -v
```

29 tests, pure logic only (no network/model calls), runs in well under a second.
Covers `detector.py`'s merge/scoring/ranking logic (including a real bug this suite
caught on first run: keyword scoring counted *whether* a topic appeared, not *how
many times* — "Lovable Lovable Lovable" scored the same as one mention, now fixed),
`compliance.py`'s pass/fail rules, `captions.py`'s ASS timestamp math, and
`face_crop.py`'s crop-clamping boundary logic.

## Error handling

`downloader.py` and `detector.py`'s Groq path both retry transient failures with
exponential backoff (`retry.py`) before giving up — verified for real by forcing an
invalid Groq key (confirmed 3 retry attempts, then a clean fallback to keyword
matching) and an invalid video URL (confirmed 3 retries, then a clear error message
instead of a raw traceback). `main.py` wraps each pipeline stage so a failure prints
an actionable `[FAILED at <stage>]` message; a single clip's cut/crop/caption failure
skips that clip and continues with the rest of the batch rather than aborting
everything.

## Verification performed

Every feature above was tested with real execution, not just written and assumed to
work — this caught several real bugs along the way (an ffmpeg filter syntax issue, a
missing libass dependency, Hugging Face's Xet backend failing on an unstable network
connection, a retired Groq model name, and a MediaPipe/matplotlib/macOS
incompatibility that led to switching to OpenCV for face detection):

- Face-tracked crop: computed crop offset confirmed different from plain-center
  (100px vs 92px on a test frame) and visually confirmed centered on the actual face
- Karaoke captions: visually confirmed the highlight sweeps word-by-word in sync
  with speech across three extracted frames
- Groq vs. keyword quality: real side-by-side test where Groq caught a paraphrased
  topic reference keyword matching missed entirely
- Campaign profiles: saved a profile, loaded it in a separate run, confirmed
  identical results
- Bilingual transcription: real synthetic EN/ID speech (macOS `say -v Damayanti`)
  transcribed correctly across a pure-Indonesian sentence, a code-switched sentence,
  and a mostly-English sentence
- Full regression: re-ran the original Phase 1 test video after all Phase 2 changes,
  confirmed no breakage
