import hashlib
import json

import pytest

from alarm_core.eventlog import EventLog, verify

KEY = b"k" * 32


@pytest.fixture
def log(tmp_path):
    lg = EventLog(tmp_path / "events.jsonl", KEY)
    for i in range(5):
        lg.append({"type": "sensor", "n": i})
    return lg


def lines(lg):
    return lg.path.read_text().splitlines()


def write(lg, ls):
    lg.path.write_text("".join(l + "\n" for l in ls))


def test_intact_log_verifies(log):
    r = verify(log.path, KEY)
    assert r.ok and r.count == 5 and r.head_seq == 5 and r.head_mac == log.head


def test_edited_record_detected(log):
    ls = lines(log)
    ls[2] = ls[2].replace('"n": 2', '"n": 99')
    write(log, ls)
    assert verify(log.path, KEY).problems == ["line 3 (seq 3): content modified"]


def test_deleted_record_detected(log):
    ls = lines(log)
    del ls[1]
    write(log, ls)
    assert verify(log.path, KEY).problems == ["line 2: record(s) 2 deleted"]


def test_reordered_records_detected(log):
    ls = lines(log)
    ls[1], ls[2] = ls[2], ls[1]
    write(log, ls)
    assert not verify(log.path, KEY).ok


def test_chain_rebuilt_without_the_key_detected(log):
    # Attacker deletes a record and recomputes every mac with plain SHA-256.
    recs = [json.loads(l) for l in lines(log)]
    del recs[1]
    prev = "0" * 64
    for i, r in enumerate(recs, 1):
        r["seq"], r["prev"] = i, prev
        r["mac"] = prev = hashlib.sha256(json.dumps(r["event"]).encode()).hexdigest()
    write(log, [json.dumps(r) for r in recs])
    assert len(verify(log.path, KEY).problems) == 4


def test_garbage_line_detected(log):
    write(log, lines(log) + ["{oops"])
    assert verify(log.path, KEY).problems == ["line 6: unreadable"]


def test_truncation_needs_a_known_head(log):
    head = (log.seq, log.head)
    write(log, lines(log)[:3])
    assert verify(log.path, KEY).ok  # cutting the end alone is invisible...
    problems = verify(log.path, KEY, head).problems  # ...unless the head was kept elsewhere
    assert problems == ["log truncated: ends at seq 3, expected at least 5"]


def test_head_prefix_match(log):
    assert verify(log.path, KEY, (5, log.head[:16])).ok
    assert not verify(log.path, KEY, (5, "deadbeef")).ok


def test_reopen_continues_chain(log):
    again = EventLog(log.path, KEY)
    assert again.startup_check.ok and again.seq == 5
    again.append({"type": "x"})
    assert verify(log.path, KEY).ok and verify(log.path, KEY).count == 6


def test_wrong_key_fails_everything(log):
    assert len(verify(log.path, b"x" * 32).problems) == 5
