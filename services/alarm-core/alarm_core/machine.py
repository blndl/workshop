"""The alarm state machine. Pure logic: no I/O, time passed in as `now`.

    DISARMED --arm--> ARMING --exit delay--> ARMED --door/pir--> ENTRY_DELAY --entry delay--> TRIGGERED
        ^                                                                                        |
        +------------------------------------- disarm (any state) ------------------------------+

    lid opened while not disarmed           -> TRIGGERED immediately (tamper)
    lid opened while disarmed               -> 'tamper' event only (maintenance is allowed)
    node link lost while arming/armed/entry -> TRIGGERED immediately (fail-secure)
    duress code                             -> disarms like a normal code, plus a silent 'duress' event

Every input appends events to `self.events`; the service publishes them.
"""

from __future__ import annotations

from dataclasses import dataclass

from .codes import CodeChecker

DISARMED, ARMING, ARMED, ENTRY_DELAY, TRIGGERED = "disarmed", "arming", "armed", "entry_delay", "triggered"
ENTRY_SENSORS = ("door", "pir")
TAMPER_SENSORS = ("lid",)
SENSORS = ENTRY_SENSORS + TAMPER_SENSORS
LED = {DISARMED: "off", ARMING: "armed", ARMED: "armed", ENTRY_DELAY: "armed", TRIGGERED: "alarm"}


@dataclass
class Timing:
    exit_delay: float = 30.0
    entry_delay: float = 30.0
    siren_max: float = 180.0  # French rules cap outdoor sirens at 3 minutes


class AlarmMachine:
    def __init__(self, nodes: list[str], codes: CodeChecker, timing: Timing | None = None, now: float = 0.0):
        self.codes = codes
        self.timing = timing or Timing()
        self.state = DISARMED
        self.since = now
        self.reason = "startup"
        self.node: str | None = None  # node that caused the current state, if any
        self.siren = False
        self.online = {n: False for n in nodes}
        self.sensors: dict[str, dict[str, str]] = {n: {} for n in nodes}
        self.telemetry: dict[str, dict] = {n: {} for n in nodes}  # rssi, uptime, last_seen
        self.security_counts: dict[str, dict[str, int]] = {n: {} for n in nodes}
        self.events: list[dict] = []
        self.request: str | None = None  # set by the service so replies can be matched
        self._deadline: float | None = None
        self._siren_until: float | None = None

    # --- outputs --------------------------------------------------------

    def outputs(self) -> dict[str, str]:
        return {"buzzer": "1" if self.siren else "0", "led": LED[self.state]}

    def snapshot(self, now: float) -> dict:
        return {
            "state": self.state,
            "reason": self.reason,
            "node": self.node,
            "siren": self.siren,
            "deadline_in": round(max(0.0, self._deadline - now), 1) if self._deadline else None,
            "nodes": {n: self._node_snapshot(n, now) for n in self.online},
        }

    def _node_snapshot(self, node: str, now: float) -> dict:
        t = self.telemetry[node]
        return {
            "online": self.online[node],
            "sensors": dict(self.sensors[node]),
            "rssi": t.get("rssi"),
            "uptime": t.get("uptime"),
            "seen_ago": round(now - t["last_seen"], 1) if "last_seen" in t else None,
            "security": dict(self.security_counts[node]),
        }

    def heard(self, node: str, fields: dict[str, str], now: float) -> None:
        """Record link metrics from any valid message (rssi/up come with heartbeats)."""
        if node not in self.telemetry:
            return
        t = self.telemetry[node]
        t["last_seen"] = now
        for key, name in (("rssi", "rssi"), ("up", "uptime")):
            try:
                t[name] = int(fields[key])
            except (KeyError, ValueError):
                pass

    def drain(self) -> list[dict]:
        out, self.events = self.events, []
        return out

    def _emit(self, type: str, **fields) -> None:
        event = {"type": type, **fields}
        if self.request:
            event["req"] = self.request
        self.events.append(event)

    def _set_state(self, new: str, now: float, reason: str, node: str | None = None) -> None:
        prev, self.state, self.since, self.reason, self.node = self.state, new, now, reason, node
        self._deadline = None
        if new == ARMING:
            self._deadline = now + self.timing.exit_delay
        elif new == ENTRY_DELAY:
            self._deadline = now + self.timing.entry_delay
        elif new == TRIGGERED:
            self.siren = True
            self._siren_until = now + self.timing.siren_max
        elif new == DISARMED:
            self.siren = False
            self._siren_until = None
        fields = {"state": new, "prev": prev, "reason": reason}
        if node:
            fields["node"] = node
        if self._deadline is not None:
            fields["delay"] = self._deadline - now
        self._emit("state", **fields)

    def status(self, now: float) -> None:
        self._emit("status", **self.snapshot(now))

    def control_done(self, action: str) -> None:
        self._emit("control_done", action=action)

    # --- user actions ---------------------------------------------------

    def _check_code(self, code: str, now: float, action: str, source: str) -> str | None:
        result = self.codes.check(code, now)
        if result in ("user", "duress"):
            if result == "duress":
                self._emit("duress", action=action, source=source)
            return result
        if result == "lockout":
            self._emit("code_lockout", action=action, source=source, seconds=self.codes.lockout)
        elif result == "locked":
            self._emit("code_locked", action=action, source=source)
        else:
            self._emit("bad_code", action=action, source=source)
        return None

    def arm(self, code: str, now: float, source: str = "unknown") -> bool:
        if self._check_code(code, now, "arm", source) is None:
            return False
        problems = []
        if self.state != DISARMED:
            problems.append(f"already {self.state}")
        problems += [f"{n} offline" for n, up in self.online.items() if not up]
        problems += [f"{n} {s} open" for n, ss in self.sensors.items() for s in TAMPER_SENSORS if ss.get(s) == "1"]
        if problems:
            self._emit("arm_refused", source=source, problems=problems)
            return False
        self._set_state(ARMING, now, f"armed by {source}")
        return True

    def disarm(self, code: str, now: float, source: str = "unknown") -> bool:
        # A duress disarm must look exactly like a normal one to anyone watching.
        if self._check_code(code, now, "disarm", source) is None:
            return False
        if self.state != DISARMED:
            self._set_state(DISARMED, now, f"disarmed by {source}")
        return True

    # --- inputs from nodes ----------------------------------------------

    def node_online(self, node: str, now: float) -> None:
        if node in self.online and not self.online[node]:
            self.online[node] = True
            self._emit("node_online", node=node)

    def link_lost(self, node: str, now: float) -> None:
        if node not in self.online:
            return
        self.online[node] = False
        self._emit("link_lost", node=node)
        if self.state in (ARMING, ARMED, ENTRY_DELAY):
            self._set_state(TRIGGERED, now, "link_lost", node)

    def security(self, node: str, kind: str, detail: str, now: float) -> None:
        if node in self.security_counts:
            counts = self.security_counts[node]
            counts[kind] = counts.get(kind, 0) + 1
        self._emit("security", node=node, kind=kind, detail=detail)

    def sensor(self, node: str, fields: dict[str, str], now: float) -> None:
        if node not in self.sensors:
            return
        for name in SENSORS:
            value = fields.get(name)
            old = self.sensors[node].get(name)
            if value not in ("0", "1") or value == old:
                continue
            self.sensors[node][name] = value
            if old is None and value == "0":
                continue  # first report from this node, nothing changed
            self._emit("sensor", node=node, sensor=name, value=value)
            if value == "1":
                self._react(node, name, now)

    def _react(self, node: str, name: str, now: float) -> None:
        if name in TAMPER_SENSORS:
            if self.state == DISARMED:
                self._emit("tamper", node=node, sensor=name)
            elif self.state != TRIGGERED:
                self._set_state(TRIGGERED, now, f"tamper:{name}", node)
        elif self.state == ARMED:
            self._set_state(ENTRY_DELAY, now, name, node)

    # --- timers ---------------------------------------------------------

    def tick(self, now: float) -> None:
        if self._deadline is not None and now >= self._deadline:
            if self.state == ARMING:
                self._set_state(ARMED, now, "exit delay over")
            elif self.state == ENTRY_DELAY:
                self._set_state(TRIGGERED, now, f"{self.reason} (not disarmed in time)", self.node)
        if self.siren and self._siren_until is not None and now >= self._siren_until:
            self.siren = False
            self._emit("siren_timeout", seconds=self.timing.siren_max)
