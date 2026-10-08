import hashlib
import json
import os
import time

import pytest

from alarm_camera.policy import CapturePolicy
from alarm_camera.service import SNAPSHOTS_TOPIC, CameraService
from alarm_camera.sources import FakeSource
from alarm_camera.store import SnapshotStore


def state(s, reason="x"):
    return {"type": "state", "state": s, "reason": reason}


def run_policy(p, start, end, step=0.05):
    out, t = [], start
    while t <= end:
        out += [(round(t, 2), r) for r in p.due(t)]
        t += step
    return out


def test_disarmed_never_captures():
    p = CapturePolicy()
    p.on_event({"type": "sensor", "sensor": "pir", "value": "1"}, 0)
    assert not p.camera_wanted and run_policy(p, 0, 5) == []


def test_armed_motion_takes_one_picture():
    p = CapturePolicy()
    p.on_event(state("armed"), 0)
    assert p.camera_wanted
    p.on_event({"type": "sensor", "sensor": "pir", "value": "1"}, 1)
    assert [r for _, r in run_policy(p, 0, 3)] == ["pir"]


def test_entry_delay_burst_without_duplicate():
    p = CapturePolicy()
    p.on_event(state("armed"), 0)
    p.on_event({"type": "sensor", "sensor": "door", "value": "1"}, 10)
    p.on_event(state("entry_delay", "door"), 10)
    shots = run_policy(p, 10, 12)
    assert [r for _, r in shots] == ["door", "entry-door-1", "entry-door-2", "entry-door-3"]
    p.on_event({"type": "sensor", "sensor": "pir", "value": "1"}, 12.0)
    p.on_event({"type": "sensor", "sensor": "pir", "value": "1"}, 12.2)  # within MIN_GAP: skipped
    assert [r for _, r in run_policy(p, 12, 13)] == ["pir"]


def test_triggered_follow_up_pictures_then_stop():
    p = CapturePolicy()
    p.on_event(state("triggered", "door"), 0)
    shots = run_policy(p, 0, 120)
    follow = [t for t, r in shots if r == "alarm-followup"]
    assert len([r for _, r in shots if r.startswith("alarm-door")]) == 3
    assert follow[0] == pytest.approx(5, abs=0.1) and follow[-1] < 60 and len(follow) == 11


def test_disarm_stops_follow_ups_and_releases_camera():
    p = CapturePolicy()
    p.on_event(state("triggered"), 0)
    run_policy(p, 0, 7)
    p.on_event(state("disarmed"), 7)
    assert run_policy(p, 7, 30) == []
    assert not p.camera_wanted


def test_duress_pictures_survive_the_disarm():
    p = CapturePolicy()
    p.on_event(state("armed"), 0)
    p.on_event({"type": "duress"}, 5)
    p.on_event(state("disarmed"), 5)
    assert p.camera_wanted  # stays open until the burst is done
    assert [r for _, r in run_policy(p, 5, 8)] == ["duress-1", "duress-2", "duress-3"]
    assert not p.camera_wanted


def test_store_saves_and_prunes(tmp_path):
    store = SnapshotStore(tmp_path, retention_days=1)
    now = time.time()
    path, digest = store.save(b"jpegdata", "door", now)
    assert path.read_bytes() == b"jpegdata" and digest == hashlib.sha256(b"jpegdata").hexdigest()
    old, _ = store.save(b"old", "pir", now)
    os.utime(old, (now - 2 * 86400, now - 2 * 86400))
    assert store.prune(now) == [old]
    assert path.exists()


def test_failed_camera_is_reported_once(tmp_path):
    from alarm_protocol.transport import MemoryBus

    class Broken(FakeSource):
        def open(self):
            raise RuntimeError("no camera")

    bus = MemoryBus()
    svc = CameraService(Broken(), SnapshotStore(tmp_path), bus.client(), log=lambda _m: None)
    bus.client().publish("alarm/events", json.dumps(state("armed")))
    for t in range(3):
        svc.tick(t)
    errors = [json.loads(p) for t, p in bus.log if t == SNAPSHOTS_TOPIC]
    assert errors == [{"type": "camera_error", "error": "no camera"}]


def test_verify_request_takes_a_burst():
    p = CapturePolicy()
    p.on_event(state("armed"), 0)
    p.on_event({"type": "verify", "node": "door-1", "sensor": "pir"}, 1)
    assert [r for _, r in run_policy(p, 1, 3)] == ["verify-1", "verify-2", "verify-3"]


def test_live_view_opens_the_camera_while_disarmed_then_ends():
    p = CapturePolicy()
    assert not p.camera_wanted and p.why.startswith("off")
    p.on_event({"type": "live_view", "on": True, "seconds": 120}, 0)
    assert p.camera_wanted and p.why == "live view"
    assert run_policy(p, 0, 5) == []  # watching only: no photos are stored
    p.due(121)
    assert not p.camera_wanted


def test_camera_streams_frames_and_status_without_file_names(tmp_path):
    from alarm_protocol.transport import MemoryBus

    bus = MemoryBus()
    src = FakeSource(b"\xff\xd8frame")
    svc = CameraService(src, SnapshotStore(tmp_path), bus.client(), log=lambda _m: None)
    bus.client().publish("alarm/events", json.dumps({"type": "live_view", "on": True, "seconds": 60}))
    t = 0.0
    while t < 2:
        svc.tick(t)
        t += 0.1
    frames = [p for topic, p in bus.log if topic == "alarm/camera/frame"]
    status = [json.loads(p) for topic, p in bus.log if topic == "alarm/camera/status"]
    assert len(frames) >= 3 and status[-1]["open"] and status[-1]["why"] == "live view"
    assert not any("path" in s or "last_snapshot" in s for s in status)
