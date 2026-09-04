"""API-level tests for api.py, using FastAPI's TestClient.

Covers request validation, job/clip lookup (404s), and endpoint logic without
needing real video processing — make_clip is mocked out for endpoints that
would otherwise shell out to ffmpeg on a real video file, since the pipeline
itself (download/transcribe/render) is already covered by real-execution
testing every session, not by this suite. What's missing before this file is
any *automated* coverage of api.py at all (20+ endpoints, previously verified
only by hand via curl each session) — this doesn't replace that real-execution
testing, it catches regressions in the request/response contract between
sessions.
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

import api
import profiles as profiles_module


@pytest.fixture
def client(tmp_path, monkeypatch):
    work_dir = tmp_path / "work"
    output_dir = tmp_path / "output"
    failed_dir = output_dir / "_dev_failed"
    work_dir.mkdir()
    output_dir.mkdir()
    failed_dir.mkdir()
    monkeypatch.setattr(api, "WORK_DIR", str(work_dir))
    monkeypatch.setattr(api, "OUTPUT_DIR", str(output_dir))
    monkeypatch.setattr(api, "FAILED_DIR", str(failed_dir))
    monkeypatch.setattr(profiles_module, "_PROFILES_PATH", str(tmp_path / "campaigns.json"))
    api.JOBS.clear()
    yield TestClient(api.app)
    api.JOBS.clear()


def _fake_result_meta(crop_center_frac=0.5, crop_segments=None, caption_lines=None):
    return {
        "path": "unused",
        "crop_center_frac": crop_center_frac,
        "crop_segments": crop_segments or [{"start": 0.0, "end": 10.0, "crop_center_frac": crop_center_frac}],
        "caption_lines": caption_lines if caption_lines is not None else [{"text": "hello world", "start": 0.0, "end": 1.0}],
    }


def _insert_fake_job(job_id, video_path="/fake/video.mp4", clips=None, extra=None):
    job = {
        "id": job_id,
        "stage": "done",
        "video_path": video_path,
        "video_ready": True,
        "words": [],
        "profile": api.CampaignProfile(),
        "clips": clips or [],
        "next_manual_index": api.MANUAL_INDEX_BASE,
        "lock": __import__("threading").Lock(),
        "created_at": time.time(),
    }
    if extra:
        job.update(extra)
    api.JOBS[job_id] = job
    return job


def _fake_clip(index=0, start=0.0, end=10.0, crop_center_frac=0.5, filename="fake_clip0.mp4"):
    return {
        "index": index, "start": start, "end": end, "duration": end - start,
        "text": "elephant talk", "reason": "test", "score": 5.0,
        "compliance": {"passed": True, "issues": []},
        "clip_filename": filename,
        "crop_center_frac": crop_center_frac,
        "crop_segments": [{"start": 0.0, "end": end - start, "crop_center_frac": crop_center_frac}],
        "caption_lines": [{"text": "elephant talk", "start": 0.0, "end": 1.0}],
    }


# --- 404 / not-found handling ---

def test_get_job_not_found(client):
    res = client.get("/api/jobs/does-not-exist")
    assert res.status_code == 404


def test_trim_job_not_found(client):
    res = client.post("/api/clips/does-not-exist/0/trim", json={"start": 0, "end": 5})
    assert res.status_code == 404


def test_trim_clip_not_found(client):
    _insert_fake_job("job1", clips=[])
    res = client.post("/api/clips/job1/0/trim", json={"start": 0, "end": 5})
    assert res.status_code == 404


def test_trim_end_before_start(client):
    _insert_fake_job("job1", clips=[_fake_clip()])
    res = client.post("/api/clips/job1/0/trim", json={"start": 5, "end": 1})
    assert res.status_code == 400


def test_reposition_invalid_frac(client):
    _insert_fake_job("job1", clips=[_fake_clip()])
    res = client.post("/api/clips/job1/0/reposition", json={"crop_center_frac": 1.5})
    assert res.status_code == 400


def test_manual_clip_video_not_ready(client):
    api.JOBS["job1"] = {"id": "job1", "stage": "queued", "lock": __import__("threading").Lock()}
    res = client.post("/api/jobs/job1/manual-clip", json={"start": 0, "end": 5})
    assert res.status_code == 400


def test_manual_clip_end_before_start(client):
    _insert_fake_job("job1")
    res = client.post("/api/jobs/job1/manual-clip", json={"start": 5, "end": 1})
    assert res.status_code == 400


# --- crop-segments validation ---

def test_crop_segments_gap_rejected(client):
    _insert_fake_job("job1", clips=[_fake_clip(end=10.0)])
    res = client.post("/api/clips/job1/0/crop-segments", json={
        "segments": [
            {"start": 0.0, "end": 4.0, "crop_center_frac": 0.5},
            {"start": 5.0, "end": 10.0, "crop_center_frac": 0.5},
        ]
    })
    assert res.status_code == 400
    assert "contiguous" in res.json()["detail"]


def test_crop_segments_missing_coverage_rejected(client):
    _insert_fake_job("job1", clips=[_fake_clip(end=10.0)])
    res = client.post("/api/clips/job1/0/crop-segments", json={
        "segments": [{"start": 0.0, "end": 5.0, "crop_center_frac": 0.5}]
    })
    assert res.status_code == 400
    assert "cover" in res.json()["detail"]


def test_crop_segments_invalid_frac_rejected(client):
    _insert_fake_job("job1", clips=[_fake_clip(end=10.0)])
    res = client.post("/api/clips/job1/0/crop-segments", json={
        "segments": [{"start": 0.0, "end": 10.0, "crop_center_frac": 2.0}]
    })
    assert res.status_code == 400


def test_crop_segments_valid_applies_and_updates_clip(client):
    clip = _fake_clip(end=10.0)
    job = _insert_fake_job("job1", clips=[clip])
    with patch.object(api, "make_clip", return_value=_fake_result_meta(crop_center_frac=0.9)):
        res = client.post("/api/clips/job1/0/crop-segments", json={
            "segments": [
                {"start": 0.0, "end": 5.0, "crop_center_frac": 0.2},
                {"start": 5.0, "end": 10.0, "crop_center_frac": 0.9},
            ]
        })
    assert res.status_code == 200
    body = res.json()
    assert len(body["crop_segments"]) == 1  # mocked make_clip's return, not an echo of input
    assert job["clips"][0]["crop_center_frac"] == 0.9


# --- manual clip + trim, with make_clip mocked ---

def test_manual_clip_success(client):
    job = _insert_fake_job("job1")
    with patch.object(api, "make_clip", return_value=_fake_result_meta()):
        res = client.post("/api/jobs/job1/manual-clip", json={"start": 1.0, "end": 6.0})
    assert res.status_code == 200
    body = res.json()
    assert body["manual"] is True
    assert body["index"] >= api.MANUAL_INDEX_BASE
    assert len(job["clips"]) == 1


def test_manual_clip_indices_never_collide_across_calls(client):
    _insert_fake_job("job1")
    with patch.object(api, "make_clip", return_value=_fake_result_meta()):
        r1 = client.post("/api/jobs/job1/manual-clip", json={"start": 1.0, "end": 6.0})
        r2 = client.post("/api/jobs/job1/manual-clip", json={"start": 6.0, "end": 11.0})
    assert r1.json()["index"] != r2.json()["index"]


def test_trim_preserves_manual_crop_override(client):
    # The clip's existing crop (whether a single position or, as here, a
    # crop_segments list) must be threaded through on re-render, rescaled to the
    # new range — not silently dropped/reset to some default.
    clip = _fake_clip(crop_center_frac=0.77, end=10.0)
    _insert_fake_job("job1", clips=[clip])
    with patch.object(api, "make_clip", return_value=_fake_result_meta(crop_center_frac=0.77)) as mock_make:
        res = client.post("/api/clips/job1/0/trim", json={"start": 1.0, "end": 8.0})
    assert res.status_code == 200
    passed_segments = mock_make.call_args.kwargs.get("crop_segments")
    assert passed_segments is not None
    assert all(s["crop_center_frac"] == 0.77 for s in passed_segments)


def test_trim_falls_back_to_single_crop_when_new_range_shares_no_overlap(client):
    # An old crop segment covering [0, 10] has zero overlap with a trim to
    # [50, 55] (e.g. the user picked a totally different part of a much longer
    # clip that had been trimmed before) — must fall back to a single position
    # instead of silently producing an empty/invalid crop_segments list.
    clip = _fake_clip(crop_center_frac=0.3, end=10.0)
    _insert_fake_job("job1", clips=[clip])
    with patch.object(api, "make_clip", return_value=_fake_result_meta(crop_center_frac=0.3)) as mock_make:
        res = client.post("/api/clips/job1/0/trim", json={"start": 50.0, "end": 55.0})
    assert res.status_code == 200
    assert mock_make.call_args.kwargs.get("crop_segments") is None
    assert mock_make.call_args.kwargs.get("crop_center_frac") == 0.3


def test_edit_captions_rechecks_hashtag_compliance(client):
    clip = _fake_clip(end=10.0)
    profile = api.CampaignProfile(required_hashtag="#test")
    job = _insert_fake_job("job1", clips=[clip], extra={"profile": profile})
    with patch.object(api, "make_clip", return_value=_fake_result_meta(
        caption_lines=[{"text": "check out #test today", "start": 0.0, "end": 1.0}]
    )):
        res = client.post("/api/clips/job1/0/captions", json={
            "lines": [{"text": "check out #test today", "start": 0.0, "end": 1.0}]
        })
    assert res.status_code == 200
    assert res.json()["compliance"]["passed"] is True
    assert job["clips"][0]["compliance"]["passed"] is True


# --- profiles ---

def test_profile_save_list_delete_roundtrip(client):
    res = client.post("/api/profiles", json={
        "name": "test-profile", "topics": ["a", "b"], "min_duration": 5, "max_duration": 30, "hashtag": "#x",
    })
    assert res.status_code == 200

    res = client.get("/api/profiles")
    assert "test-profile" in res.json()

    res = client.delete("/api/profiles/test-profile")
    assert res.status_code == 200

    res = client.get("/api/profiles")
    assert "test-profile" not in res.json()


def test_delete_nonexistent_profile_404(client):
    res = client.delete("/api/profiles/does-not-exist")
    assert res.status_code == 404


# --- maintenance ---

def test_maintenance_stats_empty(client):
    res = client.get("/api/maintenance/stats")
    assert res.status_code == 200
    body = res.json()
    assert body["source_videos"]["count"] == 0
    assert body["rendered_clips"]["count"] == 0


def test_maintenance_cleanup_removes_old_finished_job(client):
    job = _insert_fake_job("old-job", video_path=None, clips=[])
    job["created_at"] = time.time() - 999999  # long past any retention window
    res = client.post("/api/maintenance/cleanup?max_age_hours=24")
    assert res.status_code == 200
    assert res.json()["jobs_removed"] == 1
    assert "old-job" not in api.JOBS


def test_maintenance_cleanup_keeps_fresh_job(client):
    _insert_fake_job("fresh-job", video_path=None, clips=[])
    res = client.post("/api/maintenance/cleanup?max_age_hours=24")
    assert res.status_code == 200
    assert "fresh-job" in api.JOBS


# --- download-all zip ---

def test_download_all_no_clips_rejected(client):
    _insert_fake_job("job1", clips=[])
    res = client.get("/api/jobs/job1/download-all")
    assert res.status_code == 400


def test_download_all_job_not_found(client):
    res = client.get("/api/jobs/does-not-exist/download-all")
    assert res.status_code == 404


def test_download_all_zips_existing_clip_files(client, tmp_path):
    out_path = os.path.join(str(api.OUTPUT_DIR), "clip0.mp4")
    with open(out_path, "wb") as f:
        f.write(b"fake video bytes")
    _insert_fake_job("job1", clips=[_fake_clip(filename="clip0.mp4")])

    res = client.get("/api/jobs/job1/download-all")
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/zip"

    import zipfile, io
    zf = zipfile.ZipFile(io.BytesIO(res.content))
    assert "clip0.mp4" in zf.namelist()
    assert zf.read("clip0.mp4") == b"fake video bytes"


# --- filename safety ---

def test_get_clip_video_rejects_path_traversal(client):
    res = client.get("/api/video/clip/..%2F..%2Fetc%2Fpasswd")
    assert res.status_code in (400, 404)  # either is acceptable — must not 200


def test_get_clip_video_not_found(client):
    res = client.get("/api/video/clip/does-not-exist.mp4")
    assert res.status_code == 404


def test_get_clip_video_sends_attachment_disposition(client):
    """The frontend's <a download> link only works same-origin — cross-origin
    (5173 vs 8000), the browser ignores the HTML `download` attribute entirely.
    Content-Disposition: attachment forces the download regardless of origin,
    so this header is the actual fix, not an incidental detail.
    """
    out_path = os.path.join(str(api.OUTPUT_DIR), "dl_test.mp4")
    with open(out_path, "wb") as f:
        f.write(b"fake video bytes")
    res = client.get("/api/video/clip/dl_test.mp4")
    assert res.status_code == 200
    assert "attachment" in res.headers["content-disposition"]
    assert "dl_test.mp4" in res.headers["content-disposition"]


# --- social publishing ---

def test_social_status_reports_disconnected_by_default(client, monkeypatch):
    monkeypatch.setattr(api.youtube_upload, "TOKEN_PATH", "/nonexistent/youtube_token.json")
    monkeypatch.setattr(api.tiktok_upload, "TOKEN_PATH", "/nonexistent/tiktok_token.json")
    res = client.get("/api/social/status")
    assert res.status_code == 200
    assert res.json() == {"youtube_connected": False, "tiktok_connected": False}


def test_publish_youtube_clip_not_found(client):
    _insert_fake_job("job1", clips=[])
    res = client.post("/api/clips/job1/0/publish/youtube", json={"title": "t"})
    assert res.status_code == 404


def test_publish_youtube_not_connected_returns_400(client, monkeypatch):
    out_path = os.path.join(str(api.OUTPUT_DIR), "clip0.mp4")
    with open(out_path, "wb") as f:
        f.write(b"fake video bytes")
    _insert_fake_job("job1", clips=[_fake_clip(filename="clip0.mp4")])

    def _raise(*a, **kw):
        raise api.youtube_upload.YouTubeNotConnected("not connected")
    monkeypatch.setattr(api.youtube_upload, "upload_video", _raise)

    res = client.post("/api/clips/job1/0/publish/youtube", json={"title": "t"})
    assert res.status_code == 400


def test_publish_youtube_success(client, monkeypatch):
    out_path = os.path.join(str(api.OUTPUT_DIR), "clip0.mp4")
    with open(out_path, "wb") as f:
        f.write(b"fake video bytes")
    _insert_fake_job("job1", clips=[_fake_clip(filename="clip0.mp4")])

    calls = {}

    def _fake_upload(path, title, description, tags, privacy_status):
        calls["args"] = (path, title, description, tags, privacy_status)
        return {"video_id": "abc123", "url": "https://youtu.be/abc123"}

    monkeypatch.setattr(api.youtube_upload, "upload_video", _fake_upload)

    res = client.post("/api/clips/job1/0/publish/youtube", json={
        "title": "My Clip", "description": "desc", "tags": ["a", "b"], "privacy_status": "unlisted",
    })
    assert res.status_code == 200
    assert res.json() == {"video_id": "abc123", "url": "https://youtu.be/abc123"}
    assert calls["args"][1] == "My Clip"
    assert calls["args"][4] == "unlisted"


def test_publish_tiktok_not_connected_returns_400(client, monkeypatch):
    out_path = os.path.join(str(api.OUTPUT_DIR), "clip0.mp4")
    with open(out_path, "wb") as f:
        f.write(b"fake video bytes")
    _insert_fake_job("job1", clips=[_fake_clip(filename="clip0.mp4")])

    def _raise(*a, **kw):
        raise api.tiktok_upload.TikTokNotConnected("not connected")
    monkeypatch.setattr(api.tiktok_upload, "upload_video", _raise)

    res = client.post("/api/clips/job1/0/publish/tiktok", json={"title": "t"})
    assert res.status_code == 400


def test_publish_tiktok_success(client, monkeypatch):
    out_path = os.path.join(str(api.OUTPUT_DIR), "clip0.mp4")
    with open(out_path, "wb") as f:
        f.write(b"fake video bytes")
    _insert_fake_job("job1", clips=[_fake_clip(filename="clip0.mp4")])

    monkeypatch.setattr(
        api.tiktok_upload, "upload_video",
        lambda path, title, privacy_level, mode: {"publish_id": "pub1", "status": "SEND_TO_USER_INBOX"},
    )

    res = client.post("/api/clips/job1/0/publish/tiktok", json={"title": "My Clip"})
    assert res.status_code == 200
    assert res.json() == {"publish_id": "pub1", "status": "SEND_TO_USER_INBOX"}


def test_tiktok_authorize_requires_client_key(client, monkeypatch):
    monkeypatch.delenv("TIKTOK_CLIENT_KEY", raising=False)
    res = client.get("/api/social/tiktok/authorize")
    assert res.status_code == 400


def test_tiktok_authorize_returns_url_when_configured(client, monkeypatch):
    monkeypatch.setenv("TIKTOK_CLIENT_KEY", "fake_key")
    res = client.get("/api/social/tiktok/authorize")
    assert res.status_code == 200
    url = res.json()["authorize_url"]
    assert "fake_key" in url
    assert url.startswith("https://www.tiktok.com/v2/auth/authorize/")
