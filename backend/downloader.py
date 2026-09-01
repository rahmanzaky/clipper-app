"""Download a YouTube video to a local file via yt-dlp."""
import os
import yt_dlp

from retry import retry_with_backoff


def _do_download(url: str, ydl_opts: dict) -> str:
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        path = ydl.prepare_filename(info)
        base, _ = os.path.splitext(path)
        mp4_path = base + ".mp4"
        return mp4_path if os.path.exists(mp4_path) else path


def download_video(url: str, output_dir: str, progress_callback=None) -> str:
    """Download url (YouTube, or a public/shared Google Drive video link — yt-dlp's
    Google Drive extractor handles those with no extra code needed here) to
    output_dir. progress_callback, if given, is called with {"percent": float} as
    the download proceeds — lets a caller (the web API) surface a real progress bar
    instead of a static "downloading" label.
    """
    os.makedirs(output_dir, exist_ok=True)
    outtmpl = os.path.join(output_dir, "%(id)s.%(ext)s")
    ydl_opts = {
        "outtmpl": outtmpl,
        "format": "bestvideo[height<=1080]+bestaudio/best[height<=1080]",
        "merge_output_format": "mp4",
        "quiet": True,
        "noprogress": True,
    }

    if progress_callback is not None:
        def hook(d):
            if d.get("status") != "downloading":
                return
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            downloaded = d.get("downloaded_bytes", 0)
            if total:
                progress_callback({"percent": min(99.0, downloaded / total * 100)})
        ydl_opts["progress_hooks"] = [hook]

    def on_retry(attempt, exc):
        print(f"[downloader] Download failed (attempt {attempt}/3): {exc}. Retrying...")

    try:
        path = retry_with_backoff(lambda: _do_download(url, ydl_opts), attempts=3, on_retry=on_retry)
        if progress_callback is not None:
            progress_callback({"percent": 100.0})
        return path
    except Exception as e:
        raise RuntimeError(
            f"Download failed after 3 attempts: {e}\n"
            f"Check the URL is valid and reachable, and your network connection."
        ) from e
