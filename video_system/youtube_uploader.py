"""
YouTube uploader — OAuth2 upload to Shadow Files channel.
Credentials loaded from YOUTUBE_CLIENT_SECRET_JSON env var (base64 encoded).
"""

import logging
import os
import json
import base64
import tempfile

from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import pickle

log = logging.getLogger("video.youtube_upload")

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
TOKEN_PATH = "data/youtube_token.pkl"


def _get_youtube_service():
    creds = None

    # Load token from env var (Railway) or local file
    token_b64 = os.environ.get("YOUTUBE_TOKEN_B64", "")
    if token_b64 and not os.path.exists(TOKEN_PATH):
        os.makedirs("data", exist_ok=True)
        with open(TOKEN_PATH, "wb") as f:
            f.write(base64.b64decode("".join(token_b64.split())))

    if os.path.exists(TOKEN_PATH):
        with open(TOKEN_PATH, "rb") as f:
            creds = pickle.load(f)

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(TOKEN_PATH, "wb") as f:
            pickle.dump(creds, f)

    if not creds or not creds.valid:
        # Load client secret from env var (base64 encoded JSON)
        secret_b64 = os.environ.get("YOUTUBE_CLIENT_SECRET_B64", "")
        if not secret_b64:
            raise RuntimeError("YOUTUBE_CLIENT_SECRET_B64 env var not set")

        secret_json = base64.b64decode("".join(secret_b64.split())).decode("utf-8")
        secret_data = json.loads(secret_json)

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as tmp:
            json.dump(secret_data, tmp)
            tmp_path = tmp.name

        flow = InstalledAppFlow.from_client_secrets_file(tmp_path, SCOPES)
        creds = flow.run_local_server(port=0)
        os.unlink(tmp_path)

        with open(TOKEN_PATH, "wb") as f:
            pickle.dump(creds, f)

    return build("youtube", "v3", credentials=creds)


def upload_to_youtube(
    video_path: str,
    title: str,
    description: str,
    tags: list[str],
    thumbnail_path: str = None,
    privacy: str = "public",
) -> str:
    """
    Uploads video to YouTube.
    Returns the YouTube video ID.
    """
    log.info(f"Uploading to YouTube: {title}")
    youtube = _get_youtube_service()

    body = {
        "snippet": {
            "title":       title,
            "description": description,
            "tags":        tags,
            "categoryId":  "22",  # People & Blogs (true crime fits here)
        },
        "status": {
            "privacyStatus":           privacy,
            "selfDeclaredMadeForKids": False,
        },
    }

    media = MediaFileUpload(
        video_path,
        chunksize=50 * 1024 * 1024,  # 50MB chunks
        resumable=True,
        mimetype="video/mp4",
    )

    request = youtube.videos().insert(
        part=",".join(body.keys()),
        body=body,
        media_body=media,
    )

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            log.info(f"Upload progress: {int(status.progress() * 100)}%")

    video_id = response["id"]
    log.info(f"YouTube upload complete: https://youtube.com/watch?v={video_id}")

    if thumbnail_path and os.path.exists(thumbnail_path):
        try:
            youtube.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(thumbnail_path),
            ).execute()
            log.info(f"Thumbnail uploaded for {video_id}")
        except Exception as e:
            log.error(f"Thumbnail upload failed: {e}")

    return video_id
