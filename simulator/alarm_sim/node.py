"""A fake ESP8266 sensor node that follows protocol v1 (protocol/spec.md).

Time is passed in explicitly (`now`) so tests can run on a fake clock.
Incoming messages are queued by the transport thread and handled in tick().
"""

from __future__ import annotations

import os
import queue
import random
from typing import Callable

from alarm_protocol import (
    SEALED_TYPES,
    AuthFail,
    Channel,
    Malformed,
    ProtocolError,
    Replay,
    UnknownSession,
    b64d,
    b64e,
    derive_session,
    peek,
    sign,
    verify_signed,
)
from alarm_protocol.hub import down_topic, status_topic, up_topic
from alarm_protocol.modules import ModuleSpec, door_module

FW_VERSION = "0.1.0-sim"
HB_INTERVAL = 1.0
HELLO_RETRY = 2.0
DOWNLINK_TIMEOUT = 10.0



def fmt(value: float) -> str:
    """Numeric sensor value as sent on the wire (protocol field values: digits, '.', '-')."""
    return f"{value:.1f}"


class SimNode:
    def __init__(
        self,
        node_id: str,
        master: bytes,
        transport,
        rng: Callable[[int], bytes] = os.urandom,
        log: Callable[[str], None] = print,
        module: ModuleSpec | None = None,
    ):
        # Without a description, behave like the original door module.
        self.module = module or door_module(node_id)
        self.node_id = node_id
        self.master = master
        self.transport = transport
        self.rng = rng
        self.log = log
        # Numeric sensors drift around a setpoint (their 'normal' value until changed).
        self._setpoint = {n: (s.normal or 0.0) for n, s in self.module.sensors.items() if not s.binary}
        self.sensors = {n: ("0" if s.binary else fmt(self._setpoint[n])) for n, s in self.module.sensors.items()}
        self.outputs = {"buzzer": "0", "led": "off"}
        self.security_events: list[str] = []  # rejected downlink messages
        self.state = "offline"  # offline | handshaking | session | silent
        self.channel: Channel | None = None
        self._inbox: queue.SimpleQueue = queue.SimpleQueue()
        self._nn: bytes | None = None
        self._boot_at = 0.0
        self._next_hb = 0.0
        self._next_hello = 0.0
        self._last_down = 0.0
        self._silent_until: float | None = None
        self._rssi = random.Random(node_id)

        transport.subscribe(down_topic(node_id), lambda _t, p: self._inbox.put(("msg", p)))

    # --- lifecycle ------------------------------------------------------

    def start(self) -> None:
        self.transport.connect(on_connect=lambda: self._inbox.put(("connected", None)))

    def _new_session(self, now: float) -> None:
        self.channel = None
        self._nn = self.rng(16)
        self.state = "handshaking"
        self._next_hello = now

    def reboot(self, now: float, offline_for: float = 2.0) -> None:
        self.log(f"[{self.node_id}] reboot ({offline_for:g}s offline)")
        self._go_silent(now, offline_for)
        self._boot_at = now + offline_for

    def jam(self, now: float, seconds: float) -> None:
        """Simulate Wi-Fi jamming/deauth: nothing in or out, then reconnect."""
        self.log(f"[{self.node_id}] jammed for {seconds:g}s")
        self._go_silent(now, seconds)

    def _go_silent(self, now: float, seconds: float) -> None:
        self.state = "silent"
        self.channel = None
        self._silent_until = now + seconds

    # --- sensors --------------------------------------------------------

    def set(self, now: float, **values) -> None:
        """Binary sensors: 0/1. Numeric sensors: the new reading (it then drifts around it)."""
        changed = {}
        for k, v in values.items():
            spec = self.module.sensors.get(k)
            if spec is None:
                raise ValueError(f"unknown sensor {k!r}, expected one of {sorted(self.module.sensors)}")
            if spec.binary:
                try:
                    on = float(v)
                except (TypeError, ValueError):
                    on = None
                if on not in (0.0, 1.0):
                    raise ValueError(f"{k} is on/off: use 0 or 1")
                v = str(int(on))
            else:
                try:
                    self._setpoint[k] = float(v)
                except (TypeError, ValueError) as e:
                    raise ValueError(f"{k} is numeric ({spec.unit or 'no unit'}): use a number") from e
                v = fmt(self._setpoint[k])
            if self.sensors[k] != v:
                self.sensors[k] = v
                changed[k] = v
        if changed:
            self.log(f"[{self.node_id}] sensors {changed}")
            self._send_sealed("EVT", changed)

    # --- main loop ------------------------------------------------------

    def tick(self, now: float) -> None:
        while True:
            try:
                kind, payload = self._inbox.get_nowait()
            except queue.Empty:
                break
            if kind == "connected":
                self.transport.publish(status_topic(self.node_id), "online", retain=True)
                if self.state != "silent":
                    self._boot_at = now
                    self._new_session(now)
            elif self.state != "silent":
                self._handle_down(payload, now)

        if self.state == "silent":
            if now >= self._silent_until:
                self._silent_until = None
                self._new_session(now)
            else:
                return

        if self.state == "handshaking" and now >= self._next_hello:
            self.transport.publish(
                up_topic(self.node_id),
                sign(self.master, self.node_id, "HELLO", {"fw": FW_VERSION, "nn": b64e(self._nn)}),
            )
            self._next_hello = now + HELLO_RETRY

        if self.state == "session":
            if now - self._last_down > DOWNLINK_TIMEOUT:
                self.log(f"[{self.node_id}] no downlink for {DOWNLINK_TIMEOUT:g}s, new session")
                self._new_session(now)
            elif now >= self._next_hb:
                self._heartbeat(now)

    def _heartbeat(self, now: float) -> None:
        for name, target in self._setpoint.items():  # a little noise, like a real sensor
            self.sensors[name] = fmt(target + self._rssi.uniform(-1, 1) * max(abs(target) * 0.01, 0.1))
        fields = dict(self.sensors)
        fields["up"] = str(max(0, int(now - self._boot_at)))
        fields["rssi"] = str(self._rssi.randint(-66, -55))
        self._send_sealed("HB", fields)
        self._next_hb = now + HB_INTERVAL

    def _send_sealed(self, mtype: str, fields: dict[str, str]) -> None:
        if self.state == "session" and self.channel:
            self.transport.publish(up_topic(self.node_id), self.channel.seal(mtype, fields))

    def _handle_down(self, payload: bytes, now: float) -> None:
        try:
            mtype, _ = peek(payload)
            if mtype == "WELCOME":
                self._handle_welcome(payload, now)
            elif mtype in SEALED_TYPES:
                if not self.channel:
                    return  # no session yet; hub will catch up
                msg = self.channel.open(payload)
                self._last_down = now
                self._handle_cmd(msg.fields)
            else:
                raise Malformed(f"{mtype} not allowed downstream")
        except UnknownSession:
            pass  # leftover from our previous session
        except (AuthFail, Replay) as e:
            kind = "replay" if isinstance(e, Replay) else "auth_fail"
            self.security_events.append(kind)
            self.log(f"[{self.node_id}] REJECTED downlink ({kind}): {e}")
        except ProtocolError as e:
            self.security_events.append("malformed")
            self.log(f"[{self.node_id}] dropped downlink: {e}")

    def _handle_welcome(self, payload: bytes, now: float) -> None:
        msg = verify_signed(self.master, self.node_id, payload)
        if self.state != "handshaking" or msg.fields.get("nn") != b64e(self._nn):
            return  # stale or replayed WELCOME
        pn = b64d(msg.fields.get("pn", ""))
        if len(pn) != 16:
            raise Malformed("pn must be 16 bytes")
        self.channel = Channel(derive_session(self.master, self.node_id, self._nn, pn), self.node_id, "node")
        self.state = "session"
        self._last_down = now
        self.log(f"[{self.node_id}] session {self.channel.keys.sid} established")
        self._heartbeat(now)

    def _handle_cmd(self, fields: dict[str, str]) -> None:
        cmd_id = fields.get("id", "0")
        changed = {k: v for k, v in fields.items() if k in self.outputs and self.outputs[k] != v}
        self.outputs.update(changed)
        if changed:
            self.log(f"[{self.node_id}] outputs changed {changed}")
        self._send_sealed("ACK", {"id": cmd_id, "ok": "1"})
