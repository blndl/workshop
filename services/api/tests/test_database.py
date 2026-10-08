"""EventStore against a fake database that can be down."""

import time

import json

from alarm_api.database import EventStore


class FakeDB:
    def __init__(self, up=True):
        self.up = up
        self.rows: list[tuple] = []
        self.connects = 0

    def connect(self, _url):
        self.connects += 1
        if not self.up:
            raise ConnectionError("connection refused")
        return FakeConn(self)


class FakeConn:
    def __init__(self, db):
        self.db = db
        self.pending: list[tuple] = []

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql):
        if not self.db.up:
            raise ConnectionError("server closed the connection")
        if "MAX(seq)" in sql:
            self._result = (max([r[0] for r in self.db.rows if r[0] is not None], default=0),)

    def fetchone(self):
        return self._result

    def executemany(self, _sql, rows):
        if not self.db.up:
            raise ConnectionError("server closed the connection")
        seen = {r[0] for r in self.db.rows + self.pending if r[0] is not None}
        self.pending += [r for r in rows if r[0] is None or r[0] not in seen]  # ON CONFLICT (seq) DO NOTHING

    def commit(self):
        self.db.rows += self.pending
        self.pending = []

    def close(self):
        pass


def wait_for(cond, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


def types(db):
    return [r[2] for r in db.rows]


def test_events_written_in_order():
    db = FakeDB()
    store = EventStore("x", connect=db.connect, log=lambda _m: None)
    store.start()
    for i in range(5):
        store.put({"type": f"e{i}", "ts": 1791000000 + i})
    assert wait_for(lambda: len(db.rows) == 5)
    assert types(db) == ["e0", "e1", "e2", "e3", "e4"]
    assert db.connects == 1  # one connection reused, not one per event
    store.stop()


def test_database_not_ready_at_startup_loses_nothing():
    db = FakeDB(up=False)
    store = EventStore("x", connect=db.connect, log=lambda _m: None)
    store.start()
    store.put({"type": "node_online"})  # the event that used to be lost
    store.put({"type": "state"})
    time.sleep(1.5)
    assert db.rows == [] and not store.connected  # held back, not lost
    db.up = True
    assert wait_for(lambda: len(db.rows) == 2)
    assert types(db) == ["node_online", "state"] and store.connected
    store.stop()


def test_database_goes_away_and_comes_back():
    db = FakeDB()
    store = EventStore("x", connect=db.connect, log=lambda _m: None)
    store.start()
    store.put({"type": "a"})
    assert wait_for(lambda: len(db.rows) == 1)
    db.up = False
    store.put({"type": "b"})
    time.sleep(0.5)
    db.up = True
    assert wait_for(lambda: types(db) == ["a", "b"])
    store.stop()


def test_put_never_blocks_and_drops_oldest_when_full():
    db = FakeDB(up=False)
    store = EventStore("x", connect=db.connect, log=lambda _m: None, max_queue=3)  # not started
    t = time.monotonic()
    for i in range(5):
        store.put({"type": f"e{i}"})
    assert time.monotonic() - t < 0.1
    assert store.pending == 3 and store.dropped == 2


def test_bad_timestamp_still_stored():
    db = FakeDB()
    store = EventStore("x", connect=db.connect, log=lambda _m: None)
    store.start()
    store.put({"type": "weird", "ts": "not-a-number"})
    assert wait_for(lambda: len(db.rows) == 1) and db.rows[0][3] is None
    store.stop()


def test_bridge_queues_only_real_events():
    import json

    from alarm_api.bridge import Bridge
    from alarm_protocol.transport import MemoryBus

    class Recorder:
        def __init__(self):
            self.events = []

        def put(self, e):
            self.events.append(e["type"])

    bus = MemoryBus()
    store = Recorder()
    Bridge(bus.client(), store=store)
    pub = bus.client()
    for t in ["state", "duress", "control_done", "status", "security"]:
        pub.publish("alarm/events", json.dumps({"type": t, "ts": 1}))
    assert store.events == ["state", "security"]


def write_log(path, events):
    path.write_text("".join(json.dumps({"seq": i, "prev": "x", "event": e, "mac": "x"}) + "\n"
                            for i, e in enumerate(events, 1)))


def test_backfill_from_alarm_core_log(tmp_path):
    log = tmp_path / "events.jsonl"
    write_log(log, [{"type": "node_online", "ts": 1}, {"type": "duress", "ts": 2}, {"type": "state", "ts": 3}])
    db = FakeDB()
    store = EventStore("x", connect=db.connect, log=lambda _m: None, backfill_from=log)
    store.start()
    assert wait_for(lambda: len(db.rows) == 2)
    assert types(db) == ["node_online", "state"]  # duress never copied
    assert [r[0] for r in db.rows] == [1, 3]
    store.stop()


def test_backfill_and_live_events_never_duplicate(tmp_path):
    log = tmp_path / "events.jsonl"
    write_log(log, [{"type": "a"}, {"type": "b"}])
    db = FakeDB()
    db.rows.append((1, None, "a", None, None))  # seq 1 already stored
    store = EventStore("x", connect=db.connect, log=lambda _m: None, backfill_from=log)
    store.put({"type": "b", "seq": 2})  # the same event, also arriving live
    store.start()
    assert wait_for(lambda: len(db.rows) == 2)
    time.sleep(0.3)
    assert [r[0] for r in db.rows] == [1, 2]
    store.stop()


def test_missing_or_damaged_log_is_harmless(tmp_path):
    log = tmp_path / "events.jsonl"
    log.write_text("{broken\n" + json.dumps({"seq": 1, "event": {"type": "ok"}}) + "\n")
    db = FakeDB()
    store = EventStore("x", connect=db.connect, log=lambda _m: None, backfill_from=log)
    store.start()
    assert wait_for(lambda: types(db) == ["ok"])
    store.stop()
    store2 = EventStore("x", connect=FakeDB().connect, log=lambda _m: None, backfill_from=tmp_path / "nope.jsonl")
    store2.start()
    store2.put({"type": "live"})
    assert wait_for(lambda: store2.written == 1)
    store2.stop()
