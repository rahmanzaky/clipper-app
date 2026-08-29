"""Auto Video Clipper — CLI MVP.

Usage:
    python main.py --url <youtube_url> --topic "Lovable" --topic "Anton" \\
        --min-duration 15 --max-duration 60 --hashtag "#LovablePartner"
"""
import argparse
import os
import sys

from downloader import download_video
from transcriber import transcribe
from detector import detect_highlights
from clipper import make_clip
from compliance import CampaignProfile, check_clip

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
    args = parser.parse_args()

    profile = CampaignProfile(
        topics=args.topic,
        min_duration=args.min_duration,
        max_duration=args.max_duration,
        required_hashtag=args.hashtag,
    )

    print(f"[1/4] Downloading: {args.url}")
    video_path = download_video(args.url, WORK_DIR)
    print(f"      -> {video_path}")

    print("[2/4] Transcribing (bilingual EN/ID, this may take a while)...")
    segments = transcribe(video_path)
    print(f"      -> {len(segments)} segments")

    print(f"[3/4] Detecting highlights (topics: {args.topic or 'general'})...")
    candidates = detect_highlights(segments, args.topic)
    print(f"      -> {len(candidates)} candidate clips found")

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
        print(f"\n  Clip {i+1}: {cand.start:.1f}s - {cand.end:.1f}s ({cand.reason})")
        print(f"    -> {out_path}")
        print(f"    Compliance: {status}")
        for issue in result.issues:
            print(f"      - {issue}")

    print(f"\nDone. {len(candidates)} clip(s) in {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
