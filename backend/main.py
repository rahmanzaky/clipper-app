"""Auto Video Clipper — CLI MVP.

Usage:
    python main.py --url <youtube_url> --topic "Lovable" --topic "Anton" \\
        --min-duration 15 --max-duration 60 --hashtag "#LovablePartner"
"""
import argparse
import os
import sys

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from downloader import download_video
from transcriber import transcribe
from detector import detect_highlights
from clipper import make_clip
from compliance import CampaignProfile, check_clip
from profiles import load_profile, save_profile

WORK_DIR = os.path.join(os.path.dirname(__file__), "..", "work")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "output")


def main():
    parser = argparse.ArgumentParser(description="Auto Video Clipper MVP")
    parser.add_argument("--url", required=True, help="YouTube video URL")
    parser.add_argument("--topic", action="append", default=[],
                         help="Topic keyword/person to find (repeatable)")
    parser.add_argument("--min-duration", type=float, default=8.0)
    parser.add_argument("--max-duration", type=float, default=60.0)
    parser.add_argument("--hashtag", default="", help="Required hashtag to check for")
    parser.add_argument("--profile", default=None,
                         help="Load a saved campaign profile by name (from campaigns.json)")
    parser.add_argument("--save-profile", default=None,
                         help="Save the given --topic/--hashtag/--min-duration/--max-duration flags under this name")
    args = parser.parse_args()

    if args.profile:
        saved = load_profile(args.profile)
        topics = saved["topics"]
        min_duration = saved["min_duration"]
        max_duration = saved["max_duration"]
        hashtag = saved["hashtag"]
        print(f"[profile] Loaded '{args.profile}': topics={topics}, "
              f"duration={min_duration}-{max_duration}s, hashtag={hashtag or '(none)'}")
    else:
        topics = args.topic
        min_duration = args.min_duration
        max_duration = args.max_duration
        hashtag = args.hashtag

    if args.save_profile:
        save_profile(args.save_profile, topics, min_duration, max_duration, hashtag)
        print(f"[profile] Saved current settings as '{args.save_profile}'")

    profile = CampaignProfile(
        topics=topics,
        min_duration=min_duration,
        max_duration=max_duration,
        required_hashtag=hashtag,
    )

    print(f"[1/4] Downloading: {args.url}")
    video_path = download_video(args.url, WORK_DIR)
    print(f"      -> {video_path}")

    print("[2/4] Transcribing (bilingual EN/ID, this may take a while)...")
    segments = transcribe(video_path)
    print(f"      -> {len(segments)} segments")

    print(f"[3/4] Detecting highlights (topics: {topics or 'general'})...")
    candidates = detect_highlights(segments, topics)
    print(f"      -> {len(candidates)} candidate clips found, ranked best-first")

    if not candidates:
        print("No candidate clips found. Try different --topic keywords or check the transcript.")
        sys.exit(0)

    all_words = [w for seg in segments for w in seg.words]

    print("[4/4] Cutting, cropping to 9:16, burning captions, checking compliance...")
    base = os.path.splitext(os.path.basename(video_path))[0]
    for i, cand in enumerate(candidates):
        out_path = os.path.join(OUTPUT_DIR, f"{base}_clip{i+1}.mp4")
        make_clip(video_path, cand.start, cand.end, all_words, out_path)
        result = check_clip(cand.start, cand.end, cand.text, profile)
        status = "PASS" if result.passed else "FAIL"
        print(f"\n  Clip {i+1} [score {cand.score:.1f}]: {cand.start:.1f}s - {cand.end:.1f}s ({cand.reason})")
        print(f"    -> {out_path}")
        print(f"    Compliance: {status}")
        for issue in result.issues:
            print(f"      - {issue}")

    print(f"\nDone. {len(candidates)} clip(s) in {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
