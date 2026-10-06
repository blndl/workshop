"""Wires the state machine to the nodes (via the protocol Hub) and to the
other Pi services (via MQTT topics on the same broker).

    alarm/v1/<node>/up|down   encrypted node traffic (protocol/spec.md)
    alarm/control             JSON requests: {"action": "arm"|"disarm"|"status", "code": "...", "source": "...", "req": "..."}
    alarm/events              JSON events, one per message (see README)
    alarm/state               JSON snapshot, retained
    alarm/snapshots           from the camera service; each one is re-emitted
                              as a logged 'snapshot' event (the hash chain then
                              covers the image's sha256)
"""

from __future__ import annotations

import json
import queue
import time
from typing import Callable

from alarm_protocol.hub import SECURITY_EVENTS, Hub, parse_topic

from .eventlog import EventLog
from .machine import AlarmMachine

CONTROL_TOPIC = "alarm/control"
EVENTS_TOPIC = "alarm/events"
STATE_TOPIC = "alarm/state"
SNAPSHOTS_TOPIC = "alarm/snapshots"
KEEPALIVE_INTERVAL = 5.0
STATE_INTERVAL = 1.0  # alarm/state is also republished this often, for live metrics
MAX_CONTROL_BYTES = 512
UNLOGGED = {"status", "control_done"}  # replies, not things that happened


class AlarmService:
    def __init__(
        self,
        keys: dict[str, bytes],
        machine: AlarmMachine,
        transport,
        log: Callable[[str], None] = print,
        wall: Callable[[], float] = time.time,
        eventlog: EventLog | None = None,
    ):
        self.hub = Hub(keys)
        self.machine = machine
        self.transport = transport
        self.log = log
        self.wall = wall
        self.eventlog = eventlog
        self.published: list[dict] = []  # every event, for tests
        self._own_events: list[dict] = []
        if eventlog and not eventlog.startup_check.ok:
            problems = eventlog.startup_check.problems
            self._own_events.append({"type": "log_tampered", "problems": problems[:10], "count": len(problems)})
        self._inbox: queue.SimpleQueue = queue.SimpleQueue()
        self._next_keepalive: dict[str, float] = {}
        self._sent_outputs: dict[str, dict[str, str]] = {}
        self._cmd_id = 0
        self._next_state = 0.0
        for pattern in ("alarm/v1/+/up", "alarm/v1/+/status", CONTROL_TOPIC, SNAPSHOTS_TOPIC):
            transport.subscribe(pattern, lambda t, p: self._inbox.put((t, p)))

    def start(self) -> None:
        self.transport.connect()

    def tick(self, now: float) -> None:
        while True:
            try:
                topic, payload = self._inbox.get_nowait()
            except queue.Empty:
                break
            if topic == CONTROL_TOPIC:
                self._control(payload, now)
            elif topic == SNAPSHOTS_TOPIC:
                self._snapshot(payload)
            else:
                self._from_node(topic, payload, now)

        for e in self.hub.check_links(now):
            self.machine.link_lost(e.node, now)
        self.machine.tick(now)
        self._sync_outputs(now)
        self._flush(now)
        if now >= self._next_state:
            self._publish_state(now)

    # --- node traffic ---------------------------------------------------

    def _from_node(self, topic: str, payload: bytes, now: float) -> None:
        parsed = parse_topic(topic)
        if parsed is None:
            return
        node, kind = parsed
        if kind == "status":
            return  # unauthenticated hint only; the watchdog decides
        result = self.hub.receive(node, payload, now)
        for t, reply in result.replies:
            self.transport.publish(t, reply)
        for e in result.events:
            if e.kind == "msg":
                self.machine.node_online(node, now)
                self.machine.heard(node, e.message.fields, now)
                if e.message.type in ("HB", "EVT"):
                    self.machine.sensor(node, e.message.fields, now)
            elif e.kind == "session_started":
                self._sent_outputs.pop(node, None)  # resend outputs on the new session
            elif e.kind in SECURITY_EVENTS:
                self.machine.security(node, e.kind, e.detail, now)

    def _sync_outputs(self, now: float) -> None:
        wanted = self.machine.outputs()
        for node in self.hub.nodes():
            if not self.hub.has_session(node):
                continue
            if self._sent_outputs.get(node) != wanted:
                self._send(node, wanted)
                self._sent_outputs[node] = wanted
                self._next_keepalive[node] = now + KEEPALIVE_INTERVAL
            elif now >= self._next_keepalive.get(node, 0.0):
                self._send(node, wanted, keepalive=True)  # repeats outputs in case a CMD was lost
                self._next_keepalive[node] = now + KEEPALIVE_INTERVAL

    def _send(self, node: str, fields: dict[str, str], keepalive: bool = False) -> None:
        if keepalive:
            cmd_id = "0"
        else:
            self._cmd_id += 1
            cmd_id = str(self._cmd_id)
        out = self.hub.send(node, "CMD", {"id": cmd_id, **fields})
        if out:
            self.transport.publish(*out)

    # --- control requests -------------------------------------------------

    def _control(self, payload: bytes, now: float) -> None:
        try:
            if len(payload) > MAX_CONTROL_BYTES:
                raise ValueError("too large")
            req = json.loads(payload)
            if not isinstance(req, dict):
                raise ValueError("not an object")
            action = req.get("action")
            source = str(req.get("source", "unknown"))[:32]
            code = req.get("code", "")
            self.machine.request = str(req["req"])[:32] if "req" in req else None
        except (ValueError, KeyError) as e:
            self.log(f"[alarm] bad control message: {e}")
            return
        try:
            if action == "arm":
                self.machine.arm(code, now, source)
            elif action == "disarm":
                self.machine.disarm(code, now, source)
            elif action == "status":
                self.machine.status(now)
            else:
                self.log(f"[alarm] unknown control action {action!r}")
            # Every request ends with this, so callers know it was handled
            # and a duress disarm looks exactly like a normal one.
            self.machine.control_done(str(action)[:16])
        finally:
            self._flush(now)
            self.machine.request = None

    def _snapshot(self, payload: bytes) -> None:
        try:
            msg = json.loads(payload)
            if msg.get("type") == "camera_error":
                self._own_events.append({"type": "camera_error", "error": str(msg.get("error", ""))[:200]})
                return
            path, digest, reason = msg["path"], msg["sha256"], msg["reason"]
            if not (isinstance(path, str) and len(path) <= 200 and ".." not in path):
                raise ValueError("bad path")
            if not (isinstance(digest, str) and len(digest) == 64 and all(c in "0123456789abcdef" for c in digest)):
                raise ValueError("bad sha256")
        except (ValueError, KeyError, TypeError, AttributeError) as e:
            self.log(f"[alarm] bad snapshot message: {e}")
            return
        self._own_events.append({"type": "snapshot", "path": path, "sha256": digest, "reason": str(reason)[:40]})

    # --- publishing -------------------------------------------------------

    def _flush(self, now: float) -> None:
        events, self._own_events = self._own_events + self.machine.drain(), []
        if not events:
            return
        ts = round(self.wall(), 3)
        for e in events:
            e = {"ts": ts, **e}
            if self.eventlog and e["type"] not in UNLOGGED:
                e["seq"] = self.eventlog.seq + 1
                self.eventlog.append(e)
            self.published.append(e)
            self.transport.publish(EVENTS_TOPIC, json.dumps(e))
            self._log_event(e)
        self._publish_state(now)

    def _publish_state(self, now: float) -> None:
        state = {"ts": round(self.wall(), 3), **self.machine.snapshot(now)}
        if self.eventlog:
            # Published so a copy kept elsewhere can detect a truncated log.
            state["log"] = {"seq": self.eventlog.seq, "head": self.eventlog.head}
        self.transport.publish(STATE_TOPIC, json.dumps(state), retain=True)
        self._next_state = now + STATE_INTERVAL

    def _log_event(self, e: dict) -> None:
        t = e["type"]
        if t == "state":
            extra = f" (in {e['delay']:g}s)" if "delay" in e else ""
            self.log(f"[alarm] {e['prev'].upper()} -> {e['state'].upper()}: {e['reason']}{extra}")
        elif t in UNLOGGED:
            return
        else:
            fields = ", ".join(f"{k}={v}" for k, v in e.items() if k not in ("ts", "type", "req"))
            self.log(f"[alarm] {t}: {fields}")
