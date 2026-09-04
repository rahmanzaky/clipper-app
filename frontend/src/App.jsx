import { useEffect, useRef, useState } from "react";
import "./App.css";

const API = "http://127.0.0.1:8000";

// Formats a position in time as M:SS (or M:SS.s, or H:MM:SS) — raw seconds like
// "221.7s" are hard to translate to "3:41" in your head, especially for anything
// more than a minute into a long source video. Sliders still operate in raw
// seconds internally; this only changes what's displayed.
function formatTime(seconds, decimals = 1) {
  if (seconds == null || Number.isNaN(seconds)) return decimals > 0 ? "0:00.0" : "0:00";
  // Rounding h/m/s independently from the raw float (the previous approach) lets a
  // value like 59.96s round its seconds component up to "60.0" while its minutes
  // component was already floored to 0, producing the invalid "00:60.0" instead of
  // "01:00.0" (confirmed: formatTime(59.96) produced exactly that). Rounding to an
  // integer count of the smallest displayed unit FIRST, then deriving h/m/s from
  // that integer via floor division, makes the carry happen correctly and avoids
  // float-modulo imprecision entirely.
  const factor = 10 ** decimals;
  let units = Math.round(Math.max(0, seconds) * factor);
  const unitsPerSecond = factor;
  const unitsPerMinute = unitsPerSecond * 60;
  const unitsPerHour = unitsPerMinute * 60;
  const h = Math.floor(units / unitsPerHour);
  units -= h * unitsPerHour;
  const m = Math.floor(units / unitsPerMinute);
  units -= m * unitsPerMinute;
  const secStr = decimals > 0
    ? (units / unitsPerSecond).toFixed(decimals).padStart(3 + decimals, "0")
    : String(units).padStart(2, "0");
  const mStr = String(m).padStart(2, "0");
  return h > 0 ? `${h}:${mStr}:${secStr}` : `${mStr}:${secStr}`;
}

// A render-triggering request (trim/reposition/crop-segments/captions/manual-clip)
// has no client-side timeout otherwise — if ffmpeg ever genuinely hangs (a corrupt
// input, a stuck process), the UI would show its "Re-rendering..." spinner forever
// with no way out. 120s is generous enough not to false-positive on a legitimately
// slow multi-segment render.
async function fetchWithTimeout(url, options = {}, timeoutMs = 120000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } catch (e) {
    if (e.name === "AbortError") {
      throw new Error(`Request timed out after ${Math.round(timeoutMs / 1000)}s — the server may be stuck.`);
    }
    throw e;
  } finally {
    clearTimeout(timer);
  }
}

function ProcessForm({ onSubmit, onUpload, disabled }) {
  const [mode, setMode] = useState("url"); // "url" | "upload"
  const [url, setUrl] = useState("");
  const [file, setFile] = useState(null);
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef(null);
  const [topics, setTopics] = useState("");
  const [minDuration, setMinDuration] = useState(8);
  const [maxDuration, setMaxDuration] = useState(60);
  const [hashtag, setHashtag] = useState("");
  const [profiles, setProfiles] = useState({});
  const [selectedProfile, setSelectedProfile] = useState("");
  const [saveAsName, setSaveAsName] = useState("");
  const [error, setError] = useState("");

  const loadProfiles = () => {
    fetch(`${API}/api/profiles`)
      .then((r) => r.json())
      .then(setProfiles)
      .catch(() => {});
  };

  useEffect(() => {
    loadProfiles();
  }, []);

  const applyProfile = (name) => {
    setSelectedProfile(name);
    const p = profiles[name];
    if (!p) return;
    setTopics((p.topics || []).join(", "));
    // Fall back to the current value rather than undefined — a hand-edited or
    // legacy-format campaigns.json entry missing these fields would otherwise flip
    // the number input from controlled to uncontrolled (a real React warning
    // confirmed in this app's dev console).
    setMinDuration(p.min_duration ?? minDuration);
    setMaxDuration(p.max_duration ?? maxDuration);
    setHashtag(p.hashtag || "");
  };

  const handleSaveProfile = async () => {
    if (!saveAsName.trim()) return;
    try {
      await fetch(`${API}/api/profiles`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: saveAsName.trim(),
          topics: topics.split(",").map((t) => t.trim()).filter(Boolean),
          min_duration: Number(minDuration),
          max_duration: Number(maxDuration),
          hashtag,
        }),
      });
      setSaveAsName("");
      loadProfiles();
    } catch (e) {
      setError("Failed to save profile: " + e.message);
    }
  };

  const handleDeleteProfile = async () => {
    if (!selectedProfile) return;
    if (!window.confirm(`Delete saved profile "${selectedProfile}"?`)) return;
    try {
      const res = await fetch(`${API}/api/profiles/${encodeURIComponent(selectedProfile)}`, {
        method: "DELETE",
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `Request failed (${res.status})`);
      }
      setSelectedProfile("");
      loadProfiles();
    } catch (e) {
      setError("Failed to delete profile: " + e.message);
    }
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    setError("");
    if (Number(minDuration) >= Number(maxDuration)) {
      setError("Min duration must be less than max duration.");
      return;
    }
    const topicList = topics.split(",").map((t) => t.trim()).filter(Boolean);
    if (mode === "url") {
      if (!url.trim()) {
        setError("Please paste a video URL.");
        return;
      }
      onSubmit({
        url: url.trim(),
        topics: topicList,
        min_duration: Number(minDuration),
        max_duration: Number(maxDuration),
        hashtag,
      });
    } else {
      if (!file) {
        setError("Please choose a video file to upload.");
        return;
      }
      onUpload({
        file,
        topics: topicList,
        min_duration: Number(minDuration),
        max_duration: Number(maxDuration),
        hashtag,
      });
    }
  };

  return (
    <form className="card" onSubmit={handleSubmit}>
      <h2>New clip job</h2>

      <label>
        Saved campaign profile
        <div className="row">
          <select
            value={selectedProfile}
            onChange={(e) => applyProfile(e.target.value)}
            disabled={disabled}
            style={{ flex: 1 }}
          >
            <option value="">
              {Object.keys(profiles).length > 0 ? "-- none --" : "-- no saved profiles yet --"}
            </option>
            {Object.keys(profiles).map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={handleDeleteProfile}
            disabled={disabled || !selectedProfile}
          >
            Delete
          </button>
        </div>
      </label>

      <div className="mode-toggle">
        <button
          type="button"
          className={mode === "url" ? "toggle-active" : ""}
          onClick={() => setMode("url")}
          disabled={disabled}
        >
          Paste URL
        </button>
        <button
          type="button"
          className={mode === "upload" ? "toggle-active" : ""}
          onClick={() => setMode("upload")}
          disabled={disabled}
        >
          Upload file
        </button>
      </div>

      {mode === "url" ? (
        <label>
          Video URL (YouTube or a public Google Drive share link)
          <input
            type="text"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://youtube.com/watch?v=... or a Drive share link"
            disabled={disabled}
          />
        </label>
      ) : (
        <label>
          Video file
          <div
            role="button"
            tabIndex={0}
            className={"dropzone" + (dragOver ? " dragover" : "")}
            onDragOver={(e) => {
              e.preventDefault();
              if (!disabled) setDragOver(true);
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragOver(false);
              if (disabled) return;
              const dropped = e.dataTransfer.files?.[0];
              if (dropped) setFile(dropped);
            }}
            onKeyDown={(e) => {
              // The file input is visually hidden (display:none removes it from
              // the tab order entirely, so it can never receive focus on its
              // own) — without this, the dropzone would be completely
              // unreachable by keyboard despite looking clickable.
              if (!disabled && (e.key === "Enter" || e.key === " ")) {
                e.preventDefault();
                fileInputRef.current?.click();
              }
            }}
          >
            {file ? file.name : "Drag a video file here, or click to choose one"}
            {/* Nested inside the <label> — native label-click-forwarding already
                opens this picker on a mouse click, so there's no onClick here
                (adding one would double-trigger the dialog) — only onKeyDown
                above needs the ref, for keyboard users. */}
            <input
              ref={fileInputRef}
              type="file"
              accept="video/*"
              onChange={(e) => setFile(e.target.files?.[0] || null)}
              disabled={disabled}
              style={{ display: "none" }}
            />
          </div>
        </label>
      )}

      <label>
        Topics (comma-separated)
        <input
          type="text"
          value={topics}
          onChange={(e) => setTopics(e.target.value)}
          placeholder="Lovable, Anton"
          disabled={disabled}
        />
      </label>

      <div className="row">
        <label>
          Min duration (s)
          <input
            type="number"
            value={minDuration}
            onChange={(e) => setMinDuration(e.target.value)}
            disabled={disabled}
          />
        </label>
        <label>
          Max duration (s)
          <input
            type="number"
            value={maxDuration}
            onChange={(e) => setMaxDuration(e.target.value)}
            disabled={disabled}
          />
        </label>
      </div>

      <label>
        Required hashtag
        <input
          type="text"
          value={hashtag}
          onChange={(e) => setHashtag(e.target.value)}
          placeholder="#LovablePartner"
          disabled={disabled}
        />
      </label>

      <div className="row">
        <input
          type="text"
          value={saveAsName}
          onChange={(e) => setSaveAsName(e.target.value)}
          placeholder="Save current settings as..."
          disabled={disabled}
        />
        <button type="button" onClick={handleSaveProfile} disabled={disabled}>
          Save profile
        </button>
      </div>

      {error && <p className="error">{error}</p>}

      <button type="submit" className="primary" disabled={disabled}>
        {disabled && <span className="spinner" />}
        {disabled ? "Processing..." : "Process video"}
      </button>
    </form>
  );
}

const STAGE_LABELS = {
  queued: "Queued",
  downloading: "Downloading video",
  transcribing: "Transcribing audio",
  detecting: "Detecting highlights",
  rendering: "Cutting, cropping, captioning clips",
  done: "Done",
  error: "Error",
};

function ProgressBar({ stage, downloadPercent, renderProgress }) {
  const stages = ["queued", "downloading", "transcribing", "detecting", "rendering", "done"];
  const idx = stages.indexOf(stage);
  return (
    <div className="card">
      <h2>Job progress</h2>
      <div className="stages">
        {stages.map((s, i) => (
          <div
            key={s}
            className={
              "stage-step" +
              (i < idx ? " done" : i === idx ? " active" : "") +
              (stage === "error" ? " error" : "")
            }
          >
            {STAGE_LABELS[s]}
            {s === "downloading" && stage === "downloading" && (
              <div className="download-bar-track">
                <div
                  className="download-bar-fill"
                  style={{ width: `${downloadPercent || 0}%` }}
                />
                <span className="download-bar-label">{Math.round(downloadPercent || 0)}%</span>
              </div>
            )}
            {s === "rendering" && stage === "rendering" && renderProgress && renderProgress.total > 0 && (
              <div className="download-bar-track">
                <div
                  className="download-bar-fill"
                  style={{ width: `${(renderProgress.done / renderProgress.total) * 100}%` }}
                />
                <span className="download-bar-label">
                  {renderProgress.done} / {renderProgress.total} clips
                </span>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function VideoTimeline({ jobId, sourceDuration, highlightMarkers, detectionMode, onManualClip }) {
  const [rangeStart, setRangeStart] = useState(0);
  const [rangeEnd, setRangeEnd] = useState(Math.min(15, sourceDuration || 15));
  const [creating, setCreating] = useState(false);
  const [err, setErr] = useState("");
  const videoRef = useRef(null);

  const maxBound = sourceDuration || 60;

  useEffect(() => {
    setRangeEnd((e) => Math.min(Math.max(e, rangeStart + 1), maxBound));
  }, [maxBound]);

  const seekTo = (t) => {
    if (videoRef.current) videoRef.current.currentTime = t;
  };

  const handleCreate = async () => {
    if (rangeEnd <= rangeStart) {
      setErr("End must be after start.");
      return;
    }
    setCreating(true);
    setErr("");
    try {
      const res = await fetchWithTimeout(`${API}/api/jobs/${jobId}/manual-clip`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ start: Number(rangeStart), end: Number(rangeEnd) }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `Request failed (${res.status})`);
      }
      const clip = await res.json();
      onManualClip(clip);
    } catch (e) {
      setErr(e.message);
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="card">
      <div className="clip-header">
        <h2>Source video</h2>
        {detectionMode && (
          <span
            className={"badge " + (detectionMode === "groq" ? "pass" : "fail")}
            title={
              detectionMode === "groq"
                ? "Using Groq's LLM to find topic-relevant segments, including paraphrases without the literal keyword."
                : "No GROQ_API_KEY set (or it's unavailable) — falling back to plain keyword matching, which misses paraphrased mentions of your topic."
            }
          >
            {detectionMode === "groq" ? "AI DETECTION" : "KEYWORD ONLY"}
          </span>
        )}
      </div>
      <video
        ref={videoRef}
        src={`${API}/api/video/source/${jobId}`}
        controls
        className="preview-video"
        onTimeUpdate={(e) => {
          if (e.target.currentTime >= rangeEnd) e.target.pause();
        }}
      />

      {highlightMarkers && highlightMarkers.length > 0 && (
        <div className="marker-track">
          {highlightMarkers.map((m, i) => (
            <div
              key={i}
              className="marker"
              title={`${formatTime(m.start)} – ${formatTime(m.end)} · ${m.reason} (score ${m.score.toFixed(1)})`}
              style={{
                left: `${(m.start / maxBound) * 100}%`,
                width: `${Math.max(0.5, ((m.end - m.start) / maxBound) * 100)}%`,
              }}
              onClick={() => {
                setRangeStart(m.start);
                setRangeEnd(m.end);
                seekTo(m.start);
              }}
            />
          ))}
        </div>
      )}
      <p className="clip-meta">
        {highlightMarkers && highlightMarkers.length > 0
          ? `${highlightMarkers.length} potential highlight(s) found so far — click a marker to select it, or select your own range below.`
          : "Highlights will appear here as detection runs — or select a range below to clip manually right now."}
      </p>

      <div className="slider-group">
        <label>
          Manual clip start: {formatTime(rangeStart)}
          <input
            type="range"
            min={0}
            max={maxBound}
            step={0.1}
            value={rangeStart}
            onChange={(e) => {
              const v = Math.min(Number(e.target.value), rangeEnd - 0.1);
              setRangeStart(v);
              seekTo(v);
            }}
          />
        </label>
        <label>
          Manual clip end: {formatTime(rangeEnd)}
          <input
            type="range"
            min={0}
            max={maxBound}
            step={0.1}
            value={rangeEnd}
            onChange={(e) => {
              const v = Math.max(Number(e.target.value), rangeStart + 0.1);
              setRangeEnd(v);
              seekTo(v);
            }}
          />
        </label>
      </div>
      {err && <p className="error">{err}</p>}
      <button className="primary" onClick={handleCreate} disabled={creating}>
        {creating && <span className="spinner" />}
        {creating ? "Creating clip..." : "Create clip now"}
      </button>
    </div>
  );
}

function TrimEditor({ jobId, clip, sourceDuration, onApplied }) {
  const [start, setStart] = useState(clip.start);
  const [end, setEnd] = useState(clip.end);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");
  const videoRef = useRef(null);

  const maxBound = sourceDuration || clip.end + 30;

  const seekTo = (t) => {
    if (videoRef.current) {
      videoRef.current.currentTime = t;
    }
  };

  const handleApply = async () => {
    if (end <= start) {
      setErr("End must be after start.");
      return;
    }
    setSaving(true);
    setErr("");
    try {
      const res = await fetchWithTimeout(`${API}/api/clips/${jobId}/${clip.index}/trim`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ start: Number(start), end: Number(end) }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `Request failed (${res.status})`);
      }
      const data = await res.json();
      onApplied(data);
    } catch (e) {
      setErr(e.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="trim-editor">
      <video
        ref={videoRef}
        src={`${API}/api/video/source/${jobId}`}
        controls
        className="preview-video"
        onTimeUpdate={(e) => {
          if (e.target.currentTime >= end) e.target.pause();
        }}
      />
      <div className="slider-group">
        <label>
          Start: {formatTime(start)}
          <input
            type="range"
            min={0}
            max={maxBound}
            step={0.1}
            value={start}
            onChange={(e) => {
              const v = Math.min(Number(e.target.value), end - 0.1);
              setStart(v);
              seekTo(v);
            }}
          />
        </label>
        <label>
          End: {formatTime(end)}
          <input
            type="range"
            min={0}
            max={maxBound}
            step={0.1}
            value={end}
            onChange={(e) => {
              const v = Math.max(Number(e.target.value), start + 0.1);
              setEnd(v);
              seekTo(v);
            }}
          />
        </label>
      </div>
      <p className="duration-readout">Duration: {(end - start).toFixed(1)}s</p>
      {err && <p className="error">{err}</p>}
      <button className="primary" onClick={handleApply} disabled={saving}>
        {saving && <span className="spinner" />}
        {saving ? "Re-rendering..." : "Apply trim"}
      </button>
    </div>
  );
}

function CropEditor({ jobId, clip, onApplied }) {
  const duration = clip.end - clip.start;
  const initialSegments = clip.crop_segments && clip.crop_segments.length > 0
    ? clip.crop_segments
    : [{ start: 0, end: duration, crop_center_frac: clip.crop_center_frac ?? 0.5 }];
  const [segments, setSegments] = useState(initialSegments);
  // Captured once at mount — light tick marks showing where auto-detection put its
  // boundaries, kept visible even after the user starts editing, as a reference
  // point for "here's where the auto shot-cut was detected."
  const [autoBoundaries] = useState(() => initialSegments.slice(0, -1).map((s) => s.end));
  const [activeIndex, setActiveIndex] = useState(0);
  const [cropWidthFrac, setCropWidthFrac] = useState(0.3164); // real value set once the source video's actual dimensions load
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");
  const videoRef = useRef(null);
  const containerRef = useRef(null);

  const seekToSegment = (i) => {
    setActiveIndex(i);
    const seg = segments[i];
    if (videoRef.current) {
      // Segment times are clip-relative; the preview shows the full source video,
      // so convert back to an absolute position — the midpoint gives a
      // representative frame for that segment rather than its very first frame
      // (which is often still mid-transition right at a cut).
      videoRef.current.currentTime = clip.start + (seg.start + seg.end) / 2;
    }
  };

  // Number-key shortcuts to jump between segments — the same convention
  // Premiere Pro and DaVinci Resolve use for switching multicam angles.
  // Ignored while typing in a text field elsewhere on the page, and scoped to
  // this specific editor instance via the focus check below — with more than
  // one clip open for editing at once, a plain window-level listener would
  // fire in every mounted CropEditor simultaneously, silently reseeking a
  // preview the user isn't even looking at (confirmed as a real bug: two
  // crop panels open at once both react to the same keypress).
  useEffect(() => {
    const handleKey = (e) => {
      if (!containerRef.current?.contains(document.activeElement)) return;
      // Range sliders are <input> too — only skip actual text-entry fields, so
      // the shortcut still works right after dragging a segment's pan slider.
      const tag = e.target.tagName;
      const type = e.target.type;
      if (tag === "TEXTAREA" || (tag === "INPUT" && type !== "range" && type !== "checkbox")) return;
      const num = parseInt(e.key, 10);
      if (!Number.isNaN(num) && num >= 1 && num <= segments.length) {
        seekToSegment(num - 1);
      }
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [segments]);

  const handleLoadedMetadata = (e) => {
    const { videoWidth, videoHeight } = e.target;
    if (videoWidth && videoHeight) {
      const targetWidth = videoHeight * (9 / 16);
      setCropWidthFrac(Math.min(1, targetWidth / videoWidth));
    }
    seekToSegment(activeIndex);
  };

  const updateFrac = (i, frac) => {
    setActiveIndex(i);
    setSegments((prev) => prev.map((s, idx) => (idx === i ? { ...s, crop_center_frac: frac } : s)));
  };

  const splitSegment = (i) => {
    setSegments((prev) => {
      const seg = prev[i];
      const mid = (seg.start + seg.end) / 2;
      if (mid - seg.start < 0.2 || seg.end - mid < 0.2) return prev; // too short to split further
      const first = { ...seg, end: mid };
      const second = { ...seg, start: mid };
      return [...prev.slice(0, i), first, second, ...prev.slice(i + 1)];
    });
    // A new segment was inserted before any index after i — keep the preview
    // pointed at the same logical segment instead of silently drifting onto
    // whatever now occupies its old array slot.
    setActiveIndex((cur) => (cur > i ? cur + 1 : cur));
  };

  const mergeWithNext = (i) => {
    setSegments((prev) => {
      if (i >= prev.length - 1) return prev;
      const merged = { ...prev[i], end: prev[i + 1].end };
      return [...prev.slice(0, i), merged, ...prev.slice(i + 2)];
    });
    setActiveIndex((cur) => (cur > i ? cur - 1 : cur));
  };

  const moveBoundary = (i, value) => {
    // Boundary i sits between segment i and segment i+1 — dragging it resizes both.
    setSegments((prev) => {
      const lo = prev[i].start + 0.2;
      const hi = prev[i + 1].end - 0.2;
      const v = Math.min(Math.max(Number(value), lo), hi);
      return prev.map((s, idx) => {
        if (idx === i) return { ...s, end: v };
        if (idx === i + 1) return { ...s, start: v };
        return s;
      });
    });
  };

  const handleApply = async () => {
    setSaving(true);
    setErr("");
    try {
      const res = await fetchWithTimeout(`${API}/api/clips/${jobId}/${clip.index}/crop-segments`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ segments }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `Request failed (${res.status})`);
      }
      const data = await res.json();
      onApplied(data);
    } catch (e) {
      setErr(e.message);
    } finally {
      setSaving(false);
    }
  };

  const activeFrac = segments[activeIndex]?.crop_center_frac ?? 0.5;
  const cropLeftFrac = Math.min(Math.max(activeFrac - cropWidthFrac / 2, 0), 1 - cropWidthFrac);

  return (
    <div className="trim-editor" ref={containerRef}>
      <p className="clip-meta">
        {segments.length > 1
          ? `This clip spans ${segments.length} detected framing(s) — each gets its own crop position below. Preview shows segment ${activeIndex + 1}.`
          : "One framing detected for this whole clip."}
        {segments.length > 1 && (
          <>
            {" "}Press <span className="kbd-hint">1</span>–<span className="kbd-hint">{segments.length}</span> to jump between them.
          </>
        )}
      </p>

      <div className="crop-preview-wrap">
        <video
          ref={videoRef}
          src={`${API}/api/video/source/${jobId}`}
          muted
          playsInline
          className="crop-preview-video"
          onLoadedMetadata={handleLoadedMetadata}
        />
        <div className="crop-mask" style={{ left: 0, width: `${cropLeftFrac * 100}%` }} />
        <div
          className="crop-mask"
          style={{ right: 0, left: "auto", width: `${(1 - cropLeftFrac - cropWidthFrac) * 100}%` }}
        />
        <div
          className="crop-window"
          style={{ left: `${cropLeftFrac * 100}%`, width: `${cropWidthFrac * 100}%` }}
        />
      </div>
      <p className="clip-meta">
        The clear band shows what stays in the final 9:16 video for segment {activeIndex + 1} — drag its
        pan slider below and watch this update live.
      </p>

      <div className="segment-timeline">
        {segments.map((s, i) => (
          <div
            key={i}
            role="button"
            tabIndex={0}
            className={"segment-block" + (i === activeIndex ? " segment-block-active" : "")}
            style={{ width: `${((s.end - s.start) / duration) * 100}%` }}
            onClick={() => seekToSegment(i)}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                seekToSegment(i);
              }
            }}
            title={`Segment ${i + 1}: ${formatTime(s.start)} – ${formatTime(s.end)}`}
          >
            {i + 1}
          </div>
        ))}
        {autoBoundaries.map((b, i) => (
          <div key={i} className="segment-tick" style={{ left: `${(b / duration) * 100}%` }} />
        ))}
      </div>

      {segments.map((seg, i) => {
        const mid = (seg.start + seg.end) / 2;
        return (
          <div
            key={i}
            className={"segment-row" + (i === activeIndex ? " segment-row-active" : "")}
          >
            <label>
              Segment {i + 1}: {formatTime(seg.start)} – {formatTime(seg.end)} — pan{" "}
              {(seg.crop_center_frac * 100).toFixed(0)}%
              <input
                type="range"
                min={0}
                max={1}
                step={0.01}
                value={seg.crop_center_frac}
                onFocus={() => seekToSegment(i)}
                onChange={(e) => updateFrac(i, Number(e.target.value))}
              />
            </label>
            {i < segments.length - 1 && (
              <label>
                Boundary after this segment: {formatTime(seg.end)}
                <input
                  type="range"
                  min={seg.start + 0.2}
                  max={segments[i + 1].end - 0.2}
                  step={0.1}
                  value={seg.end}
                  onChange={(e) => moveBoundary(i, e.target.value)}
                />
              </label>
            )}
            <div className="row">
              <button type="button" onClick={() => splitSegment(i)}>
                Split this segment
              </button>
              {i < segments.length - 1 && (
                <button type="button" onClick={() => mergeWithNext(i)}>
                  Merge with next
                </button>
              )}
            </div>
            <p className="segment-hint">
              {seg.end - seg.start < 0.4
                ? "Too short to split further."
                : `"Split" divides this at ${formatTime(mid)}, into ${formatTime(seg.start)}–${formatTime(mid)} and ${formatTime(mid)}–${formatTime(seg.end)}.`}
              {i < segments.length - 1 &&
                ` "Merge with next" removes the boundary at ${formatTime(seg.end)}, combining this with segment ${i + 2}.`}
            </p>
          </div>
        );
      })}

      {err && <p className="error">{err}</p>}
      <button className="primary" onClick={handleApply} disabled={saving}>
        {saving && <span className="spinner" />}
        {saving ? "Re-rendering..." : "Apply crop segments"}
      </button>
    </div>
  );
}

function CaptionEditor({ jobId, clip, onApplied }) {
  const [lines, setLines] = useState(clip.caption_lines || []);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");

  const updateLine = (i, text) => {
    setLines((prev) => prev.map((l, idx) => (idx === i ? { ...l, text } : l)));
  };

  const handleApply = async () => {
    setSaving(true);
    setErr("");
    try {
      const res = await fetchWithTimeout(`${API}/api/clips/${jobId}/${clip.index}/captions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ lines }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `Request failed (${res.status})`);
      }
      const data = await res.json();
      onApplied(data);
    } catch (e) {
      setErr(e.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="trim-editor">
      {lines.length === 0 && <p className="clip-meta">No caption lines to edit.</p>}
      {lines.map((line, i) => (
        <label key={i}>
          Line {i + 1} ({formatTime(line.start)} – {formatTime(line.end)})
          <input type="text" value={line.text} onChange={(e) => updateLine(i, e.target.value)} />
        </label>
      ))}
      {err && <p className="error">{err}</p>}
      <button className="primary" onClick={handleApply} disabled={saving || lines.length === 0}>
        {saving && <span className="spinner" />}
        {saving ? "Re-rendering..." : "Apply caption edits"}
      </button>
    </div>
  );
}

function ScoreGauge({ score }) {
  const pct = Math.max(0, Math.min(100, (score / 10) * 100));
  return (
    <span className="score-gauge" title={`Relevance score: ${score.toFixed(1)} / 10`}>
      <span className="score-ring" style={{ "--score-pct": `${pct}%` }}>
        {score.toFixed(1)}
      </span>
    </span>
  );
}

function ClipCard({ jobId, clip, sourceDuration, onClipUpdated, socialStatus, onSocialStatusChange }) {
  const [panel, setPanel] = useState(null); // null | "trim" | "crop" | "captions"
  const [cacheBust, setCacheBust] = useState(0);
  const [justApplied, setJustApplied] = useState(false);

  const handleApplied = (data) => {
    onClipUpdated(data);
    setCacheBust((n) => n + 1);
    setPanel(null);
    setJustApplied(true);
    setTimeout(() => setJustApplied(false), 3000);
  };

  const togglePanel = (name) => setPanel((p) => (p === name ? null : name));

  return (
    <div className="card clip-card">
      <div className="clip-header">
        <h3>
          Clip {clip.index + 1}
          {clip.manual && (
            <span className="manual-tag" title="Created by you from the timeline, not auto-detected">
              manual
            </span>
          )}
        </h3>
        <div className="row" style={{ gap: 8, alignItems: "center" }}>
          {!!clip.score && <ScoreGauge score={clip.score} />}
          <span
            className={"badge " + (clip.compliance.passed ? "pass" : "fail")}
            title={
              clip.compliance.passed
                ? "Meets your campaign's min/max duration and hashtag requirements"
                : "Doesn't meet one or more campaign requirements — see the list below"
            }
          >
            {clip.compliance.passed ? "PASS" : "FAIL"}
          </span>
        </div>
      </div>
      <p className="clip-meta">
        {formatTime(clip.start)} – {formatTime(clip.end)} ({clip.duration.toFixed(1)}s)
      </p>
      {clip.reason && <p className="clip-reason">{clip.reason}</p>}
      {clip.compliance.issues.length > 0 && (
        <ul className="issues">
          {clip.compliance.issues.map((issue, i) => (
            <li key={i}>{issue}</li>
          ))}
        </ul>
      )}

      {justApplied && <span className="toast">Applied — clip re-rendered</span>}

      <video
        key={cacheBust}
        src={`${API}/api/video/clip/${clip.clip_filename}?v=${cacheBust}`}
        controls
        className="preview-video"
      />

      <div className="row">
        <a
          href={`${API}/api/video/clip/${clip.clip_filename}?v=${cacheBust}`}
          download
          className="button-like"
        >
          Download
        </a>
        <button onClick={() => togglePanel("trim")}>
          {panel === "trim" ? "Cancel" : "Edit duration"}
        </button>
        <button onClick={() => togglePanel("crop")}>
          {panel === "crop" ? "Cancel" : "Adjust crop"}
        </button>
        <button onClick={() => togglePanel("captions")}>
          {panel === "captions" ? "Cancel" : "Edit captions"}
        </button>
        <button onClick={() => togglePanel("publish")}>
          {panel === "publish" ? "Cancel" : "Post to..."}
        </button>
      </div>

      {panel === "trim" && (
        <TrimEditor jobId={jobId} clip={clip} sourceDuration={sourceDuration} onApplied={handleApplied} />
      )}
      {panel === "crop" && <CropEditor jobId={jobId} clip={clip} onApplied={handleApplied} />}
      {panel === "captions" && <CaptionEditor jobId={jobId} clip={clip} onApplied={handleApplied} />}
      {panel === "publish" && (
        <PublishEditor
          jobId={jobId}
          clip={clip}
          socialStatus={socialStatus}
          onSocialStatusChange={onSocialStatusChange}
        />
      )}
    </div>
  );
}

function PublishEditor({ jobId, clip, socialStatus, onSocialStatusChange }) {
  const [platform, setPlatform] = useState("youtube"); // "youtube" | "tiktok"
  const [title, setTitle] = useState((clip.text || `Clip ${clip.index + 1}`).slice(0, 90));
  const [description, setDescription] = useState("");
  const [tags, setTags] = useState("");
  const [privacyStatus, setPrivacyStatus] = useState("private"); // YouTube: private/unlisted/public
  const [tiktokMode, setTiktokMode] = useState("inbox"); // "inbox" | "direct"
  const [posting, setPosting] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [result, setResult] = useState(null);
  const [err, setErr] = useState("");

  const connected = platform === "youtube" ? socialStatus.youtube_connected : socialStatus.tiktok_connected;

  const handleConnectTikTok = async () => {
    setConnecting(true);
    setErr("");
    try {
      const res = await fetchWithTimeout(`${API}/api/social/tiktok/authorize`);
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `Request failed (${res.status})`);
      }
      const data = await res.json();
      const popup = window.open(data.authorize_url, "_blank", "width=480,height=720");
      // No server-push channel for "the OAuth callback finished" — a short poll
      // after the popup closes catches the common case (user approves, popup
      // auto-navigates to our callback page, then they close the tab) without
      // needing the user to manually refresh the app.
      const poll = setInterval(() => {
        if (popup && popup.closed) {
          clearInterval(poll);
          onSocialStatusChange();
        }
      }, 1000);
    } catch (e) {
      setErr(e.message);
    } finally {
      setConnecting(false);
    }
  };

  const handlePost = async () => {
    setPosting(true);
    setErr("");
    setResult(null);
    try {
      const body =
        platform === "youtube"
          ? {
              title,
              description,
              tags: tags.split(",").map((t) => t.trim()).filter(Boolean),
              privacy_status: privacyStatus,
            }
          : { title, mode: tiktokMode };
      // Uploads can genuinely take longer than the default 120s timeout on a
      // large clip over a slow connection — give this one more room.
      const res = await fetchWithTimeout(
        `${API}/api/clips/${jobId}/${clip.index}/publish/${platform}`,
        { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) },
        300000
      );
      if (!res.ok) {
        const errBody = await res.json().catch(() => ({}));
        throw new Error(errBody.detail || `Request failed (${res.status})`);
      }
      setResult(await res.json());
    } catch (e) {
      setErr(e.message);
    } finally {
      setPosting(false);
    }
  };

  return (
    <div className="trim-editor">
      <div className="row" style={{ gap: 16 }}>
        <label>
          <input
            type="radio"
            name={`platform-${clip.index}`}
            checked={platform === "youtube"}
            onChange={() => { setPlatform("youtube"); setResult(null); setErr(""); }}
          />{" "}
          YouTube
        </label>
        <label>
          <input
            type="radio"
            name={`platform-${clip.index}`}
            checked={platform === "tiktok"}
            onChange={() => { setPlatform("tiktok"); setResult(null); setErr(""); }}
          />{" "}
          TikTok
        </label>
      </div>

      {!connected && platform === "youtube" && (
        <p className="clip-meta">
          YouTube isn't connected yet. Run <code>python scripts/setup_youtube_auth.py</code> once from a
          terminal (see README) — it opens your browser for a one-time authorization.
        </p>
      )}
      {!connected && platform === "tiktok" && (
        <div className="row" style={{ alignItems: "center", gap: 8 }}>
          <p className="clip-meta" style={{ margin: 0 }}>TikTok isn't connected yet.</p>
          <button onClick={handleConnectTikTok} disabled={connecting}>
            {connecting && <span className="spinner" />}
            Connect TikTok
          </button>
        </div>
      )}

      <label>
        Title
        <input type="text" value={title} onChange={(e) => setTitle(e.target.value)} maxLength={100} />
      </label>

      {platform === "youtube" && (
        <>
          <label>
            Description
            <textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={3} />
          </label>
          <label>
            Tags (comma-separated)
            <input type="text" value={tags} onChange={(e) => setTags(e.target.value)} placeholder="clip, highlights" />
          </label>
          <label>
            Privacy
            <select value={privacyStatus} onChange={(e) => setPrivacyStatus(e.target.value)}>
              <option value="private">Private</option>
              <option value="unlisted">Unlisted</option>
              <option value="public">Public</option>
            </select>
          </label>
        </>
      )}

      {platform === "tiktok" && (
        <label>
          Post mode
          <select value={tiktokMode} onChange={(e) => setTiktokMode(e.target.value)}>
            <option value="inbox">Send to TikTok inbox (you tap Post in the app)</option>
            <option value="direct">Post directly (requires an audited app)</option>
          </select>
        </label>
      )}

      {err && <p className="error">{err}</p>}
      {result && platform === "youtube" && (
        <p className="toast">
          Uploaded —{" "}
          <a href={result.url} target="_blank" rel="noreferrer">
            view on YouTube
          </a>
        </p>
      )}
      {result && platform === "tiktok" && <p className="toast">Sent to TikTok ({result.status})</p>}

      <button className="primary" onClick={handlePost} disabled={posting || !connected || !title.trim()}>
        {posting && <span className="spinner" />}
        {posting ? "Uploading..." : `Post to ${platform === "youtube" ? "YouTube" : "TikTok"}`}
      </button>
    </div>
  );
}

function App() {
  const [jobId, setJobId] = useState(null);
  const [stage, setStage] = useState(null);
  const [videoReady, setVideoReady] = useState(false);
  const [downloadPercent, setDownloadPercent] = useState(0);
  const [renderProgress, setRenderProgress] = useState(null);
  const [highlightMarkers, setHighlightMarkers] = useState([]);
  const [detectionMode, setDetectionMode] = useState(null);
  const [clips, setClips] = useState([]);
  const [renderErrors, setRenderErrors] = useState([]);
  const [errorMsg, setErrorMsg] = useState("");
  const [sourceDuration, setSourceDuration] = useState(null);
  const [socialStatus, setSocialStatus] = useState({ youtube_connected: false, tiktok_connected: false });
  const pollRef = useRef(null);
  const videoReadyFetchedRef = useRef(false);

  const refreshSocialStatus = () => {
    fetch(`${API}/api/social/status`)
      .then((r) => r.json())
      .then(setSocialStatus)
      .catch(() => {});
  };

  useEffect(() => {
    refreshSocialStatus();
  }, []);

  // Reattach to whatever job was open when the page was last loaded (or
  // reloaded) — otherwise a refresh always drops back to a blank form even
  // though the backend may still be happily running (or have finished) the job.
  useEffect(() => {
    const existing = new URLSearchParams(window.location.search).get("job");
    if (existing) {
      setJobId(existing);
      setStage("queued");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const setJobIdAndUrl = (id) => {
    setJobId(id);
    const url = new URL(window.location.href);
    if (id) url.searchParams.set("job", id);
    else url.searchParams.delete("job");
    window.history.replaceState(null, "", url);
  };

  const resetForNewJob = () => {
    setErrorMsg("");
    setClips([]);
    setRenderErrors([]);
    setSourceDuration(null);
    setVideoReady(false);
    setDownloadPercent(0);
    setRenderProgress(null);
    setHighlightMarkers([]);
    setDetectionMode(null);
    videoReadyFetchedRef.current = false;
  };

  const submitJob = async (payload) => {
    resetForNewJob();
    try {
      const res = await fetch(`${API}/api/process`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `Request failed (${res.status})`);
      }
      const data = await res.json();
      setJobIdAndUrl(data.job_id);
      setStage("queued");
    } catch (e) {
      setErrorMsg("Failed to submit job: " + e.message);
    }
  };

  const submitUpload = async ({ file, topics, min_duration, max_duration, hashtag }) => {
    resetForNewJob();
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("topics", topics.join(","));
      form.append("min_duration", min_duration);
      form.append("max_duration", max_duration);
      form.append("hashtag", hashtag);
      const res = await fetch(`${API}/api/process/upload`, { method: "POST", body: form });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `Request failed (${res.status})`);
      }
      const data = await res.json();
      setJobIdAndUrl(data.job_id);
      setStage("queued");
    } catch (e) {
      setErrorMsg("Failed to submit job: " + e.message);
    }
  };

  useEffect(() => {
    if (!jobId) return;

    const poll = async () => {
      try {
        const res = await fetch(`${API}/api/jobs/${jobId}`);
        if (res.status === 404) {
          // Most likely: the backend restarted since this job was created (job
          // state is in-memory only) — reattaching from the URL found nothing
          // to reattach to. Say so plainly instead of polling a dead job forever.
          // Also clear jobId-dependent UI state (clips, download-all link, etc.)
          // — otherwise stale clip cards stick around pointing edit/download
          // actions at a now-null job ID, failing with a confusing generic
          // error instead of this already-shown one.
          resetForNewJob();
          setErrorMsg("This job is no longer available (the server may have restarted). Please start a new one.");
          clearInterval(pollRef.current);
          setJobIdAndUrl(null);
          return;
        }
        if (!res.ok) return;
        const data = await res.json();
        setStage(data.stage);
        if (typeof data.download_percent === "number") setDownloadPercent(data.download_percent);
        if (data.render_progress) setRenderProgress(data.render_progress);
        if (data.highlight_markers) setHighlightMarkers(data.highlight_markers);
        if (data.detection_mode) setDetectionMode(data.detection_mode);
        if (data.clips) setClips(data.clips);

        // Use a ref, not the videoReady state, as the "already fetched" guard —
        // this closure is created once per jobId (the effect below only depends
        // on [jobId]) so a captured state value stays stale on every subsequent
        // poll tick. With state, that stale `false` caused source-duration to be
        // re-fetched on every single 2s poll for the rest of the job instead of
        // once (confirmed via repeated requests in the network log).
        if (data.video_ready && !videoReadyFetchedRef.current) {
          videoReadyFetchedRef.current = true;
          setVideoReady(true);
          fetch(`${API}/api/source-duration/${jobId}`)
            .then((r) => r.json())
            .then((d) => setSourceDuration(d.duration))
            .catch(() => {});
        }

        if (data.stage === "error") {
          setErrorMsg(data.error || "Unknown error");
          clearInterval(pollRef.current);
        }
        if (data.stage === "done") {
          setRenderErrors(data.render_errors || []);
          clearInterval(pollRef.current);
        }
      } catch {
        // transient network error while polling — next tick will retry
      }
    };

    poll();
    pollRef.current = setInterval(poll, 2000);
    return () => clearInterval(pollRef.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId]);

  const handleClipUpdated = (data) => {
    setClips((prev) =>
      prev.map((c) => (c.index === data.index ? { ...c, ...data } : c))
    );
  };

  const handleManualClip = (clip) => {
    // A poll tick can land between the backend appending this clip to job["clips"]
    // (which happens before the POST response is even sent) and this response
    // resolving — if that poll's setClips(data.clips) already included it, a plain
    // append here would duplicate it (same index, two ClipCards, a React
    // duplicate-key warning). Guard by index instead of assuming this is new.
    setClips((prev) => (prev.some((c) => c.index === clip.index) ? prev : [...prev, clip]));
  };

  const isProcessing = stage && stage !== "done" && stage !== "error";
  const isFullyDone = stage === "done";

  return (
    <div className="app">
      <div className="app-header">
        <div className="app-logo">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5v14l11-7z" /></svg>
        </div>
        <div className="app-title-group">
          <h1>Auto Video Clipper</h1>
          <p>Paste a video, get compliance-checked vertical clips out.</p>
        </div>
      </div>
      <ProcessForm onSubmit={submitJob} onUpload={submitUpload} disabled={isProcessing} />

      {stage && (
        <ProgressBar stage={stage} downloadPercent={downloadPercent} renderProgress={renderProgress} />
      )}

      {errorMsg && (
        <div className="card">
          <p className="error">{errorMsg}</p>
        </div>
      )}

      {videoReady && jobId && (
        <VideoTimeline
          jobId={jobId}
          sourceDuration={sourceDuration}
          highlightMarkers={highlightMarkers}
          detectionMode={detectionMode}
          onManualClip={handleManualClip}
        />
      )}

      {renderErrors.length > 0 && (
        <div className="card">
          <p className="error">Some clips failed to render:</p>
          <ul className="issues">
            {renderErrors.map((e, i) => (
              <li key={i}>{e}</li>
            ))}
          </ul>
        </div>
      )}

      {isFullyDone && clips.length === 0 && renderErrors.length === 0 && (
        <div className="card">
          <p>No candidate clips found. Try different topics, or use the timeline above to clip manually.</p>
        </div>
      )}

      {clips.length > 1 && (
        <a href={`${API}/api/jobs/${jobId}/download-all`} className="button-like" style={{ marginBottom: 12 }}>
          Download all {clips.length} clips (.zip)
        </a>
      )}

      {clips.length > 0 && (
        <div className="clips-grid">
          {clips.map((clip) => (
            <ClipCard
              key={clip.index}
              jobId={jobId}
              clip={clip}
              sourceDuration={sourceDuration}
              onClipUpdated={handleClipUpdated}
              socialStatus={socialStatus}
              onSocialStatusChange={refreshSocialStatus}
            />
          ))}
        </div>
      )}

      <MaintenancePanel />
    </div>
  );
}

function formatBytes(bytes) {
  if (!bytes) return "0 MB";
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function MaintenancePanel() {
  const [stats, setStats] = useState(null);
  const [result, setResult] = useState(null);
  const [running, setRunning] = useState(false);
  const [includeToday, setIncludeToday] = useState(false);
  const [err, setErr] = useState("");

  const loadStats = () => {
    fetch(`${API}/api/maintenance/stats`)
      .then((r) => r.json())
      .then(setStats)
      .catch(() => {});
  };

  useEffect(() => {
    loadStats();
  }, []);

  const handleCleanup = async () => {
    setRunning(true);
    setErr("");
    setResult(null);
    try {
      const maxAge = includeToday ? 0 : 24;
      const res = await fetch(`${API}/api/maintenance/cleanup?max_age_hours=${maxAge}`, {
        method: "POST",
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `Request failed (${res.status})`);
      }
      setResult(await res.json());
      loadStats();
    } catch (e) {
      setErr(e.message);
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="card maintenance-panel">
      {stats ? (
        <p className="clip-meta">
          Currently stored: {stats.source_videos.count} source video(s) (
          {formatBytes(stats.source_videos.bytes)}), {stats.rendered_clips.count} rendered clip(s) (
          {formatBytes(stats.rendered_clips.bytes)}), {stats.quarantined_failed.count} quarantined
          failed clip(s) ({formatBytes(stats.quarantined_failed.bytes)}). Files older than 24h are
          cleaned up automatically.
        </p>
      ) : (
        <p className="clip-meta">Loading storage stats...</p>
      )}

      <label className="row" style={{ alignItems: "center", fontSize: 13 }}>
        <input
          type="checkbox"
          checked={includeToday}
          onChange={(e) => setIncludeToday(e.target.checked)}
        />
        Include today's files too (force clean everything now)
      </label>

      <button onClick={handleCleanup} disabled={running}>
        {running && <span className="spinner" />}
        {running ? "Cleaning up..." : "Clean up old files now"}
      </button>
      {result && (
        <p className="clip-meta">
          Removed {result.jobs_removed} finished job record(s) and {result.files_removed} file(s).
        </p>
      )}
      {err && <p className="error">{err}</p>}
    </div>
  );
}

export default App;
