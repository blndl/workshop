"""MQTT bridge between the web API and alarm-core.

Keeps the latest alarm/state and a ring buffer of recent alarm/events, and
turns a control request into an awaitable: publish to alarm/control, collect
the events alarm-core tags with our request id, finish on 'control_done'.

MQTT callbacks run on the transport's thread; results are handed to the
asyncio loop with call_soon_threadsafe.
"""

from __future__ import annotations

import asyncio
import json
import secrets
import threading
import time
from collections import deque

from .database import save_event


CONTROL_TOPIC = "alarm/control"
EVENTS_TOPIC = "alarm/events"
STATE_TOPIC = "alarm/state"
SIM_STATUS_TOPIC = "sim/+/status"  # dev only: simulated nodes

# Never stored, never shown: whoever is at the screen may be the one forcing the disarm.
HIDDEN = {"duress"}

# Replies to requests, not things that happened.
REPLIES = {"status", "control_done"}


class AlarmCoreTimeout(Exception):
    pass


class _Waiter:
    def __init__(self, loop: asyncio.AbstractEventLoop):
        self.loop = loop
        self.future: asyncio.Future = loop.create_future()
        self.events: list[dict] = []


class Bridge:
    def __init__(
        self,
        transport,
        max_events: int = 500,
        timeout: float = 3.0,
        sim: bool = False,
    ):
        self.transport = transport
        self.timeout = timeout
        self.state: dict | None = None
        self.state_received_at: float | None = None
        self.connected = False
        self._events: deque[dict] = deque(maxlen=max_events)
        self._waiters: dict[str, _Waiter] = {}
        self._lock = threading.Lock()
        self.sim = sim
        self.sim_nodes: dict[str, dict] = {}

        transport.subscribe(STATE_TOPIC, self._on_state)
        transport.subscribe(EVENTS_TOPIC, self._on_event)

        if sim:
            transport.subscribe(SIM_STATUS_TOPIC, self._on_sim_status)

    def start(self) -> None:
        self.transport.connect(on_connect=self._on_connect)

    def stop(self) -> None:
        self.transport.close()

    def _on_connect(self) -> None:
        self.connected = True

    # --- incoming (transport thread) ---------------------------------------

    def _on_state(self, _topic: str, payload: bytes) -> None:
        try:
            state = json.loads(payload)
        except ValueError:
            return

        if isinstance(state, dict):
            with self._lock:
                self.state = state
                self.state_received_at = time.time()

    def _on_sim_status(self, topic: str, payload: bytes) -> None:
        try:
            status = json.loads(payload)
        except ValueError:
            return

        node = topic.split("/")[1]

        if isinstance(status, dict):
            status["received_at"] = time.time()

            with self._lock:
                self.sim_nodes[node] = status

    def sim_command(self, node: str, command: dict) -> None:
        self.transport.publish(
            f"sim/{node}/cmd",
            json.dumps(command),
        )

    def _on_event(self, _topic: str, payload: bytes) -> None:
        try:
            e = json.loads(payload)
        except ValueError:
            return

        if not isinstance(e, dict) or e.get("type") in HIDDEN:
            return

        # Persist real alarm events in PostgreSQL.
        # Replies such as "status" and "control_done" are not persisted.
        if e.get("type") not in REPLIES:
            try:
                save_event(e)
            except Exception as exc:
                # PostgreSQL failure must not stop the MQTT event flow.
                print(f"[api] failed to persist event: {exc}")

        with self._lock:
            if e.get("type") not in REPLIES:
                self._events.append(e)

            waiter = self._waiters.get(e.get("req"))

            if waiter is None:
                return

            if e.get("type") == "control_done":
                del self._waiters[e["req"]]
                events = list(waiter.events)
                waiter.loop.call_soon_threadsafe(
                    _resolve,
                    waiter.future,
                    events,
                )
            else:
                waiter.events.append(e)

    # --- outgoing (asyncio) ------------------------------------------------

    async def control(
        self,
        action: str,
        code: str | None = None,
        source: str = "api",
    ) -> list[dict]:
        """Send a request; return the events alarm-core emitted for it."""

        req = secrets.token_hex(8)

        waiter = _Waiter(asyncio.get_running_loop())

        with self._lock:
            self._waiters[req] = waiter

        msg = {
            "action": action,
            "source": source[:32],
            "req": req,
        }

        if code is not None:
            msg["code"] = code

        self.transport.publish(
            CONTROL_TOPIC,
            json.dumps(msg),
        )

        try:
            return await asyncio.wait_for(
                waiter.future,
                self.timeout,
            )

        except asyncio.TimeoutError as e:
            raise AlarmCoreTimeout(
                f"no reply from alarm-core within {self.timeout:g}s"
            ) from e

        finally:
            with self._lock:
                self._waiters.pop(req, None)

    def recent_events(
        self,
        limit: int = 50,
        types: set[str] | None = None,
    ) -> list[dict]:
        """Newest first."""

        with self._lock:
            events = list(self._events)

        if types:
            events = [
                e
                for e in events
                if e.get("type") in types
            ]

        return events[::-1][:limit]


def _resolve(future: asyncio.Future, value) -> None:
    if not future.done():
        future.set_result(value)