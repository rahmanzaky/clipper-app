"""Pure-logic tests for compliance.py — no network, no models."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from compliance import CampaignProfile, check_clip


def test_passes_when_within_bounds_and_hashtag_present():
    profile = CampaignProfile(min_duration=5.0, max_duration=60.0, required_hashtag="#LovablePartner")
    result = check_clip(0.0, 20.0, "check out this clip #LovablePartner", profile)
    assert result.passed
    assert result.issues == []


def test_fails_when_too_short():
    profile = CampaignProfile(min_duration=8.0, max_duration=60.0)
    result = check_clip(0.0, 5.0, "some caption", profile)
    assert not result.passed
    assert any("Too short" in issue for issue in result.issues)


def test_fails_when_too_long():
    profile = CampaignProfile(min_duration=5.0, max_duration=30.0)
    result = check_clip(0.0, 45.0, "some caption", profile)
    assert not result.passed
    assert any("Too long" in issue for issue in result.issues)


def test_fails_when_hashtag_missing():
    profile = CampaignProfile(min_duration=5.0, max_duration=60.0, required_hashtag="#LovablePartner")
    result = check_clip(0.0, 20.0, "no hashtag here", profile)
    assert not result.passed
    assert any("Missing required hashtag" in issue for issue in result.issues)


def test_hashtag_check_is_case_insensitive():
    profile = CampaignProfile(min_duration=5.0, max_duration=60.0, required_hashtag="#LovablePartner")
    result = check_clip(0.0, 20.0, "check out #lovablepartner", profile)
    assert result.passed


def test_no_required_hashtag_means_no_hashtag_check():
    profile = CampaignProfile(min_duration=5.0, max_duration=60.0, required_hashtag="")
    result = check_clip(0.0, 20.0, "anything at all", profile)
    assert result.passed


def test_multiple_issues_all_reported():
    profile = CampaignProfile(min_duration=30.0, max_duration=60.0, required_hashtag="#Required")
    result = check_clip(0.0, 5.0, "no hashtag", profile)
    assert not result.passed
    assert len(result.issues) == 2  # too short AND missing hashtag
