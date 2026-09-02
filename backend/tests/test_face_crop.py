"""Pure-logic tests for face_crop.py's crop-clamping math — mocks find_face_center_x
so no real video file or OpenCV detection is needed in the test run.
"""
import sys
import os
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import face_crop


def test_crop_centers_on_detected_face():
    with patch.object(face_crop, "find_face_center_x", return_value=200.0):
        crop_x = face_crop.compute_crop_x("fake.mp4", 0.0, 5.0, source_width=640, target_width=200)
    # Face at x=200, target_width=200 -> crop should start at 200 - 100 = 100
    assert crop_x == 100


def test_crop_falls_back_to_center_when_no_face_found():
    with patch.object(face_crop, "find_face_center_x", return_value=None):
        crop_x = face_crop.compute_crop_x("fake.mp4", 0.0, 5.0, source_width=640, target_width=200)
    # No face -> center of 640 is 320, crop starts at 320 - 100 = 220
    assert crop_x == 220


def test_crop_clamps_to_left_edge():
    """Face very close to the left edge shouldn't push the crop window off-frame."""
    with patch.object(face_crop, "find_face_center_x", return_value=10.0):
        crop_x = face_crop.compute_crop_x("fake.mp4", 0.0, 5.0, source_width=640, target_width=200)
    assert crop_x == 0  # clamped, not negative


def test_crop_clamps_to_right_edge():
    """Face very close to the right edge shouldn't push the crop window past the frame."""
    with patch.object(face_crop, "find_face_center_x", return_value=630.0):
        crop_x = face_crop.compute_crop_x("fake.mp4", 0.0, 5.0, source_width=640, target_width=200)
    assert crop_x == 640 - 200  # clamped to the max valid left-edge position


def test_crop_x_never_negative_or_out_of_bounds_across_range():
    """Sweep face position across the whole frame width; crop_x must always stay valid."""
    for face_x in range(-50, 700, 25):
        with patch.object(face_crop, "find_face_center_x", return_value=float(face_x)):
            crop_x = face_crop.compute_crop_x("fake.mp4", 0.0, 5.0, source_width=640, target_width=200)
        assert 0 <= crop_x <= 640 - 200


def test_manual_center_x_overrides_face_detection():
    """A manual override (0.0-1.0 fraction) should be used directly, skipping
    find_face_center_x entirely — this is what the UI's crop-reposition slider drives.
    """
    with patch.object(face_crop, "find_face_center_x", return_value=200.0) as mock_find:
        # manual fraction 0.5 of a 640-wide frame -> center_x = 320 -> crop_x = 220
        crop_x = face_crop.compute_crop_x(
            "fake.mp4", 0.0, 5.0, source_width=640, target_width=200, manual_center_x=0.5
        )
    assert crop_x == 220
    mock_find.assert_not_called()


def test_largest_cluster_mean_picks_dominant_face_not_average():
    """The real bug this fixes: two distinct speakers' x-centers should NOT be
    averaged into the empty gap between them — the more-consistently-detected one
    (larger cluster) should win instead.
    """
    # Speaker A around x=100 (3 samples), speaker B around x=500 (2 samples).
    centers = [95.0, 100.0, 105.0, 495.0, 505.0]
    result = face_crop._largest_cluster_mean(centers, frame_width=640)
    assert 90 <= result <= 110  # picks speaker A's cluster, not the ~300 midpoint


def test_largest_cluster_mean_single_cluster_behaves_like_average():
    centers = [198.0, 200.0, 202.0]
    result = face_crop._largest_cluster_mean(centers, frame_width=640)
    assert result == 200.0


# --- Shot-boundary detection (_boundaries_from_presence_samples) ---
# Fixtures below are the exact (t, has_face) sequences recorded from two real
# calibration videos, at 1s sampling — not invented data. They're what drove the
# threshold choices (min_run_samples=3) in detect_shot_boundaries, and pin down
# the real, visually-confirmed correct answer for each: zero boundaries for a
# genuinely continuous single shot, and exactly one boundary for a clip that
# really does cut from a no-face wide shot into a face-visible close-up.

_CONTINUOUS_SHOT_SAMPLES = [
    (0.0, True), (1.0, True), (2.0, True), (3.0, True), (4.0, False), (5.0, True),
    (6.0, True), (7.0, True), (8.0, True), (9.0, True), (10.0, True), (11.0, True),
    (12.0, True), (13.0, True), (14.0, True), (15.0, False), (16.0, False),
    (17.0, True), (18.0, True),
]

_REAL_CUT_SAMPLES = [
    (153.4, False), (154.4, False), (155.4, False), (156.4, False), (157.4, False),
    (158.4, True), (159.4, True), (160.4, True), (161.4, True), (162.4, True),
    (163.4, True), (164.4, True), (165.4, True), (166.4, True), (167.4, False),
    (168.4, False), (169.4, True), (170.4, True), (171.4, True), (172.4, False),
    (173.4, True), (174.4, True), (175.4, False), (176.4, True), (177.4, True),
]


def test_boundaries_ignore_single_sample_flicker_in_continuous_shot():
    """A real continuous handheld shot with brief 1-2 sample face-detection
    dropouts (someone turning their head) must produce zero boundaries — this is
    the exact case that broke a naive raw-pixel-diff and a naive 1-sample-debounce
    approach during development.
    """
    assert face_crop._boundaries_from_presence_samples(_CONTINUOUS_SHOT_SAMPLES) == []


def test_boundaries_detect_real_wide_shot_to_closeup_cut():
    """A clip that genuinely cuts from a sustained no-face wide shot into a
    sustained face-visible close-up must produce exactly one boundary at the
    transition, ignoring the shorter (2-sample) face-detection dropouts later in
    the close-up portion that are detector noise, not real cuts.
    """
    assert face_crop._boundaries_from_presence_samples(_REAL_CUT_SAMPLES) == [158.4]


def test_boundaries_empty_or_single_sample_returns_nothing():
    assert face_crop._boundaries_from_presence_samples([]) == []
    assert face_crop._boundaries_from_presence_samples([(0.0, True)]) == []


def test_boundaries_min_run_samples_is_tunable():
    """Lowering min_run_samples should surface the 2-sample dropout that the
    default (3) correctly treats as noise — confirms the parameter actually
    controls sensitivity rather than being dead code.
    """
    boundaries = face_crop._boundaries_from_presence_samples(_REAL_CUT_SAMPLES, min_run_samples=2)
    assert 158.4 in boundaries
    assert len(boundaries) > 1


# --- compute_crop_segments ---

def test_compute_crop_segments_manual_passthrough():
    """A manually-supplied segment list is returned as-is, no auto-detection run."""
    manual = [{"start": 0.0, "end": 5.0, "crop_center_frac": 0.3},
              {"start": 5.0, "end": 10.0, "crop_center_frac": 0.7}]
    with patch.object(face_crop, "detect_shot_boundaries") as mock_detect:
        result = face_crop.compute_crop_segments(
            "fake.mp4", 0.0, 10.0, source_width=640, target_width=360, manual_segments=manual
        )
    assert result == manual
    mock_detect.assert_not_called()


def test_compute_crop_segments_no_cuts_falls_back_to_single_segment():
    """Zero detected boundaries must produce exactly one segment spanning the
    whole clip — identical to the pre-existing single-crop behavior, so a clean
    single-shot clip incurs no extra encode/concat overhead.
    """
    with patch.object(face_crop, "detect_shot_boundaries", return_value=[]), \
         patch.object(face_crop, "compute_crop_x", return_value=100):
        result = face_crop.compute_crop_segments(
            "fake.mp4", 10.0, 20.0, source_width=640, target_width=360
        )
    assert len(result) == 1
    assert result[0]["start"] == 0.0
    assert result[0]["end"] == 10.0


def test_compute_crop_segments_splits_at_detected_boundary():
    """A single detected boundary must produce exactly two clip-relative segments,
    each with its own independently-computed crop position.
    """
    with patch.object(face_crop, "detect_shot_boundaries", return_value=[15.0]), \
         patch.object(face_crop, "compute_crop_x", side_effect=[50, 250]):
        result = face_crop.compute_crop_segments(
            "fake.mp4", 10.0, 20.0, source_width=640, target_width=360
        )
    assert len(result) == 2
    assert result[0]["start"] == 0.0 and result[0]["end"] == 5.0
    assert result[1]["start"] == 5.0 and result[1]["end"] == 10.0
