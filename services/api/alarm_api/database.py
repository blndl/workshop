
"""Persist alarm events in PostgreSQL without slowing down or losing them.

The MQTT handler only calls EventStore.put(), which never blocks: events go
into a bounded in-memory queue. One background thread keeps a connection
open and writes them in batches. If PostgreSQL is not ready yet (startup) or
goes away, the writer keeps the events and retries with backoff, so they are
written once the database is back.

Events that happened while the API itself was not running never reach it over
MQTT. On its first connection the store therefore backfills from alarm-core's
event log (data/events.jsonl): every record whose seq is above the highest
one already stored. The seq column is unique, so nothing is stored twice.
The log stays the source of truth; the database is a searchable copy.
"""

from __future__ import annotations

import json
import queue
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import psycopg
from psycopg.types.json import Jsonb

from .history import read_log  # noqa: F401 (re-exported; used by the backfill)

# Also run on every connection, so databases created before seq existed upgrade themselves.
SCHEMA = [
    "ALTER TABLE alarm_events ADD COLUMN IF NOT EXISTS seq BIGINT",
    "CREATE UNIQUE INDEX IF NOT EXISTS alarm_events_seq ON alarm_events (seq)",
]
INSERT = """
    INSERT INTO alarm_events (seq, event_id, event_type, event_time, event_data)
    VALUES (%s, %s, %s, COALESCE(%s, NOW()), %s)
    ON CONFLICT (seq) DO NOTHING
"""
MAX_QUEUE = 10_000  # about a day of normal traffic; beyond that the oldest are dropped
BATCH = 200
RETRY_MAX = 30.0


def _row(event: dict) -> tuple:
    event_time = None
    if "ts" in event:
        try:
            event_time = datetime.fromtimestamp(float(event["ts"]), tz=timezone.utc)
        except (TypeError, ValueError):
            pass
    seq = event.get("seq") if isinstance(event.get("seq"), int) else None
    return (seq, event.get("req"), str(event.get("type", "unknown")), event_time, Jsonb(event))


class EventStore:
    def __init__(
        self,
        url: str,
        connect: Callable[[str], "psycopg.Connection"] | None = None,
        log: Callable[[str], None] = print,
        max_queue: int = MAX_QUEUE,
        backfill_from: Path | None = None,
    ):
        self.url = url
        self.backfill_from = backfill_from
        self._backfilled = False
        self._connect = connect or (lambda u: psycopg.connect(u, connect_timeout=5))
        self.log = log
        self._queue: queue.Queue[dict] = queue.Queue(maxsize=max_queue)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="event-store", daemon=True)
        self.written = 0
        self.dropped = 0
        self.connected = False

    def start(self) -> None:
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        """Stop after trying to write what is still queued."""
        self._stop.set()
        self._thread.join(timeout)

    def put(self, event: dict) -> None:
        """Queue an event for writing. Never blocks."""
        while True:
            try:
                self._queue.put_nowait(event)
                return
            except queue.Full:
                try:
                    self._queue.get_nowait()  # make room: drop the oldest
                    self.dropped += 1
                    if self.dropped in (1, 100) or self.dropped % 1000 == 0:
                        self.log(f"[db] queue full, {self.dropped} old event(s) dropped")
                except queue.Empty:
                    pass

    @property
    def pending(self) -> int:
        return self._queue.qsize()

    # --- writer thread -------------------------------------------------------

    def _run(self) -> None:
        conn = None
        delay = 1.0
        batch: list[dict] = []
        while True:
            # Until the backfill is done, connect right away instead of waiting for a live event.
            if not batch and self._backfilled:
                try:
                    batch.append(self._queue.get(timeout=0.5))
                except queue.Empty:
                    if self._stop.is_set():
                        break
                    continue
            while len(batch) < BATCH:
                try:
                    batch.append(self._queue.get_nowait())
                except queue.Empty:
                    break
            try:
                if conn is None:
                    conn = self._connect(self.url)
                    with conn.cursor() as cur:
                        for statement in SCHEMA:
                            cur.execute(statement)
                    conn.commit()
                    if not self.connected:
                        self.log("[db] connected to PostgreSQL")
                    self.connected = True
                    if not self._backfilled:
                        self._backfill(conn)
                if batch:
                    with conn.cursor() as cur:
                        cur.executemany(INSERT, [_row(e) for e in batch])
                    conn.commit()
                    self.written += len(batch)
                    batch = []
                delay = 1.0
            except Exception as e:  # noqa: BLE001 - any database error: keep the batch, retry
                if self.connected:
                    self.log(f"[db] write failed, will retry: {e}")
                elif delay == 1.0:
                    self.log(f"[db] PostgreSQL not reachable yet, retrying: {e}")
                self.connected = False
                if conn is not None:
                    try:
                        conn.close()
                    except Exception:  # noqa: BLE001
                        pass
                    conn = None
                if self._stop.is_set():
                    break  # give up on shutdown
                self._stop.wait(delay)
                delay = min(RETRY_MAX, delay * 2)
        if batch or self.pending:
            self.log(f"[db] stopped with {len(batch) + self.pending} event(s) not written")
        if conn is not None:
            conn.close()

    def _backfill(self, conn) -> None:
        """Copy log events the database doesn't have yet (e.g. from before the API started)."""
        if self.backfill_from is None:
            self._backfilled = True
            return
        with conn.cursor() as cur:
            cur.execute("SELECT COALESCE(MAX(seq), 0) FROM alarm_events")
            last = cur.fetchone()[0]
        missing = read_log(self.backfill_from, last)
        for i in range(0, len(missing), BATCH):
            with conn.cursor() as cur:
                cur.executemany(INSERT, [_row(e) for e in missing[i : i + BATCH]])
            conn.commit()
        self.written += len(missing)
        self._backfilled = True
        if missing:
            self.log(f"[db] backfilled {len(missing)} event(s) from {self.backfill_from.name} (seq > {last})")

