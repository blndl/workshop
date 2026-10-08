import { useEffect, useState } from "react";
import { api } from "../api";
import { clock } from "../format";
import type { CameraInfo, Snapshot } from "../types";
import { usePoll } from "../usePoll";

/** Everything about the camera: live feed, vision check, detector, photos. */
export function CameraTab() {
  const info = usePoll(api.camera, 1000);
  const shots = usePoll(() => api.snapshots(60), 3000);
  const [open, setOpen] = useState<Snapshot | null>(null);
  const c = info.data;

  return (
    <div className="camera-tab">
      <div className="camera-top">
        <LiveView info={c} />
        <div className="col">
          {c?.verifying && (
            <section className="card verifying">
              <strong>Checking motion on {c.verifying.node}…</strong>
              <span className="small">The camera took a burst; the detector must see a person for it to count.</span>
            </section>
          )}
          <VisionStats info={c} />
          <Health info={c} />
        </div>
      </div>
      <Gallery shots={shots.data ?? []} onOpen={setOpen} />
      {open && <Lightbox shot={open} onClose={() => setOpen(null)} />}
    </div>
  );
}

function LiveView({ info }: { info: CameraInfo | null }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Restart the MJPEG stream whenever the camera comes (back) on.
  const [streamKey, setStreamKey] = useState(0);
  const streaming = info?.streaming ?? false;
  useEffect(() => {
    if (streaming) setStreamKey((k) => k + 1);
  }, [streaming]);

  const toggle = async (on: boolean) => {
    setBusy(true);
    setError(null);
    try {
      await api.liveView(on);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  const cam = info?.camera;
  const live = (info?.live_view_s ?? 0) > 0;

  return (
    <section className="card live">
      <header>
        <h2>
          Camera {streaming && <span className="pill bad rec">● LIVE</span>}
        </h2>
        <span className="muted small">{cam ? `${cam.source} · ${cam.why}` : "camera service not running"}</span>
      </header>
      <div className="live-frame">
        {streaming ? (
          <img key={streamKey} src={`/api/camera/stream?k=${streamKey}`} alt="live camera" />
        ) : (
          <div className="live-off">
            <strong>{cam ? "Camera off" : "No camera"}</strong>
            <span>
              {cam
                ? "The camera only runs while the system is armed, so the people living here aren't filmed."
                : "Start the stack with scripts/sim.sh up."}
            </span>
          </div>
        )}
      </div>
      <div className="live-actions">
        {cam?.open && !live && !cam.live ? (
          <span className="small muted">On because the {cam.why}. Live view is only needed while disarmed.</span>
        ) : live ? (
          <>
            <span className="small">Live view: {Math.ceil(info!.live_view_s)} s left</span>
            <button onClick={() => toggle(false)} disabled={busy}>Stop live view</button>
          </>
        ) : (
          <>
            <span className="small muted">Turns the camera on for 2 minutes. Recorded in the event log.</span>
            <button className="arm-like" onClick={() => toggle(true)} disabled={busy || !cam}>Start live view</button>
          </>
        )}
      </div>
      {error && <p className="msg bad">{error}</p>}
    </section>
  );
}

function VisionStats({ info }: { info: CameraInfo | null }) {
  const s = info?.stats;
  const tiles = [
    { label: "False alarms avoided", value: s?.motion_dismissed ?? 0, good: true },
    { label: "Motions confirmed", value: s?.motion_confirmed ?? 0 },
    { label: "Not verified in time", value: s?.verify_timeouts ?? 0 },
    { label: "Photos", value: s?.photos ?? 0 },
    { label: "Analysed", value: s?.analysed ?? 0 },
    { label: "With a person", value: s?.with_person ?? 0 },
  ];
  return (
    <section className="card">
      <h2>Vision</h2>
      <div className="tiles">
        {tiles.map((t) => (
          <div key={t.label} className={t.good && t.value ? "tile good" : "tile"}>
            <strong>{t.value}</strong>
            <span>{t.label}</span>
          </div>
        ))}
      </div>
      <p className="muted small">
        Motion sensors marked <code>confirm: person</code> only count if the camera sees someone; a cat or a curtain is
        dismissed. If the detector doesn't answer in time, the motion counts anyway.
      </p>
    </section>
  );
}

function Health({ info }: { info: CameraInfo | null }) {
  const cam = info?.camera;
  const det = info?.detector;
  return (
    <section className="card">
      <h2>Health</h2>
      <dl className="health">
        <dt>Camera</dt>
        <dd className={cam?.error ? "bad-text" : ""}>
          {cam ? (cam.error ? "error" : cam.open ? "on" : "off") : "not running"}
          {cam ? ` · ${cam.frames} frames, ${cam.snapshots} photos since start` : ""}
        </dd>
        <dt>Detector</dt>
        <dd className={det && !det.ready ? "bad-text" : ""}>
          {det ? (det.ready ? `ready · ${det.model}` : det.error ?? "not ready") : "not running"}
        </dd>
        <dt>Analysed</dt>
        <dd>{det ? `${det.processed} photos, ${det.persons} with a person` : "-"}</dd>
        <dt>Speed</dt>
        <dd>
          {info?.stats.median_latency_ms != null ? `${Math.round(info.stats.median_latency_ms)} ms per photo (median)` : "-"}
        </dd>
      </dl>
    </section>
  );
}

function Badge({ shot }: { shot: Snapshot }) {
  const d = shot.detection;
  if (!d) return <span className="badge">not analysed</span>;
  if (d.person) return <span className="badge person">person {Math.round(d.confidence * 100)}%</span>;
  const other = Object.keys(d.objects).filter((k) => k !== "person");
  return <span className="badge clear">no person{other.length ? ` · ${other.join(", ")}` : ""}</span>;
}

function Boxes({ shot }: { shot: Snapshot }) {
  return (
    <>
      {(shot.detection?.boxes ?? []).map((b, i) => (
        <div
          key={i}
          className={b.label === "person" ? "box person" : "box"}
          style={{ left: `${b.x * 100}%`, top: `${b.y * 100}%`, width: `${b.w * 100}%`, height: `${b.h * 100}%` }}
        >
          <span>{b.label} {Math.round(b.confidence * 100)}%</span>
        </div>
      ))}
    </>
  );
}

function Gallery({ shots, onOpen }: { shots: Snapshot[]; onOpen: (s: Snapshot) => void }) {
  return (
    <section className="card">
      <h2>
        Photos <span className="muted small">newest first · kept 30 days</span>
      </h2>
      {shots.length === 0 && <p className="muted">No photos yet: the camera takes them when the system is armed and something happens.</p>}
      <div className="gallery">
        {shots.map((s) => (
          <button key={s.path} className="shot" onClick={() => onOpen(s)}>
            <div className="shot-img">
              <img src={s.url} alt={s.reason} loading="lazy" />
              <Boxes shot={s} />
            </div>
            <div className="shot-meta">
              <span>{clock(s.ts)} · {s.reason}</span>
              <Badge shot={s} />
              {s.verified === false && <span className="badge tampered">modified!</span>}
            </div>
          </button>
        ))}
      </div>
    </section>
  );
}

function Lightbox({ shot, onClose }: { shot: Snapshot; onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  const d = shot.detection;
  return (
    <div className="lightbox" onClick={onClose} role="dialog" aria-label="photo">
      <div className="lightbox-body" onClick={(e) => e.stopPropagation()}>
        <div className="shot-img large">
          <img src={shot.url} alt={shot.reason} />
          <Boxes shot={shot} />
        </div>
        <div className="lightbox-info">
          <h3>{shot.reason}</h3>
          <dl className="health">
            <dt>Taken</dt>
            <dd>{new Date(shot.ts * 1000).toLocaleString()}</dd>
            <dt>Log record</dt>
            <dd>#{shot.seq ?? "-"}</dd>
            <dt>Integrity</dt>
            <dd className={shot.verified === false ? "bad-text" : ""}>
              {shot.verified === true ? "✓ matches the hash in the event log" : shot.verified === false ? "✗ file modified since it was logged" : "unknown"}
            </dd>
            <dt>Detection</dt>
            <dd>
              {d
                ? Object.entries(d.objects).map(([k, n]) => `${n} ${k}`).join(", ") || "nothing"
                : "not analysed"}
              {d ? ` · ${Math.round(d.latency_ms)} ms` : ""}
            </dd>
          </dl>
          <p className="small muted">{shot.path}</p>
          <button onClick={onClose}>Close</button>
        </div>
      </div>
    </div>
  );
}
