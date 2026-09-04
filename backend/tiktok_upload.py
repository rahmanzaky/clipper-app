"""TikTok upload via the Content Posting API (v2).

Two publish endpoints exist, sharing the same chunked-upload + status-poll
mechanics:
- /v2/post/publish/inbox/video/init/ — "upload to inbox." Works with just the
  video.upload scope every app gets by default, no TikTok audit needed. The video
  lands in the user's TikTok inbox as a draft; they tap Post themselves in the app.
- /v2/post/publish/video/init/ — direct-to-feed publish. Requires the video.publish
  scope, which TikTok only grants after auditing the app (a live privacy policy URL
  plus a real review, days to weeks). Until that audit passes, requesting "direct"
  mode here will be rejected by TikTok's API with a scope error — that's expected,
  not a bug in this module.

Unlike YouTube, TikTok's OAuth is a standard web authorization-code flow (not a
one-time local script) — see api.py's /api/social/tiktok/authorize and /callback
endpoints, which drive this module's build_authorize_url/exchange_code_for_token.
"""
import json
import os
import time

import requests

SECRETS_DIR = os.path.join(os.path.dirname(__file__), "secrets")
TOKEN_PATH = os.path.join(SECRETS_DIR, "tiktok_token.json")

AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
INBOX_INIT_URL = "https://open.tiktokapis.com/v2/post/publish/inbox/video/init/"
DIRECT_INIT_URL = "https://open.tiktokapis.com/v2/post/publish/video/init/"
STATUS_URL = "https://open.tiktokapis.com/v2/post/publish/status/fetch/"

CHUNK_SIZE = 10 * 1024 * 1024  # 10MB — within TikTok's allowed per-chunk range
STATUS_POLL_ATTEMPTS = 30
STATUS_POLL_INTERVAL_S = 2


class TikTokNotConnected(Exception):
    pass


def is_connected() -> bool:
    return os.path.exists(TOKEN_PATH)


def build_authorize_url(client_key: str, redirect_uri: str, state: str) -> str:
    from urllib.parse import urlencode
    params = {
        "client_key": client_key,
        "scope": "video.upload,video.publish",
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "state": state,
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def exchange_code_for_token(client_key: str, client_secret: str, code: str, redirect_uri: str) -> dict:
    resp = requests.post(
        TOKEN_URL,
        data={
            "client_key": client_key,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    resp.raise_for_status()
    data = resp.json()
    os.makedirs(SECRETS_DIR, exist_ok=True)
    with open(TOKEN_PATH, "w") as f:
        json.dump(data, f)
    return data


def _load_token() -> dict:
    if not os.path.exists(TOKEN_PATH):
        raise TikTokNotConnected("TikTok isn't connected yet — use Connect TikTok first.")
    with open(TOKEN_PATH) as f:
        return json.load(f)


def _refresh(client_key: str, client_secret: str) -> dict:
    token = _load_token()
    resp = requests.post(TOKEN_URL, data={
        "client_key": client_key,
        "client_secret": client_secret,
        "grant_type": "refresh_token",
        "refresh_token": token["refresh_token"],
    })
    resp.raise_for_status()
    data = resp.json()
    with open(TOKEN_PATH, "w") as f:
        json.dump(data, f)
    return data


def upload_video(video_path: str, title: str, privacy_level: str = "SELF_ONLY",
                  mode: str = "inbox") -> dict:
    """Upload video_path. mode="inbox" (default) needs no audit; mode="direct"
    posts straight to the feed but requires the audited video.publish scope.
    """
    token = _load_token()
    access_token = token["access_token"]
    size = os.path.getsize(video_path)
    chunk_size = min(CHUNK_SIZE, size) or size
    total_chunks = max(1, (size + chunk_size - 1) // chunk_size)

    init_url = DIRECT_INIT_URL if mode == "direct" else INBOX_INIT_URL
    body = {"source_info": {
        "source": "FILE_UPLOAD",
        "video_size": size,
        "chunk_size": chunk_size,
        "total_chunk_count": total_chunks,
    }}
    if mode == "direct":
        body["post_info"] = {"title": title, "privacy_level": privacy_level}

    resp = requests.post(init_url, json=body, headers={
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json; charset=UTF-8",
    })
    resp.raise_for_status()
    init_data = resp.json()["data"]
    publish_id = init_data["publish_id"]
    upload_url = init_data["upload_url"]

    with open(video_path, "rb") as f:
        offset = 0
        while offset < size:
            chunk = f.read(chunk_size)
            end = offset + len(chunk) - 1
            put_resp = requests.put(upload_url, data=chunk, headers={
                "Content-Type": "video/mp4",
                "Content-Range": f"bytes {offset}-{end}/{size}",
            })
            put_resp.raise_for_status()
            offset += len(chunk)

    # Poll for completion rather than returning right after the bytes are sent —
    # the API endpoint calling this wants to report a real pass/fail, not just
    # "we finished streaming the upload."
    for _ in range(STATUS_POLL_ATTEMPTS):
        status_resp = requests.post(STATUS_URL, json={"publish_id": publish_id}, headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=UTF-8",
        })
        status_resp.raise_for_status()
        status = status_resp.json()["data"]["status"]
        if status in ("PUBLISH_COMPLETE", "SEND_TO_USER_INBOX"):
            return {"publish_id": publish_id, "status": status}
        if status == "FAILED":
            raise RuntimeError(f"TikTok publish failed: {status_resp.json()['data']}")
        time.sleep(STATUS_POLL_INTERVAL_S)
    return {"publish_id": publish_id, "status": "PENDING"}
