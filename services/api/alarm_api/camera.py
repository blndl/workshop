"""Camera routes: status, live stream, live view on/off, the photo gallery.

Photos come from the event stream (snapshot + detection events, matched by
path), never from listing the folder, so duress photos stay hidden: the
bridge drops anything whose reason starts with "duress".
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel

from .bridge import AlarmCoreTimeout, Bridge

FRAME_FRESH = 3.0  # seconds: older than this, the camera is considered off
STREAM_EVERY = 0.5


class LiveIn(BaseModel):
    on: bool


def router(bridge: Bridge, snapshots_dir: Path | None) -> APIRouter:
    r = APIRouter(prefix="/api/camera")
    root = snapshots_dir.resolve() if snapshots_dir else None
    digests: dict[tuple[str, float], str] = {}  # (path, mtime) -> sha256, so files are hashed once

    def frame_fresh() -> bool:
        return bridge.frame_at is not None and time.time() - bridge.frame_at < FRAME_FRESH

    def safe_file(path: str) -> Path | None:
        if root is None or "duress" in path:
            return None
        f = (root / path).resolve()
        return f if root in f.parents and f.is_file() and f.suffix == ".jpg" else None

    def verified(path: str, sha: str | None) -> bool | None:
        f = safe_file(path)
        if f is None or not sha:
            return None
        key = (path, f.stat().st_mtime)
        if key not in digests:
            digests[key] = hashlib.sha256(f.read_bytes()).hexdigest()
        return digests[key] == sha

    @r.get("")
    def status():
        state = bridge.state or {}
        cam = dict(bridge.camera_status or {})
        det = dict(bridge.detector_status or {})
        events = bridge.recent_events(500)
        dismissed = sum(1 for e in events if e.get("type") == "motion_dismissed")
        confirmed = sum(1 for e in events if e.get("type") == "motion_confirmed")
        detections = [e for e in events if e.get("type") == "detection"]
        return {
            "camera": cam or None,
            "streaming": frame_fresh(),
            "detector": det or None,
            "live_view_s": state.get("live_view_s", 0),
            "verifying": state.get("verifying"),
            "stats": {
                "photos": sum(1 for e in events if e.get("type") == "snapshot"),
                "analysed": len(detections),
                "with_person": sum(1 for e in detections if e.get("person")),
                "motion_confirmed": confirmed,
                "motion_dismissed": dismissed,
                "verify_timeouts": sum(1 for e in events if e.get("type") == "verify_timeout"),
                "median_latency_ms": sorted(e.get("latency_ms", 0) for e in detections)[len(detections) // 2] if detections else None,
            },
        }

    @r.get("/frame.jpg")
    def frame():
        if not frame_fresh():
            raise HTTPException(404, "camera off")
        return Response(bridge.frame, media_type="image/jpeg", headers={"Cache-Control": "no-store"})

    @r.get("/stream")
    async def stream():
        """MJPEG: an <img src> shows it live. Ends when the camera stops sending."""
        async def frames():
            last = None
            idle = 0.0
            while idle < 10:
                if frame_fresh() and bridge.frame_at != last:
                    last, idle = bridge.frame_at, 0.0
                    jpeg = bridge.frame
                    yield (b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(jpeg)).encode()
                           + b"\r\n\r\n" + jpeg + b"\r\n")
                else:
                    idle += STREAM_EVERY
                await asyncio.sleep(STREAM_EVERY / 2)
        return StreamingResponse(frames(), media_type="multipart/x-mixed-replace; boundary=frame",
                                 headers={"Cache-Control": "no-store"})

    @r.post("/live")
    async def live(body: LiveIn):
        """Live view while disarmed: alarm-core logs it and turns it off by itself after 2 minutes."""
        try:
            events = await bridge.control("live_view", source="api", on=body.on)
        except AlarmCoreTimeout as e:
            raise HTTPException(504, str(e)) from e
        ev = next((e for e in events if e.get("type") == "live_view"), None)
        return {"on": bool(ev and ev.get("on")), "seconds": ev.get("seconds") if ev else None}

    @r.get("/snapshots")
    def snapshots(limit: int = 60):
        events = bridge.recent_events(500)
        found = {e["path"]: e for e in events if e.get("type") == "detection" and e.get("path")}
        out = []
        for e in events:
            if e.get("type") != "snapshot" or not e.get("path"):
                continue
            d = found.get(e["path"])
            out.append({
                "path": e["path"], "ts": e.get("ts"), "reason": e.get("reason"), "seq": e.get("seq"),
                "url": f"/api/camera/snapshots/file/{e['path']}",
                "verified": verified(e["path"], e.get("sha256")),
                "detection": None if d is None else {k: d.get(k) for k in ("person", "confidence", "objects", "boxes", "latency_ms")},
            })
            if len(out) >= min(limit, 200):
                break
        return out

    @r.get("/snapshots/file/{path:path}")
    def snapshot_file(path: str):
        f = safe_file(path)
        if f is None:
            raise HTTPException(404, "no such photo")
        return FileResponse(f, media_type="image/jpeg")

    return r
