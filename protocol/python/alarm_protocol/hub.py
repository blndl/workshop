"""Hub-side session management (spec sections 5 and 7).

Pure logic, no I/O: feed it payloads with `receive`, publish what it returns.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Callable

from .codec import (
    SEALED_TYPES,
    UP_TYPES,
    AuthFail,
    Channel,
    Malformed,
    Message,
    Replay,
    UnknownSession,
    b64d,
    b64e,
    derive_session,
    peek,
    sealed_header,
    sign,
    verify_signed,
)

HELLO_MIN_INTERVAL = 1.0
LINK_TIMEOUT = 3.0

# Event kinds. The ones in SECURITY_EVENTS go to the audit log.
SECURITY_EVENTS = {"auth_fail", "replay"}


def up_topic(node: str) -> str:
    return f"alarm/v1/{node}/up"


def down_topic(node: str) -> str:
    return f"alarm/v1/{node}/down"


def status_topic(node: str) -> str:
    return f"alarm/v1/{node}/status"


def parse_topic(topic: str) -> tuple[str, str] | None:
    """'alarm/v1/door-1/up' -> ('door-1', 'up')."""
    parts = topic.split("/")
    if len(parts) != 4 or parts[:2] != ["alarm", "v1"]:
        return None
    return parts[2], parts[3]


@dataclass(frozen=True)
class HubEvent:
    kind: str  # msg, session_pending, session_started, link_lost, link_restored,
    #            malformed, auth_fail, replay, unknown_session, rate_limited, unknown_node
    node: str
    message: Message | None = None
    detail: str = ""


@dataclass
class _Node:
    master: bytes
    current: Channel | None = None
    pending: Channel | None = None
    pending_nn: bytes | None = None
    pending_welcome: str | None = None
    last_hello: float = float("-inf")
    last_valid: float | None = None
    link_up: bool = False


@dataclass
class Received:
    events: list[HubEvent] = field(default_factory=list)
    replies: list[tuple[str, str]] = field(default_factory=list)  # (topic, payload)


class Hub:
    def __init__(self, keys: dict[str, bytes], rng: Callable[[int], bytes] = os.urandom):
        self._nodes = {node: _Node(master) for node, master in keys.items()}
        self._rng = rng

    def nodes(self) -> list[str]:
        return list(self._nodes)

    def has_session(self, node: str) -> bool:
        n = self._nodes.get(node)
        return n is not None and n.current is not None

    def receive(self, node: str, payload: bytes | str, now: float) -> Received:
        out = Received()
        state = self._nodes.get(node)
        if state is None:
            out.events.append(HubEvent("unknown_node", node))
            return out
        try:
            mtype, _ = peek(payload)
            if mtype not in UP_TYPES:
                raise Malformed(f"{mtype} not allowed upstream")
            if mtype in SEALED_TYPES:
                self._sealed(node, state, payload, now, out)
            else:
                self._hello(node, state, payload, now, out)
        except Malformed as e:
            out.events.append(HubEvent("malformed", node, detail=str(e)))
        except AuthFail as e:
            out.events.append(HubEvent("auth_fail", node, detail=str(e)))
        except Replay as e:
            out.events.append(HubEvent("replay", node, detail=str(e)))
        except UnknownSession as e:
            out.events.append(HubEvent("unknown_session", node, detail=str(e)))
        return out

    def _hello(self, node: str, s: _Node, payload, now: float, out: Received) -> None:
        msg = verify_signed(s.master, node, payload)
        nn = b64d(msg.fields.get("nn", ""))
        if len(nn) != 16:
            raise Malformed("nn must be 16 bytes")
        if now - s.last_hello < HELLO_MIN_INTERVAL:
            out.events.append(HubEvent("rate_limited", node))
            return
        s.last_hello = now
        if nn == s.pending_nn and s.pending_welcome:
            out.replies.append((down_topic(node), s.pending_welcome))
            return
        pn = self._rng(16)
        s.pending = Channel(derive_session(s.master, node, nn, pn), node, "hub")
        s.pending_nn = nn
        s.pending_welcome = sign(s.master, node, "WELCOME", {"nn": b64e(nn), "pn": b64e(pn)})
        out.replies.append((down_topic(node), s.pending_welcome))
        out.events.append(HubEvent("session_pending", node, msg, detail=msg.fields.get("fw", "")))

    def _sealed(self, node: str, s: _Node, payload, now: float, out: Received) -> None:
        _, sid, _, _ = sealed_header(payload)
        if s.current and sid == s.current.keys.sid:
            msg = s.current.open(payload)
        elif s.pending and sid == s.pending.keys.sid:
            msg = s.pending.open(payload)
            s.current, s.pending, s.pending_nn, s.pending_welcome = s.pending, None, None, None
            out.events.append(HubEvent("session_started", node, detail=sid))
        else:
            raise UnknownSession(sid)
        if not s.link_up and s.last_valid is not None:
            out.events.append(HubEvent("link_restored", node))
        s.link_up = True
        s.last_valid = now
        out.events.append(HubEvent("msg", node, msg))

    def send(self, node: str, mtype: str, fields: dict[str, str]) -> tuple[str, str] | None:
        """Seal a downlink message on the current session; None if there is none."""
        s = self._nodes.get(node)
        if s is None or s.current is None:
            return None
        return down_topic(node), s.current.seal(mtype, fields)

    def check_links(self, now: float) -> list[HubEvent]:
        events = []
        for node, s in self._nodes.items():
            if s.link_up and s.last_valid is not None and now - s.last_valid > LINK_TIMEOUT:
                s.link_up = False
                events.append(HubEvent("link_lost", node, detail=f"{now - s.last_valid:.1f}s silent"))
        return events
