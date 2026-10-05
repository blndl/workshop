"""When to take pictures. Pure logic, driven by alarm-core events.

Privacy rule: the camera is only open while the system is arming, armed,
in its entry delay or triggered. While disarmed, nothing is captured.
"""

from __future__ import annotations

ACTIVE_STATES = {"arming", "armed", "entry_delay", "triggered"}
WATCH_STATES = {"armed", "entry_delay", "triggered"}  # sensor activity is photographed

BURST = (0.0, 0.7, 1.4)  # seconds after the trigger
TRIGGERED_EVERY = 5.0
TRIGGERED_FOR = 60.0
MIN_GAP = 0.5  # ignore a request this close to one already scheduled


class CapturePolicy:
    def __init__(self):
        self.state = "disarmed"
        self.pending: list[tuple[float, str]] = []  # (due time, reason), sorted
        self._periodic_until: float | None = None
        self._next_periodic = 0.0

    @property
    def camera_wanted(self) -> bool:
        return self.state in ACTIVE_STATES or bool(self.pending)

    def on_event(self, e: dict, now: float) -> None:
        t = e.get("type")
        if t == "state":
            self.state = e.get("state", self.state)
            reason = _slug(e.get("reason", ""))
            if self.state == "entry_delay":
                self._burst(now, f"entry-{reason}")
            elif self.state == "triggered":
                self._burst(now, f"alarm-{reason}")
                self._periodic_until = now + TRIGGERED_FOR
                self._next_periodic = now + TRIGGERED_EVERY
            if self.state != "triggered":
                self._periodic_until = None
        elif t == "sensor" and e.get("value") == "1" and self.state in WATCH_STATES:
            self._add(now, f"{e.get('sensor', 'sensor')}")
        elif t == "duress":
            self._burst(now, "duress")  # silently, before the disarm closes the camera

    def on_state_snapshot(self, snap: dict) -> None:
        """Initial state from the retained alarm/state message."""
        self.state = snap.get("state", self.state)

    def due(self, now: float) -> list[str]:
        """Reasons for captures due now (removes them from pending)."""
        if self._periodic_until is not None:
            if now >= self._periodic_until:
                self._periodic_until = None
            elif now >= self._next_periodic:
                self._add(now, "alarm-followup")
                self._next_periodic = now + TRIGGERED_EVERY
        reasons = [r for t, r in self.pending if t <= now]
        self.pending = [(t, r) for t, r in self.pending if t > now]
        return reasons

    def _burst(self, now: float, reason: str) -> None:
        for i, dt in enumerate(BURST):
            self._add(now + dt, f"{reason}-{i + 1}", force=True)

    def _add(self, at: float, reason: str, force: bool = False) -> None:
        if not force and any(abs(t - at) < MIN_GAP for t, _ in self.pending):
            return
        self.pending.append((at, reason))
        self.pending.sort()


def _slug(text: str) -> str:
    text = text.split("(")[0]  # "door (not disarmed in time)" -> "door"
    keep = "".join(c if c.isalnum() else "-" for c in text.lower())
    return "-".join(p for p in keep.split("-") if p)[:24] or "event"
