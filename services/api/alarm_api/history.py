"""Reading alarm-core's event log (data/events.jsonl) back.

Used to backfill the database, and to refill the API's recent-events buffer
when it restarts (so the timeline, the photo gallery and the camera
statistics don't start empty).
"""

from __future__ import annotations

import json
from pathlib import Path

# Never returned: duress must stay invisible (see bridge.hidden), replies aren't events.
SKIP = {"duress", "status", "control_done"}


def read_log(path: Path, after_seq: int) -> list[dict]:
    """Events from alarm-core's log with seq > after_seq (skipping SKIP types)."""
    events = []
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return events
    for line in lines:
        try:
            rec = json.loads(line)
            seq, event = rec["seq"], rec["event"]
        except (ValueError, KeyError, TypeError):
            continue  # damaged line: `alarm_core verify-log` reports it
        if (isinstance(seq, int) and seq > after_seq and isinstance(event, dict) and event.get("type") not in SKIP
                and not str(event.get("reason", "")).startswith("duress")):
            events.append({**event, "seq": seq})
    return events


