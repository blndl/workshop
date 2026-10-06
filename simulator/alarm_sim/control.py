"""Remote control of a simulated node over MQTT (DEV ONLY).

    sim/<node>/cmd     JSON commands in:
                       {"cmd": "set", "sensor": "door", "value": 1}
                       {"cmd": "jam", "seconds": 6}
                       {"cmd": "reboot", "seconds": 2}
                       {"cmd": "attack", "name": "spoof", "args": {}}
    sim/<node>/status  JSON status out (retained): what the fake device is doing,
                       including its buzzer and LED, and the last command's result

These topics only exist in the simulation: a real ESP has no such channel.
"""

from __future__ import annotations

import json
import queue

from .attacks import ATTACKS
from .node import SENSORS

STATUS_INTERVAL = 1.0
MAX_CMD_BYTES = 512


def cmd_topic(node: str) -> str:
    return f"sim/{node}/cmd"


def status_topic(node: str) -> str:
    return f"sim/{node}/status"


class SimControl:
    def __init__(self, node, attacker=None, log=print):
        self.node = node
        self.attacker = attacker
        self.log = log
        self.last: dict | None = None
        self._inbox: queue.SimpleQueue = queue.SimpleQueue()
        self._next_status = 0.0
        self._last_sent: str | None = None
        node.transport.subscribe(cmd_topic(node.node_id), lambda _t, p: self._inbox.put(p))

    def tick(self, now: float) -> None:
        while True:
            try:
                payload = self._inbox.get_nowait()
            except queue.Empty:
                break
            self.last = self._apply(payload, now)
            self._next_status = now  # report the result right away
        status = json.dumps(self.status(now))
        if now >= self._next_status or status != self._last_sent:
            self.node.transport.publish(status_topic(self.node.node_id), status, retain=True)
            self._last_sent = status
            self._next_status = now + STATUS_INTERVAL

    def status(self, now: float) -> dict:
        n = self.node
        return {
            "node": n.node_id,
            "state": n.state,  # offline | handshaking | session | silent
            "session": n.channel.keys.sid if n.channel else None,
            "sensors": dict(n.sensors),
            "outputs": dict(n.outputs),
            "silent_for": round(max(0.0, n._silent_until - now), 1) if n._silent_until else 0,
            "attacks": list(ATTACKS) if self.attacker else [],
            "last_command": self.last,
        }

    def _apply(self, payload: bytes, now: float) -> dict:
        try:
            if len(payload) > MAX_CMD_BYTES:
                raise ValueError("command too large")
            c = json.loads(payload)
            if not isinstance(c, dict):
                raise ValueError("command must be a JSON object")
            kind = c.get("cmd")
            if kind == "set":
                sensor, value = c.get("sensor"), c.get("value")
                if sensor not in SENSORS or value not in (0, 1, "0", "1"):
                    raise ValueError(f"set needs sensor in {SENSORS} and value 0/1")
                self.node.set(now, **{sensor: int(value)})
            elif kind == "jam":
                self.node.jam(now, _seconds(c, 1, 60))
            elif kind == "reboot":
                self.node.reboot(now, _seconds(c, 0.5, 30, default=2))
            elif kind == "attack":
                if self.attacker is None:
                    raise ValueError("no attacker configured for this node")
                name, args = c.get("name"), c.get("args") or {}
                if name not in ATTACKS or not isinstance(args, dict):
                    raise ValueError(f"attack name must be one of {ATTACKS}")
                self.attacker.run(name, **args)
            else:
                raise ValueError(f"unknown cmd {kind!r}")
        except (ValueError, TypeError, RuntimeError) as e:
            self.log(f"[{self.node.node_id}] remote command failed: {e}")
            return {"cmd": _safe(payload), "ok": False, "error": str(e)[:200]}
        self.log(f"[{self.node.node_id}] remote command: {_safe(payload)}")
        return {"cmd": _safe(payload), "ok": True}


def _seconds(c: dict, low: float, high: float, default: float | None = None) -> float:
    value = c.get("seconds", default)
    if not isinstance(value, (int, float)) or not low <= value <= high:
        raise ValueError(f"seconds must be between {low:g} and {high:g}")
    return float(value)


def _safe(payload: bytes) -> str:
    return payload[:120].decode("utf-8", "replace")
