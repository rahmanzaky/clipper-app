import { useEffect, useRef, useState } from "react";
import "./App.css";

const API = "http://127.0.0.1:8000";

function ProcessForm({ onSubmit, onUpload, disabled }) {
  const [mode, setMode] = useState("url"); // "url" | "upload"
  const [url, setUrl] = useState("");
  const [file, setFile] = useState(null);
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
    setMinDuration(p.min_duration);
    setMaxDuration(p.max_duration);
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

  const handleSubmit = (e) => {
    e.preventDefault();
    setError("");
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
        <select
          value={selectedProfile}
          onChange={(e) => applyProfile(e.target.value)}
          disabled={disabled}
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
          <input
            type="file"
            accept="video/*"
            onChange={(e) => setFile(e.target.files?.[0] || null)}
            disabled={disabled}
          />
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

function ProgressBar({ stage, downloadPercent }) {
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
          </div>
        ))}
      </div>
    </div>
  );
}

function VideoTimeline({ jobId, sourceDuration, highlightMarkers, onManualClip }) {
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
      const res = await fetch(`${API}/api/jobs/${jobId}/manual-clip`, {
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
      <h2>Source video</h2>
      <video ref={videoRef} src={`${API}/api/video/source/${jobId}`} controls className="preview-video" />

      {highlightMarkers && highlightMarkers.length > 0 && (
        <div className="marker-track">
          {highlightMarkers.map((m, i) => (
            <div
              key={i}
              className="marker"
              title={`${m.reason} (score ${m.score.toFixed(1)})`}
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
          Manual clip start: {Number(rangeStart).toFixed(1)}s
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
          Manual clip end: {Number(rangeEnd).toFixed(1)}s
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
      const res = await fetch(`${API}/api/clips/${jobId}/${clip.index}/trim`, {
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
      />
      <div className="slider-group">
        <label>
          Start: {Number(start).toFixed(1)}s
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
          End: {Number(end).toFixed(1)}s
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
        {saving ? "Re-rendering..." : "Apply trim"}
      </button>
    </div>
  );
}

function CropEditor({ jobId, clip, onApplied }) {
  const [frac, setFrac] = useState(clip.crop_center_frac ?? 0.5);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");

  const handleApply = async () => {
    setSaving(true);
    setErr("");
    try {
      const res = await fetch(`${API}/api/clips/${jobId}/${clip.index}/reposition`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ crop_center_frac: Number(frac) }),
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
      <label>
        Crop position (pan left/right): {(frac * 100).toFixed(0)}%
        <input
          type="range"
          min={0}
          max={1}
          step={0.01}
          value={frac}
          onChange={(e) => setFrac(Number(e.target.value))}
        />
      </label>
      {err && <p className="error">{err}</p>}
      <button className="primary" onClick={handleApply} disabled={saving}>
        {saving ? "Re-rendering..." : "Apply crop position"}
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
      const res = await fetch(`${API}/api/clips/${jobId}/${clip.index}/captions`, {
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
          Line {i + 1} ({line.start.toFixed(1)}s - {line.end.toFixed(1)}s)
          <input type="text" value={line.text} onChange={(e) => updateLine(i, e.target.value)} />
        </label>
      ))}
      {err && <p className="error">{err}</p>}
      <button className="primary" onClick={handleApply} disabled={saving || lines.length === 0}>
        {saving ? "Re-rendering..." : "Apply caption edits"}
      </button>
    </div>
  );
}

function ClipCard({ jobId, clip, sourceDuration, onClipUpdated }) {
  const [panel, setPanel] = useState(null); // null | "trim" | "crop" | "captions"
  const [cacheBust, setCacheBust] = useState(0);

  const handleApplied = (data) => {
    onClipUpdated(data);
    setCacheBust((n) => n + 1);
    setPanel(null);
  };

  const togglePanel = (name) => setPanel((p) => (p === name ? null : name));

  return (
    <div className="card clip-card">
      <div className="clip-header">
        <h3>
          Clip {clip.index + 1}
          {clip.manual && <span className="manual-tag">manual</span>}
        </h3>
        <span className={"badge " + (clip.compliance.passed ? "pass" : "fail")}>
          {clip.compliance.passed ? "PASS" : "FAIL"}
        </span>
      </div>
      <p className="clip-meta">
        {clip.start.toFixed(1)}s - {clip.end.toFixed(1)}s ({clip.duration.toFixed(1)}s)
        {clip.score ? ` · score ${clip.score.toFixed(1)}` : ""}
      </p>
      {clip.reason && <p className="clip-reason">{clip.reason}</p>}
      {clip.compliance.issues.length > 0 && (
        <ul className="issues">
          {clip.compliance.issues.map((issue, i) => (
            <li key={i}>{issue}</li>
          ))}
        </ul>
      )}

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
          {panel === "crop" ? "Cancel" : "Reposition crop"}
        </button>
        <button onClick={() => togglePanel("captions")}>
          {panel === "captions" ? "Cancel" : "Edit captions"}
        </button>
      </div>

      {panel === "trim" && (
        <TrimEditor jobId={jobId} clip={clip} sourceDuration={sourceDuration} onApplied={handleApplied} />
      )}
      {panel === "crop" && <CropEditor jobId={jobId} clip={clip} onApplied={handleApplied} />}
      {panel === "captions" && <CaptionEditor jobId={jobId} clip={clip} onApplied={handleApplied} />}
    </div>
  );
}

function App() {
  const [jobId, setJobId] = useState(null);
  const [stage, setStage] = useState(null);
  const [videoReady, setVideoReady] = useState(false);
  const [downloadPercent, setDownloadPercent] = useState(0);
  const [highlightMarkers, setHighlightMarkers] = useState([]);
  const [clips, setClips] = useState([]);
  const [renderErrors, setRenderErrors] = useState([]);
  const [errorMsg, setErrorMsg] = useState("");
  const [sourceDuration, setSourceDuration] = useState(null);
  const pollRef = useRef(null);

  const resetForNewJob = () => {
    setErrorMsg("");
    setClips([]);
    setRenderErrors([]);
    setSourceDuration(null);
    setVideoReady(false);
    setDownloadPercent(0);
    setHighlightMarkers([]);
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
      setJobId(data.job_id);
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
      setJobId(data.job_id);
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
        if (!res.ok) return;
        const data = await res.json();
        setStage(data.stage);
        if (typeof data.download_percent === "number") setDownloadPercent(data.download_percent);
        if (data.highlight_markers) setHighlightMarkers(data.highlight_markers);
        if (data.clips) setClips(data.clips);

        if (data.video_ready && !videoReady) {
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
    setClips((prev) => [...prev, clip]);
  };

  const isProcessing = stage && stage !== "done" && stage !== "error";
  const isFullyDone = stage === "done";

  return (
    <div className="app">
      <h1>Auto Video Clipper</h1>
      <ProcessForm onSubmit={submitJob} onUpload={submitUpload} disabled={isProcessing} />

      {stage && <ProgressBar stage={stage} downloadPercent={downloadPercent} />}

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

      {clips.length > 0 && (
        <div className="clips-grid">
          {clips.map((clip) => (
            <ClipCard
              key={clip.index}
              jobId={jobId}
              clip={clip}
              sourceDuration={sourceDuration}
              onClipUpdated={handleClipUpdated}
            />
          ))}
        </div>
      )}
    </div>
  );
}

export default App;
