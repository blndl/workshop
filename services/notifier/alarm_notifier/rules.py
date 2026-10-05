"""Which alarm-core events become phone alerts. Pure logic.

Priorities follow ntfy: 1 min, 2 low, 3 default, 4 high, 5 urgent.
Repeats of the same non-urgent alert are throttled to one per minute.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

THROTTLE_SECONDS = 60.0


@dataclass
class Alert:
    title: str
    message: str
    priority: int = 3
    tags: list[str] = field(default_factory=list)
    image: Path | None = None
    key: str = ""
    wait_for_snapshot: str | None = None  # attach the first snapshot whose reason starts with this


def _node(e: dict) -> str:
    return f" ({e['node']})" if e.get("node") else ""


def build(e: dict) -> Alert | None:
    t = e.get("type")
    if t == "state":
        state, prev, reason = e.get("state"), e.get("prev"), e.get("reason", "")
        if state == "triggered":
            return Alert("ALARM", f"Alarm triggered: {reason}{_node(e)}", 5, ["rotating_light"],
                         wait_for_snapshot="alarm-")
        if state == "arming":
            return Alert("Arming", f"{reason.capitalize()}, active in {e.get('delay', 0):g} s.", 2, ["lock"])
        if state == "disarmed" and prev != "disarmed":
            return Alert("Disarmed", reason.capitalize() + ".", 2, ["unlock"])
        return None
    if t == "duress":
        return Alert("DURESS CODE USED",
                     f"The system was disarmed with the duress code (source: {e.get('source', '?')}). "
                     "Someone may be forced to disarm it. Treat as an emergency.",
                     5, ["sos"], wait_for_snapshot="duress")
    if t == "tamper":
        return Alert("Tamper", f"Enclosure {e.get('sensor', 'lid')} opened while disarmed{_node(e)}.", 4, ["warning"])
    if t == "link_lost":
        return Alert("Sensor offline", f"No signal from {e.get('node')} for 3 s (jamming, power cut or damage?).",
                     4, ["warning"])
    if t == "security":
        what = {"auth_fail": "a forged or altered", "replay": "a replayed"}.get(e.get("kind"), "a suspicious")
        return Alert("Security warning", f"Rejected {what} message on {e.get('node')}'s channel. Possible attack.",
                     4, ["no_entry"])
    if t == "code_lockout":
        return Alert("Code lockout", f"Too many wrong codes ({e.get('source', '?')}): codes refused for "
                     f"{e.get('seconds', 0) / 60:g} min.", 4, ["warning"])
    if t == "log_tampered":
        problems = "; ".join(e.get("problems", [])[:3])
        return Alert("Event log tampered", f"{e.get('count', '?')} problem(s): {problems}", 5, ["skull"])
    if t == "camera_error":
        return Alert("Camera error", f"{e.get('error', 'unknown error')}", 4, ["camera"])
    if t == "arm_refused":
        return Alert("Arming refused", ", ".join(e.get("problems", [])) or "unknown reason", 3, ["warning"])
    return None


class Rules:
    def __init__(self, throttle: float = THROTTLE_SECONDS):
        self.throttle = throttle
        self._last: dict[str, float] = {}
        self._suppressed: dict[str, int] = {}

    def alert_for(self, e: dict, now: float) -> Alert | None:
        alert = build(e)
        if alert is None:
            return None
        alert.key = f"{e.get('type')}:{e.get('node', '')}:{e.get('kind', '')}:{e.get('state', '')}"
        if alert.priority >= 5:
            return alert
        last = self._last.get(alert.key)
        if last is not None and now - last < self.throttle:
            self._suppressed[alert.key] = self._suppressed.get(alert.key, 0) + 1
            return None
        self._last[alert.key] = now
        n = self._suppressed.pop(alert.key, 0)
        if n:
            alert.message += f" (+{n} similar in the last minute)"
        return alert
