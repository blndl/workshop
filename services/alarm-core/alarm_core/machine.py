"""The alarm state machine. Pure logic: no I/O, time passed in as `now`.

    DISARMED --arm--> ARMING --exit delay--> ARMED --entry sensor--> ENTRY_DELAY --entry delay--> TRIGGERED
        ^                                                                                            |
        +--------------------------------------- disarm (any state) --------------------------------+

Sensors are handled by the role their module description gives them
(config/modules.yaml, alarm_protocol.modules), never by name:

    entry      active while armed                 -> ENTRY_DELAY
    instant    active while armed / entry delay   -> TRIGGERED immediately
    tamper     active while not disarmed          -> TRIGGERED immediately
               active while disarmed              -> 'tamper' event only (maintenance is allowed)
    safety     active, whatever the state         -> safety alarm: siren until silenced with a code
                                                     or the sensor clears (separate from intrusion)
    telemetry  never alarms

    module link lost while arming/armed/entry -> TRIGGERED immediately (fail-secure)
    duress code -> disarms like a normal code, plus a silent 'duress' event

Vision (sensors with `confirm: person`): when such a sensor becomes active while
armed, the machine emits 'verify' and waits for the detector's results on the
camera's verify burst. A person -> the sensor counts ('motion_confirmed'). No
person on the whole burst -> 'motion_dismissed' (a cat, a curtain). No answer
within verify_timeout -> it counts anyway ('verify_timeout'): fail-secure.

A sensor is "active" when a binary one reports 1, or a numeric one crosses
its alarm_above / alarm_below threshold.

Every input appends events to `self.events`; the service publishes them.
"""

from __future__ import annotations

from dataclasses import dataclass

from alarm_protocol.modules import ModuleSpec, door_module

from .codes import CodeChecker

DISARMED, ARMING, ARMED, ENTRY_DELAY, TRIGGERED = "disarmed", "arming", "armed", "entry_delay", "triggered"
LED = {DISARMED: "off", ARMING: "armed", ARMED: "armed", ENTRY_DELAY: "armed", TRIGGERED: "alarm"}


@dataclass
class Timing:
    exit_delay: float = 30.0
    entry_delay: float = 30.0
    siren_max: float = 180.0  # French rules cap outdoor sirens at 3 minutes
    verify_timeout: float = 8.0  # vision check; after that the sensor counts anyway
    live_view_max: float = 120.0  # camera live view while disarmed, then it turns itself off


VERIFY_SHOTS = 3  # the camera's verify burst; all must show nobody to dismiss


class AlarmMachine:
    def __init__(
        self,
        modules: dict[str, ModuleSpec] | list[str],
        codes: CodeChecker,
        timing: Timing | None = None,
        now: float = 0.0,
    ):
        # A plain list of ids means "door modules" (the original setup; used by tests).
        if not isinstance(modules, dict):
            modules = {n: door_module(n) for n in modules}
        self.modules = modules
        nodes = list(modules)
        self.codes = codes
        self.timing = timing or Timing()
        self.state = DISARMED
        self.since = now
        self.reason = "startup"
        self.node: str | None = None  # node that caused the current state, if any
        self.siren = False
        self.online = {n: False for n in nodes}
        self.sensors: dict[str, dict[str, str]] = {n: {} for n in nodes}  # last reported values
        self.active: dict[str, dict[str, bool]] = {n: {} for n in nodes}  # alarm condition per sensor
        self.safety: dict[tuple[str, str], dict] = {}  # active safety alarms: (node, sensor) -> details
        self.safety_silenced = False
        self.telemetry: dict[str, dict] = {n: {} for n in nodes}  # rssi, uptime, last_seen
        self.security_counts: dict[str, dict[str, int]] = {n: {} for n in nodes}
        self.events: list[dict] = []
        self.request: str | None = None  # set by the service so replies can be matched
        self._deadline: float | None = None
        self._siren_until: float | None = None
        self.verify: dict | None = None  # pending vision check
        self.live_until: float | None = None  # camera live view (while disarmed)

    # --- outputs --------------------------------------------------------

    def outputs(self) -> dict[str, str]:
        safety_sounding = bool(self.safety) and not self.safety_silenced
        led = "alarm" if self.safety else LED[self.state]
        return {"buzzer": "1" if self.siren or safety_sounding else "0", "led": led}

    def snapshot(self, now: float) -> dict:
        return {
            "state": self.state,
            "reason": self.reason,
            "node": self.node,
            "siren": self.siren,
            "deadline_in": round(max(0.0, self._deadline - now), 1) if self._deadline else None,
            "safety": [{"node": n, "sensor": s, **d, "since_s": round(now - d["since"], 1)}
                       for (n, s), d in self.safety.items()],
            "safety_silenced": self.safety_silenced,
            "verifying": {k: self.verify[k] for k in ("node", "sensor")} if self.verify else None,
            "live_view_s": round(self.live_until - now, 1) if self.live_until and self.live_until > now else 0,
            "nodes": {n: self._node_snapshot(n, now) for n in self.online},
        }

    def _node_snapshot(self, node: str, now: float) -> dict:
        t = self.telemetry[node]
        m = self.modules[node]
        return {
            "type": m.type,
            "name": m.name,
            "online": self.online[node],
            "sensors": dict(self.sensors[node]),
            "active": dict(self.active[node]),
            "info": {name: spec.info() for name, spec in m.sensors.items()},
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
            self.verify = None
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
        for n, actives in self.active.items():
            for s, on in actives.items():
                role = self.modules[n].sensors[s].role
                if on and role in ("tamper", "instant"):
                    problems.append(f"{n} {s} open" if role == "tamper" else f"{n} {s} active")
        problems += [f"safety alarm: {n} {s}" for n, s in self.safety]
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
        if self.safety and not self.safety_silenced:
            # The code also silences a safety alarm; it stays listed until the sensor clears.
            self.safety_silenced = True
            self._emit("safety_silenced", source=source, alarms=[f"{n} {s}" for n, s in self.safety])
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
        """Handle reported values (heartbeat snapshot or change event) for a module."""
        if node not in self.modules:
            return
        for name, spec in self.modules[node].sensors.items():
            value = fields.get(name)
            if value is None:
                continue
            active = spec.is_active(value)
            if active is None:
                continue  # malformed value: ignore it, keep the last good one
            self.sensors[node][name] = value
            if (node, name) in self.safety:
                self.safety[(node, name)]["value"] = value  # keep the live reading
            was = self.active[node].get(name)
            if was == active:
                continue
            self.active[node][name] = active
            if was is None and not active:
                continue  # first report from this module, nothing changed
            # Binary sensors: one event per change. Numeric: one per threshold crossing
            # (their values change every heartbeat and are in the snapshot instead).
            self._emit("sensor", node=node, sensor=name, value=value, active=active)
            if active:
                self._react(node, spec, value, now)
            elif spec.role == "safety":
                self._safety_clear(node, name, value)

    def _react(self, node: str, spec, value: str, now: float) -> None:
        name, role = spec.name, spec.role
        if role == "tamper":
            if self.state == DISARMED:
                self._emit("tamper", node=node, sensor=name)
            elif self.state != TRIGGERED:
                self._set_state(TRIGGERED, now, f"tamper:{name}", node)
        elif role in ("entry", "instant"):
            counts = self.state == ARMED or (role == "instant" and self.state == ENTRY_DELAY)
            if not counts:
                return
            if spec.confirm == "person":
                if self.verify is None:
                    self.verify = {"node": node, "sensor": name, "role": role,
                                   "deadline": now + self.timing.verify_timeout, "negatives": 0, "objects": {}}
                    self._emit("verify", node=node, sensor=name, timeout=self.timing.verify_timeout)
                return
            self._intrusion(node, name, role, name, now)
        elif role == "safety":
            self.safety[(node, name)] = {"kind": spec.kind, "value": value, "unit": spec.unit, "since": now}
            self.safety_silenced = False  # a new safety alarm sounds again
            self._emit("safety_alarm", node=node, sensor=name, kind=spec.kind, value=value, unit=spec.unit,
                       threshold=spec.alarm_above if spec.alarm_above is not None else spec.alarm_below)
        # telemetry: never active, nothing to do

    def _intrusion(self, node: str, sensor: str, role: str, reason: str, now: float) -> None:
        if role == "entry" and self.state == ARMED:
            self._set_state(ENTRY_DELAY, now, reason, node)
        elif role == "instant" and self.state in (ARMED, ENTRY_DELAY):
            self._set_state(TRIGGERED, now, reason, node)

    # --- vision ---------------------------------------------------------

    def detection(self, result: dict, now: float) -> None:
        """A detector result for a snapshot. Only the verify burst counts towards a pending check."""
        v = self.verify
        if v is None or not str(result.get("reason", "")).startswith("verify"):
            return
        if result.get("person"):
            self.verify = None
            self._emit("motion_confirmed", node=v["node"], sensor=v["sensor"],
                       confidence=result.get("confidence"), path=result.get("path"))
            self._intrusion(v["node"], v["sensor"], v["role"], f"{v['sensor']} (person seen)", now)
            return
        v["negatives"] += 1
        for label, n in (result.get("objects") or {}).items():
            v["objects"][label] = max(v["objects"].get(label, 0), n)
        if v["negatives"] >= VERIFY_SHOTS:
            self.verify = None
            self._emit("motion_dismissed", node=v["node"], sensor=v["sensor"], seen=v["objects"])

    def live_view(self, on: bool, now: float, source: str = "unknown") -> None:
        """Turn the camera on for viewing while disarmed (it's on anyway when armed). Logged."""
        if on:
            self.live_until = now + self.timing.live_view_max
            self._emit("live_view", on=True, seconds=self.timing.live_view_max, source=source)
        elif self.live_until is not None:
            self.live_until = None
            self._emit("live_view", on=False, source=source)

    def _safety_clear(self, node: str, name: str, value: str) -> None:
        if self.safety.pop((node, name), None) is not None:
            self._emit("safety_clear", node=node, sensor=name, value=value)
            if not self.safety:
                self.safety_silenced = False

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
        if self.verify is not None and now >= self.verify["deadline"]:
            v, self.verify = self.verify, None
            self._emit("verify_timeout", node=v["node"], sensor=v["sensor"], answers=v["negatives"])
            self._intrusion(v["node"], v["sensor"], v["role"], f"{v['sensor']} (not verified)", now)
        if self.live_until is not None and now >= self.live_until:
            self.live_until = None
            self._emit("live_view", on=False, source="timeout")
