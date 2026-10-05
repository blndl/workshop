"""Tamper-evident event log: an HMAC hash chain in a JSON Lines file.

Each line is {"seq": n, "prev": <mac of line n-1>, "event": {...}, "mac": ...}
where mac = HMAC-SHA256(log_key, canonical JSON of the other three fields).

- Editing a line breaks its mac.
- Deleting or inserting a line breaks the seq/prev chain.
- Without the key, an attacker can't rebuild a valid chain.
- Cutting lines off the END only shows against a known head (seq + mac)
  kept somewhere else; alarm-core publishes it in alarm/state for that reason.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

GENESIS = "0" * 64


def canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def _mac(key: bytes, seq: int, prev: str, event: dict) -> str:
    return hmac.new(key, canonical({"seq": seq, "prev": prev, "event": event}), hashlib.sha256).hexdigest()


@dataclass
class VerifyResult:
    count: int = 0
    head_seq: int = 0
    head_mac: str = GENESIS
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


def verify(path: Path, key: bytes, expect_head: tuple[int, str] | None = None) -> VerifyResult:
    r = VerifyResult()
    if not path.exists():
        if expect_head and expect_head[0] > 0:
            r.problems.append(f"log missing, expected {expect_head[0]} records")
        return r
    prev_mac, expected = GENESIS, 1
    seen: dict[int, str] = {}
    with path.open() as f:
        for lineno, line in enumerate(f, 1):
            r.count += 1
            try:
                rec = json.loads(line)
                seq, prev, event, mac = rec["seq"], rec["prev"], rec["event"], rec["mac"]
                if not isinstance(seq, int):
                    raise ValueError
            except (ValueError, KeyError, TypeError):
                r.problems.append(f"line {lineno}: unreadable")
                continue
            if not hmac.compare_digest(_mac(key, seq, prev, event), str(mac)):
                r.problems.append(f"line {lineno} (seq {seq}): content modified")
            elif seq > expected:
                missing = f"{expected}" if seq == expected + 1 else f"{expected}-{seq - 1}"
                r.problems.append(f"line {lineno}: record(s) {missing} deleted")
            elif seq < expected:
                r.problems.append(f"line {lineno} (seq {seq}): out of order or duplicated")
            elif prev != prev_mac:
                r.problems.append(f"line {lineno} (seq {seq}): chain broken")
            seen[seq] = str(mac)
            prev_mac, expected = str(mac), max(expected, seq + 1)
            r.head_seq, r.head_mac = seq, str(mac)
    if expect_head:
        want_seq, want_mac = expect_head
        if want_seq > r.head_seq:
            r.problems.append(f"log truncated: ends at seq {r.head_seq}, expected at least {want_seq}")
        elif want_seq > 0 and not seen.get(want_seq, "").startswith(want_mac):
            r.problems.append(f"seq {want_seq} does not match the expected head")
    return r


class EventLog:
    def __init__(self, path: Path, key: bytes):
        if len(key) < 16:
            raise ValueError("log key too short")
        self.path = Path(path)
        self.key = key
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.startup_check = verify(self.path, key)
        # Continue the chain from the last line, even if earlier lines are damaged.
        self.seq, self.head = self.startup_check.head_seq, self.startup_check.head_mac

    def append(self, event: dict) -> dict:
        seq = self.seq + 1
        rec = {"seq": seq, "prev": self.head, "event": event}
        rec["mac"] = _mac(self.key, seq, self.head, event)
        with self.path.open("a") as f:
            f.write(json.dumps(rec, sort_keys=True) + "\n")
            f.flush()
            os.fsync(f.fileno())
        self.seq, self.head = seq, rec["mac"]
        return rec
