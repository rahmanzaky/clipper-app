"""Face-tracked 9:16 crop.

Uses OpenCV's Haar cascade face detector (bundled model download in models/) rather
than MediaPipe: MediaPipe 1.0.1's package-level __init__ unconditionally imports a
matplotlib-based drawing helper, whose font manager crashes on this machine's macOS
version (system_profiler JSON format changed). OpenCV avoids that import chain
entirely and gives the same "find a face, center the crop on it" result for the MVP's
purposes. Revisit MediaPipe once that upstream/macOS incompatibility is resolved.
"""
import os
import cv2

_CASCADE_PATH = os.path.join(os.path.dirname(__file__), "models", "haarcascade_frontalface_default.xml")
_detector = None


def _get_detector():
    global _detector
    if _detector is None:
        _detector = cv2.CascadeClassifier(_CASCADE_PATH)
    return _detector


def find_face_center_x(video_path: str, start: float, end: float, sample_count: int = 5,
                        source_width: int = None):
    """Sample a few frames within [start, end] and return a representative detected
    face center x-coordinate (in source pixels), or None if no face was found in any
    sampled frame — caller should fall back to a plain center-crop in that case.

    Real two-speaker podcasts previously broke this: averaging every sampled face's
    x-center together blends two distinct speaker positions into the empty gap
    between them (confirmed as the actual bug from real testing, not just imprecise
    tracking). Instead, cluster the sampled centers by proximity and return the mean
    of the largest cluster — the most-consistently-detected face position, not a
    blend of multiple different faces.
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return None

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    frame_width = source_width or int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 1920
    detector = _get_detector()
    centers = []

    duration = max(end - start, 0.1)
    for i in range(sample_count):
        t = start + duration * (i + 0.5) / sample_count
        frame_idx = int(t * fps)
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ok, frame = cap.read()
        if not ok:
            continue
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = detector.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(40, 40))
        if len(faces) == 0:
            continue
        # Largest face = most likely the active speaker close to camera.
        x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
        centers.append(x + w / 2)

    cap.release()
    if not centers:
        return None
    return _largest_cluster_mean(centers, frame_width)


def _largest_cluster_mean(centers: list, frame_width: int, threshold_frac: float = 0.15) -> float:
    """Group nearby x-centers together (within threshold_frac * frame_width pixels
    of each other) and return the mean of the largest group. With a single speaker
    (or all samples landing on the same face), this is equivalent to the old
    average. With two alternating speakers, it picks whichever one was detected
    more consistently instead of splitting the difference between both.
    """
    threshold = frame_width * threshold_frac
    centers_sorted = sorted(centers)
    clusters = []
    current = [centers_sorted[0]]
    for c in centers_sorted[1:]:
        if c - current[-1] <= threshold:
            current.append(c)
        else:
            clusters.append(current)
            current = [c]
    clusters.append(current)
    best = max(clusters, key=len)
    return sum(best) / len(best)


def compute_crop_x(video_path: str, start: float, end: float, source_width: int, target_width: int,
                    manual_center_x: float = None) -> int:
    """Return the left-edge x-coordinate for a target_width-wide crop, centered on
    a manually-supplied position if given, otherwise the detected face, otherwise
    the frame center.

    manual_center_x, if given, is a 0.0-1.0 fraction of source_width (not a pixel
    value) — lets callers pass a UI slider's 0-1 position directly.
    """
    if manual_center_x is not None:
        center_x = manual_center_x * source_width
    else:
        face_x = find_face_center_x(video_path, start, end, source_width=source_width)
        center_x = face_x if face_x is not None else source_width / 2
    crop_x = int(center_x - target_width / 2)
    # Clamp so the crop window stays within the source frame.
    crop_x = max(0, min(crop_x, source_width - target_width))
    return crop_x
