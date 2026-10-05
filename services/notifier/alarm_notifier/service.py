"""Notifier: follows alarm/events, turns them into alerts, waits briefly for
a matching snapshot to attach, and delivers with retries.
"""

from __future__ import annotations

import json
import queue
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .ntfy import SendError
from .rules import Alert, Rules

EVENTS_TOPIC = "alarm/events"
SNAPSHOT_WAIT = 2.5  # seconds an alarm alert waits for its first photo
RETRY_MAX_DELAY = 60.0
GIVE_UP_AFTER = 3600.0


@dataclass
class _Pending:
    alert: Alert
    created: float
    next_try: float
    attempts: int = 0


class NotifierService:
    def __init__(
        self,
        backend,
        transport,
        snapshots_dir: Path | None = None,
        rules: Rules | None = None,
        log: Callable[[str], None] = print,
    ):
        self.backend = backend
        self.transport = transport
        self.snapshots_dir = Path(snapshots_dir) if snapshots_dir else None
        self.rules = rules or Rules()
        self.log = log
        self.sent: list[Alert] = []
        self._inbox: queue.SimpleQueue = queue.SimpleQueue()
        self._waiting: list[tuple[float, Alert]] = []  # (deadline, alert) waiting for a snapshot
        self._outbox: list[_Pending] = []
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
            if isinstance(e, dict):
                self._event(e, now)

        still_waiting = []
        for deadline, alert in self._waiting:
            if now >= deadline:
                self._queue(alert, now)  # no photo in time: send text only
            else:
                still_waiting.append((deadline, alert))
        self._waiting = still_waiting
        self._deliver(now)

    def _event(self, e: dict, now: float) -> None:
        if e.get("type") == "snapshot":
            self._attach(e, now)
            return
        alert = self.rules.alert_for(e, now)
        if alert is None:
            return
        if alert.wait_for_snapshot and self.snapshots_dir:
            self._waiting.append((now + SNAPSHOT_WAIT, alert))
        else:
            self._queue(alert, now)

    def _attach(self, snap: dict, now: float) -> None:
        reason, path = str(snap.get("reason", "")), str(snap.get("path", ""))
        for i, (_, alert) in enumerate(self._waiting):
            if reason.startswith(alert.wait_for_snapshot or "\0"):
                image = (self.snapshots_dir / path).resolve()
                if self.snapshots_dir.resolve() in image.parents:  # no path tricks
                    alert.image = image
                del self._waiting[i]
                self._queue(alert, now)
                return

    def _queue(self, alert: Alert, now: float) -> None:
        self._outbox.append(_Pending(alert, now, now))

    def _deliver(self, now: float) -> None:
        keep = []
        for p in self._outbox:
            if now < p.next_try:
                keep.append(p)
                continue
            p.attempts += 1
            try:
                self.backend.send(p.alert)
            except SendError as e:
                if e.permanent or now - p.created > GIVE_UP_AFTER:
                    self.log(f"[notifier] DROPPED '{p.alert.title}' after {p.attempts} attempt(s): {e}")
                    continue
                delay = min(RETRY_MAX_DELAY, 2 ** (p.attempts - 1))
                p.next_try = now + delay
                self.log(f"[notifier] send failed ({e}), retry in {delay:g}s")
                keep.append(p)
                continue
            self.sent.append(p.alert)
            photo = f" + {p.alert.image.name}" if p.alert.image else ""
            self.log(f"[notifier] sent [{p.alert.priority}] {p.alert.title}: {p.alert.message}{photo}")
        self._outbox = keep
