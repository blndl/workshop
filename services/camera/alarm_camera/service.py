"""Camera service: follows alarm/events, captures per the policy, stores the
images and announces each one on alarm/snapshots (alarm-core logs the hash).
"""

from __future__ import annotations

import json
import queue
import time
from typing import Callable

from .policy import CapturePolicy
from .store import SnapshotStore

EVENTS_TOPIC = "alarm/events"
STATE_TOPIC = "alarm/state"
SNAPSHOTS_TOPIC = "alarm/snapshots"
PRUNE_EVERY = 3600.0


class CameraService:
    def __init__(
        self,
        source,
        store: SnapshotStore,
        transport,
        policy: CapturePolicy | None = None,
        log: Callable[[str], None] = print,
        wall: Callable[[], float] = time.time,
    ):
        self.source = source
        self.store = store
        self.transport = transport
        self.policy = policy or CapturePolicy()
        self.log = log
        self.wall = wall
        self.saved: list[dict] = []
        self._inbox: queue.SimpleQueue = queue.SimpleQueue()
        self._next_prune = 0.0
        self._camera_failed = False
        transport.subscribe(EVENTS_TOPIC, lambda t, p: self._inbox.put((t, p)))
        transport.subscribe(STATE_TOPIC, lambda t, p: self._inbox.put((t, p)))

    def start(self) -> None:
        self.transport.connect()

    def tick(self, now: float) -> None:
        while True:
            try:
                topic, payload = self._inbox.get_nowait()
            except queue.Empty:
                break
            try:
                msg = json.loads(payload)
            except ValueError:
                continue
            if not isinstance(msg, dict):
                continue
            if topic == STATE_TOPIC:
                self.policy.on_state_snapshot(msg)
            else:
                self.policy.on_event(msg, now)

        self._power(now)
        for reason in self.policy.due(now):
            self._capture(reason)
        if not self.policy.camera_wanted and self.source.is_open:
            self.source.close()
            self.log("[camera] closed (system disarmed)")

        if now >= self._next_prune:
            removed = self.store.prune(self.wall())
            if removed:
                self.log(f"[camera] retention: deleted {len(removed)} old snapshot(s)")
            self._next_prune = now + PRUNE_EVERY

    def _power(self, now: float) -> None:
        if self.policy.camera_wanted and not self.source.is_open:
            try:
                self.source.open()
                self._camera_failed = False
                self.log(f"[camera] open (system {self.policy.state})")
            except Exception as e:  # noqa: BLE001 - any camera failure must be reported
                if not self._camera_failed:
                    self._camera_failed = True
                    self._announce({"type": "camera_error", "error": str(e)[:200]})
                    self.log(f"[camera] ERROR {e}")

    def _capture(self, reason: str) -> None:
        if not self.source.is_open:
            return
        try:
            jpeg = self.source.latest_jpeg()
        except Exception as e:  # noqa: BLE001
            self._announce({"type": "camera_error", "error": str(e)[:200]})
            self.log(f"[camera] capture failed: {e}")
            return
        ts = self.wall()
        path, digest = self.store.save(jpeg, reason, ts)
        rel = str(path.relative_to(self.store.root))
        msg = {"type": "snapshot", "ts": round(ts, 3), "path": rel, "sha256": digest, "reason": reason, "bytes": len(jpeg)}
        self.saved.append(msg)
        self._announce(msg)
        self.log(f"[camera] snapshot {rel} ({len(jpeg) // 1024} KB)")

    def _announce(self, msg: dict) -> None:
        self.transport.publish(SNAPSHOTS_TOPIC, json.dumps(msg))
