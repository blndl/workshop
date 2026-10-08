"""Detector service: runs YOLO on every snapshot the camera announces and
publishes the result. alarm-core logs each result and uses it to confirm or
dismiss motion (sensors with `confirm: person` in config/modules.yaml).

    in   alarm/events            'snapshot' events (path, reason)
    out  alarm/detections        {path, reason, person, confidence, boxes, objects, latency_ms}
    out  alarm/detector/status   retained: ready, model, processed, last latency
"""

from __future__ import annotations

import json
import queue
import time
from pathlib import Path
from typing import Callable

EVENTS_TOPIC = "alarm/events"
DETECTIONS_TOPIC = "alarm/detections"
STATUS_TOPIC = "alarm/detector/status"
STATUS_EVERY = 10.0


class DetectorService:
    def __init__(self, detector, snapshots: Path, transport, model_name: str = "",
                 log: Callable[[str], None] = print, wall: Callable[[], float] = time.time):
        self.detector = detector  # None if the model couldn't be loaded
        self.snapshots = Path(snapshots).resolve()
        self.transport = transport
        self.model_name = model_name
        self.log = log
        self.wall = wall
        self.processed = 0
        self.persons = 0
        self.errors = 0
        self.last_latency: float | None = None
        self.error: str | None = None if detector else "model not loaded"
        self.published: list[dict] = []
        self._inbox: queue.SimpleQueue = queue.SimpleQueue()
        self._next_status = 0.0
        transport.subscribe(EVENTS_TOPIC, lambda _t, p: self._inbox.put(p))

    def start(self) -> None:
        self.transport.connect()

    def tick(self, now: float) -> None:
        while True:
            try:
                payload = self._inbox.get_nowait()
            except queue.Empty:
                break
            try:
                e = json.loads(payload)
            except ValueError:
                continue
            if isinstance(e, dict) and e.get("type") == "snapshot":
                self._analyse(e)
        if now >= self._next_status:
            self._status()
            self._next_status = now + STATUS_EVERY

    def _analyse(self, e: dict) -> None:
        path, reason = str(e.get("path", "")), str(e.get("reason", ""))
        if self.detector is None:
            return
        file = (self.snapshots / path).resolve()
        if self.snapshots not in file.parents or not file.is_file():
            self.log(f"[detector] skipped {path!r}: not a snapshot file")
            return
        try:
            boxes, latency = self.detector.detect_jpeg(file.read_bytes())
        except Exception as exc:  # noqa: BLE001 - a bad image must not stop the service
            self.errors += 1
            self.log(f"[detector] {path}: {exc}")
            return
        people = [b for b in boxes if b.label == "person"]
        objects: dict[str, int] = {}
        for b in boxes:
            objects[b.label] = objects.get(b.label, 0) + 1
        result = {
            "path": path,
            "reason": reason,
            "seq": e.get("seq"),
            "person": bool(people),
            "confidence": round(max((b.confidence for b in people), default=0.0), 3),
            "objects": objects,
            "boxes": [b.as_dict() for b in boxes],
            "latency_ms": round(latency, 1),
        }
        self.processed += 1
        self.persons += bool(people)
        self.last_latency = latency
        self.published.append(result)
        self.transport.publish(DETECTIONS_TOPIC, json.dumps(result))
        seen = ", ".join(f"{n} {k}" for k, n in objects.items()) or "nothing"
        self.log(f"[detector] {path}: {seen} ({latency:.0f} ms)")

    def _status(self) -> None:
        status = {
            "ts": round(self.wall(), 3),
            "ready": self.detector is not None,
            "model": self.model_name,
            "error": self.error,
            "processed": self.processed,
            "persons": self.persons,
            "errors": self.errors,
            "last_latency_ms": round(self.last_latency, 1) if self.last_latency is not None else None,
        }
        self.transport.publish(STATUS_TOPIC, json.dumps(status), retain=True)
