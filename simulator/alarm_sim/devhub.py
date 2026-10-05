"""Minimal hub for developing against the simulator.

Runs the protocol's Hub logic over a transport and prints what happens.
services/alarm-core replaces this with the real state machine.
"""

from __future__ import annotations

import queue
from typing import Callable

from alarm_protocol.hub import SECURITY_EVENTS, Hub, HubEvent, parse_topic

KEEPALIVE_INTERVAL = 5.0


class DevHub:
    def __init__(self, keys: dict[str, bytes], transport, log: Callable[[str], None] = print, quiet_hb: bool = True):
        self.hub = Hub(keys)
        self.transport = transport
        self.log = log
        self.quiet_hb = quiet_hb
        self.events: list[HubEvent] = []
        self._inbox: queue.SimpleQueue = queue.SimpleQueue()
        self._next_keepalive: dict[str, float] = {}
        transport.subscribe("alarm/v1/+/up", lambda t, p: self._inbox.put((t, p)))
        transport.subscribe("alarm/v1/+/status", lambda t, p: self._inbox.put((t, p)))

    def start(self) -> None:
        self.transport.connect()

    def tick(self, now: float) -> None:
        while True:
            try:
                topic, payload = self._inbox.get_nowait()
            except queue.Empty:
                break
            parsed = parse_topic(topic)
            if parsed is None:
                continue
            node, kind = parsed
            if kind == "status":
                self.log(f"[hub] {node} status: {payload.decode('ascii', 'replace')} (unauthenticated hint)")
                continue
            result = self.hub.receive(node, payload, now)
            for topic_out, reply in result.replies:
                self.transport.publish(topic_out, reply)
            for event in result.events:
                self._record(event)

        for event in self.hub.check_links(now):
            self._record(event)

        for node in self.hub.nodes():
            if self.hub.has_session(node) and now >= self._next_keepalive.get(node, 0.0):
                out = self.hub.send(node, "CMD", {"id": "0"})
                if out:
                    self.transport.publish(*out)
                self._next_keepalive[node] = now + KEEPALIVE_INTERVAL

    def command(self, node: str, fields: dict[str, str]) -> bool:
        out = self.hub.send(node, "CMD", fields)
        if out:
            self.transport.publish(*out)
        return out is not None

    def kinds(self) -> set[str]:
        return {e.kind for e in self.events}

    def _record(self, e: HubEvent) -> None:
        self.events.append(e)
        if e.kind == "msg":
            m = e.message
            if m.type == "HB" and self.quiet_hb:
                return
            if m.type == "ACK" and m.fields.get("id") == "0":
                return
            self.log(f"[hub] {e.node} {m.type} #{m.ctr} {m.fields}")
        elif e.kind in SECURITY_EVENTS:
            self.log(f"[hub] !! SECURITY {e.kind.upper()} from {e.node}: {e.detail}")
        elif e.kind in ("link_lost", "link_restored"):
            self.log(f"[hub] !! {e.kind.upper()} {e.node} {e.detail}")
        else:
            self.log(f"[hub] {e.kind} {e.node} {e.detail}".rstrip())
