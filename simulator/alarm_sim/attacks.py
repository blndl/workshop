"""Attacks against a node's traffic, for testing and the pentest demo.

The attacker can see and publish on the node's topics (plain MQTT over
shared Wi-Fi leaks broker passwords), but doesn't know the master key.
Use only on your own lab network.
"""

from __future__ import annotations

import os
import random
from typing import Callable

from alarm_protocol import SEALED_TYPES, Malformed, b64e, seal, sealed_header, sign
from alarm_protocol.hub import down_topic, up_topic

ATTACKS = (
    "replay",  # resend a captured message from the current session
    "replay_old",  # resend a message from an earlier session
    "replay_hello",  # resend the first captured HELLO
    "spoof",  # forge an EVT door=0 without the key
    "tamper",  # change the type in a captured header
    "forge_hello",  # HELLO signed with a wrong key
    "inject_cmd",  # forge a CMD buzzer=0 to the node ("silence the siren")
    "flood",  # junk payloads
)


class Attacker:
    def __init__(self, node_id: str, transport, log: Callable[[str], None] = print, seed: int | None = None):
        self.node_id = node_id
        self.transport = transport
        self.log = log
        self.up: list[str] = []
        self.down: list[str] = []
        self._sent: set[str] = set()
        self._rand = random.Random(seed)
        transport.subscribe(up_topic(node_id), lambda _t, p: self._capture(self.up, p))
        transport.subscribe(down_topic(node_id), lambda _t, p: self._capture(self.down, p))

    def _capture(self, into: list[str], payload: bytes) -> None:
        text = payload.decode("ascii", "replace")
        if text not in self._sent:
            into.append(text)

    def _publish(self, topic: str, payload: str) -> None:
        self._sent.add(payload)
        self.transport.publish(topic, payload)

    def _sealed(self, msgs: list[str]) -> list[tuple[str, str, int, str]]:
        """[(type, sid, ctr, payload)] for captured sealed messages."""
        out = []
        for p in msgs:
            try:
                mtype, sid, ctr, _ = sealed_header(p)
                out.append((mtype, sid, ctr, p))
            except Malformed:
                pass
        return out

    def _current_sid(self) -> str:
        sealed = self._sealed(self.up)
        if not sealed:
            raise RuntimeError("no sealed traffic captured yet")
        return sealed[-1][1]

    def run(self, kind: str, **params) -> None:
        if kind not in ATTACKS:
            raise ValueError(f"unknown attack {kind!r}, expected one of {ATTACKS}")
        getattr(self, f"_{kind}")(**params)

    def _replay(self, type: str = "EVT", index: int = -1) -> None:
        sid = self._current_sid()
        candidates = [p for t, s, _, p in self._sealed(self.up) if s == sid and t == type]
        if not candidates:
            raise RuntimeError(f"no {type} captured in session {sid}")
        payload = candidates[index]
        self.log(f"[attacker] replaying {type} #{index}: {payload[:40]}…")
        self._publish(up_topic(self.node_id), payload)

    def _replay_old(self) -> None:
        sid = self._current_sid()
        old = [p for _, s, _, p in self._sealed(self.up) if s != sid]
        if not old:
            raise RuntimeError("no traffic from an earlier session captured")
        self.log(f"[attacker] replaying message from an old session: {old[-1][:40]}…")
        self._publish(up_topic(self.node_id), old[-1])

    def _replay_hello(self) -> None:
        hellos = [p for p in self.up if p.startswith("v1|HELLO|")]
        if not hellos:
            raise RuntimeError("no HELLO captured")
        self.log("[attacker] replaying captured HELLO")
        self._publish(up_topic(self.node_id), hellos[0])

    def _spoof(self) -> None:
        sid = self._current_sid()
        last_ctr = max(c for _, s, c, _ in self._sealed(self.up) if s == sid)
        payload = seal(os.urandom(32), self.node_id, "EVT", sid, last_ctr + 1, {"door": "0"})
        self.log(f"[attacker] spoofing 'door closed' (sid {sid}, ctr {last_ctr + 1})")
        self._publish(up_topic(self.node_id), payload)

    def _tamper(self) -> None:
        sealed = [p for t, *_, p in self._sealed(self.up) if t == "HB"]
        if not sealed:
            raise RuntimeError("no HB captured")
        payload = sealed[-1].replace("|HB|", "|EVT|", 1)
        self.log("[attacker] tampering: HB header rewritten as EVT")
        self._publish(up_topic(self.node_id), payload)

    def _forge_hello(self) -> None:
        payload = sign(os.urandom(32), self.node_id, "HELLO", {"fw": "6.6.6", "nn": b64e(os.urandom(16))})
        self.log("[attacker] forging HELLO with a guessed key")
        self._publish(up_topic(self.node_id), payload)

    def _inject_cmd(self) -> None:
        sids = [s for t, s, _, _ in self._sealed(self.down) if t in SEALED_TYPES]
        sid = sids[-1] if sids else self._current_sid()
        payload = seal(os.urandom(32), self.node_id, "CMD", sid, 2**31, {"id": "99", "buzzer": "0"})
        self.log("[attacker] injecting CMD buzzer=0 to the node")
        self._publish(down_topic(self.node_id), payload)

    def _flood(self, count: int = 20) -> None:
        self.log(f"[attacker] flooding {count} junk messages")
        for _ in range(count):
            n = self._rand.randint(1, 300)
            junk = "".join(self._rand.choice("v1|HBEVT0123456789abcdef=,") for _ in range(n))
            self._publish(up_topic(self.node_id), junk)
