# Auto Video Clipper — MVP

Paste a YouTube URL, get compliance-checked vertical clips out. Built for competing
in paid clipping campaigns (Whop/Evangelist-style — e.g. Lovable Clipping).

## What this MVP does (Phase 1 of the full plan)

1. Downloads the source video (`yt-dlp`)
2. Transcribes it bilingually, EN/ID, with word-level timestamps (`faster-whisper`,
   large-v3-turbo model)
3. Finds candidate clips two ways:
   - If `GROQ_API_KEY` is set: asks Groq's free-tier LLM which segments discuss your
     topic (better recall, catches paraphrases)
   - Otherwise: falls back to plain keyword matching (zero setup, always works)
4. Cuts each candidate, center-crops to 9:16, burns in captions, exports to `output/`
5. Checks each clip against your campaign's rules (min/max duration, required
   hashtag) and reports pass/fail before you submit anywhere

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

Optional — for better topic-relevance detection, get a free Groq API key at
console.groq.com and export it:

```bash
export GROQ_API_KEY="your-key-here"
```

Without it, the tool still works using keyword matching instead.

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

Clips land in `output/`, named `<video_id>_clip1.mp4`, `_clip2.mp4`, etc.

## What's simplified vs. the full plan (for now)

- **Crop is a simple center-crop**, not the face-tracked MediaPipe crop from the full
  plan. Good enough to validate the pipeline; face-tracking is the next upgrade.
- **Captions are plain burned-in text**, not word-by-word karaoke-style highlighting.
- **No campaign-profile save/reuse UI yet** — pass campaign rules as CLI flags each run.
- **No React frontend yet** — this is a CLI tool for now, to get the core AI pipeline
  proven before building UI on top of it.

These are exactly the "Phase 2+" items from the plan (`~/.claude/plans/im-thinking-to-
bump-fluttering-eagle.md`) — the MVP goal was proving the mechanical pipeline
(download → transcribe → detect → cut → caption → validate) works end to end first.
