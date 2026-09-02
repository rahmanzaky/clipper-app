"""Face-tracked 9:16 crop.

Uses OpenCV's Haar cascade face detector (bundled model download in models/) rather
than MediaPipe: MediaPipe 1.0.1's package-level __init__ unconditionally imports a
matplotlib-based drawing helper, whose font manager crashes on this machine's macOS
version (system_profiler JSON format changed). OpenCV avoids that import chain
entirely and gives the same "find a face, center the crop on it" result for the MVP's
purposes. Revisit MediaPipe once that upstream/macOS incompatibility is resolved.
"""
import os
import threading
import cv2

_CASCADE_PATH = os.path.join(os.path.dirname(__file__), "models", "haarcascade_frontalface_default.xml")
_thread_local = threading.local()


def _get_detector():
    """One CascadeClassifier per thread, not a single shared global instance.
    The rendering pipeline runs multiple clips concurrently via a
    ThreadPoolExecutor (api.py, RENDER_WORKERS), each calling detectMultiScale on
    whatever this returns — OpenCV's CascadeClassifier isn't documented as safe
    for concurrent detectMultiScale calls from multiple threads on one shared
    instance, and constructing a new one from the (small, local) XML file is cheap
    enough that there's no reason to risk it.
    """
    if not hasattr(_thread_local, "detector"):
        _thread_local.detector = cv2.CascadeClassifier(_CASCADE_PATH)
    return _thread_local.detector


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


def detect_shot_boundaries(video_path: str, start: float, end: float,
                            sample_interval: float = 1.0, min_run_samples: int = 3) -> list:
    """Find framing-change timestamps within [start, end] by sampling face presence
    (reusing the same Haar cascade as find_face_center_x) at a regular interval and
    flagging sustained transitions between "a face is visible" and "no face is
    visible."

    Two other approaches were tried first and rejected, calibrated against real
    footage rather than assumed to work:
    - Raw grayscale pixel-difference: flagged 7 false boundaries on a real
      continuous handheld-camera clip with zero actual cuts — ordinary camera
      motion shifts enough pixels to look like a cut.
    - HSV color-histogram correlation: correctly ignored that same motion, but on
      a real problem clip (a two-camera podcast cut between a wide two-shot and a
      speaker close-up) it never dropped below 0.97 correlation anywhere — the
      wide shot and the close-up share the same studio lighting/backdrop/skin
      tones, so the overall color palette barely changes even though the framing
      is completely different. Color alone can't see a same-set camera-angle cut.

    Directly sampling face presence doesn't share that blind spot: this exact
    problem clip has a real 4-second stretch with *no* face detected at all (a
    wide two-shot) followed by a stretch where a face is consistently detected (a
    close-up) — a presence-based comparison catches that transition where
    color-based comparison couldn't.

    Raw per-sample presence is noisy on its own, though — a real continuous shot
    of someone moving/turning naturally produces occasional single-sample "no
    face" blips that are not real cuts (confirmed: naive sample-to-sample
    comparison, even with a lookahead debounce, still produced several false
    boundaries on both real calibration clips). This is handled by run-length
    smoothing: raw presence is collapsed into runs, and any run shorter than
    min_run_samples is discarded (absorbed into whichever state came before it) —
    a real segment (wide shot or close-up) lasts several seconds, so this removes
    detector flicker without erasing genuine transitions.
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return []

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    detector = _get_detector()
    duration = max(end - start, 0.1)
    num_samples = max(1, int(duration / sample_interval))

    samples = []  # (t, has_face)
    for i in range(num_samples + 1):
        t = start + i * sample_interval
        if t > end:
            break
        frame_idx = int(t * fps)
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ok, frame = cap.read()
        if not ok:
            continue
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = detector.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(40, 40))
        samples.append((t, len(faces) > 0))
    cap.release()

    return _boundaries_from_presence_samples(samples, min_run_samples)


def _boundaries_from_presence_samples(samples: list, min_run_samples: int = 3) -> list:
    """Pure run-length-smoothing logic behind detect_shot_boundaries, split out so
    it can be unit-tested against synthetic (t, has_face) sequences directly,
    without needing a real video file or a mocked cv2.VideoCapture.

    Collapses raw presence samples into runs, drops any run shorter than
    min_run_samples by absorbing it into the previous run (a lone detector blip
    vanishes instead of creating a spurious boundary), and returns the start time
    of every run after the first.
    """
    if len(samples) < 2:
        return []

    runs = []  # [has_face, start_idx, end_idx]
    cur_state, run_start = samples[0][1], 0
    for i in range(1, len(samples)):
        if samples[i][1] != cur_state:
            runs.append([cur_state, run_start, i - 1])
            cur_state, run_start = samples[i][1], i
    runs.append([cur_state, run_start, len(samples) - 1])

    cleaned = []
    for run in runs:
        length = run[2] - run[1] + 1
        if length < min_run_samples and cleaned:
            cleaned[-1][2] = run[2]  # absorb this blip into the previous run
        else:
            cleaned.append(list(run))
    # A second pass in case absorbing blips left adjacent runs with the same state.
    final_runs = []
    for run in cleaned:
        if final_runs and final_runs[-1][0] == run[0]:
            final_runs[-1][2] = run[2]
        else:
            final_runs.append(run)

    # The backward-absorption loop above can't merge a short run into "the
    # previous run" when it IS the first run — there's nothing before it. Merge
    # it forward into the run that follows instead, or it survives as a spurious
    # boundary right at the start of the clip (the opposite of what run-length
    # smoothing is for).
    if len(final_runs) > 1 and (final_runs[0][2] - final_runs[0][1] + 1) < min_run_samples:
        final_runs[1][1] = final_runs[0][1]
        final_runs = final_runs[1:]

    return [samples[run[1]][0] for run in final_runs[1:]]


def compute_crop_segments(video_path: str, start: float, end: float, source_width: int,
                           target_width: int, manual_segments: list = None) -> list:
    """Return a list of {"start", "end", "crop_center_frac"} dicts (clip-relative
    seconds, i.e. 0..duration) describing the crop to use across the clip's timeline.

    If manual_segments is given (from the frontend's segment editor), it's returned
    as-is — the caller has already validated it covers [0, duration] with no gaps.
    Otherwise, shot boundaries are auto-detected and each resulting sub-range gets
    its own auto-computed crop position (reusing compute_crop_x's existing face
    detection + clustering, just scoped to that sub-range instead of the whole
    clip). Zero detected cuts collapses to a single segment covering the whole
    clip — identical to the pre-existing single-crop behavior, at the cost of one
    cheap boundary-detection pass.
    """
    if manual_segments is not None:
        return manual_segments

    boundaries = detect_shot_boundaries(video_path, start, end)
    bounds = [start] + sorted(boundaries) + [end]
    segments = []
    for seg_start, seg_end in zip(bounds[:-1], bounds[1:]):
        if seg_end - seg_start < 0.05:
            continue  # boundary landed right at a segment edge — skip a near-zero sliver
        crop_x = compute_crop_x(video_path, seg_start, seg_end, source_width, target_width)
        crop_center_frac = (crop_x + target_width / 2) / source_width
        segments.append({
            "start": seg_start - start,
            "end": seg_end - start,
            "crop_center_frac": crop_center_frac,
        })
    if not segments:
        # Every candidate sub-range was a sliver (pathological/very short clip) —
        # fall back to one segment covering the whole clip rather than returning
        # nothing.
        crop_x = compute_crop_x(video_path, start, end, source_width, target_width)
        segments = [{
            "start": 0.0,
            "end": end - start,
            "crop_center_frac": (crop_x + target_width / 2) / source_width,
        }]
    return segments


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
