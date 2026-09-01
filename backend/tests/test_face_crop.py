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
