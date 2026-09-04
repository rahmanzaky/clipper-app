"""YouTube upload via the Data API v3's videos.insert.

OAuth-authorized via a one-time local script (scripts/setup_youtube_auth.py), not an
in-request browser flow — videos.insert needs a long-lived refresh token, and driving
a browser consent screen from inside an HTTP request handler has no clean way to
return control to that same request once the user finishes in their browser. The
one-time script produces a token file this module then reuses (refreshing silently)
for every subsequent upload.
"""
import os

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

SECRETS_DIR = os.path.join(os.path.dirname(__file__), "secrets")
TOKEN_PATH = os.path.join(SECRETS_DIR, "youtube_token.json")
CLIENT_SECRET_PATH = os.path.join(SECRETS_DIR, "client_secret.json")
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


class YouTubeNotConnected(Exception):
    pass


def is_connected() -> bool:
    return os.path.exists(TOKEN_PATH)


def _load_credentials() -> Credentials:
    if not os.path.exists(TOKEN_PATH):
        raise YouTubeNotConnected(
            "YouTube isn't connected yet. Run `python scripts/setup_youtube_auth.py` "
            "once (after placing your OAuth client_secret.json in backend/secrets/)."
        )
    creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(TOKEN_PATH, "w") as f:
            f.write(creds.to_json())
    return creds


def upload_video(video_path: str, title: str, description: str = "", tags: list = None,
                  privacy_status: str = "private", category_id: str = "22") -> dict:
    """Upload video_path to the authorized channel, return {"video_id", "url"}.

    privacy_status defaults to "private", not "public" — auto-posting straight to
    public with no human glance at the rendered result is the kind of mistake that's
    hard to undo once a platform (or a paid clipping campaign tracking the post) has
    already indexed it. The caller picks "public" explicitly per upload instead of
    that being an invisible default.
    """
    creds = _load_credentials()
    youtube = build("youtube", "v3", credentials=creds)
    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags or [],
            "categoryId": category_id,
        },
        "status": {"privacyStatus": privacy_status, "selfDeclaredMadeForKids": False},
    }
    media = MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype="video/mp4")
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        _, response = request.next_chunk()
    return {"video_id": response["id"], "url": f"https://youtu.be/{response['id']}"}
