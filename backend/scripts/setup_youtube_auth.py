"""One-time YouTube OAuth setup.

Run this once from a real desktop browser session:

    python scripts/setup_youtube_auth.py

It opens your browser to Google's consent screen, then saves a long-lived refresh
token to backend/secrets/youtube_token.json. youtube_upload.py reuses that token
(refreshing it silently) for every upload after this — no further browser
interaction needed.

Prerequisite: backend/secrets/client_secret.json must already exist (the OAuth
client JSON downloaded from Google Cloud Console > APIs & Services > Credentials
> your "Desktop app" client).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from google_auth_oauthlib.flow import InstalledAppFlow

from youtube_upload import CLIENT_SECRET_PATH, SECRETS_DIR, SCOPES, TOKEN_PATH


def main():
    if not os.path.exists(CLIENT_SECRET_PATH):
        raise SystemExit(
            f"Missing {CLIENT_SECRET_PATH}.\n"
            "Download your OAuth client JSON from Google Cloud Console "
            "(APIs & Services > Credentials > your Desktop app client) and save it there."
        )
    os.makedirs(SECRETS_DIR, exist_ok=True)
    flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_PATH, SCOPES)
    creds = flow.run_local_server(port=0)
    with open(TOKEN_PATH, "w") as f:
        f.write(creds.to_json())
    print(f"Saved YouTube credentials to {TOKEN_PATH}. You can now upload from the app.")


if __name__ == "__main__":
    main()
