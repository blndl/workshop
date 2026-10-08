"""The 'confirm: person' rule and live view."""

from alarm_core.codes import CodeChecker, hash_code
from alarm_core.machine import ARMED, DISARMED, ENTRY_DELAY, TRIGGERED, AlarmMachine, Timing
from alarm_protocol.modules import parse

CODES = CodeChecker([hash_code("1234", 1000)], [])
MODULES = parse({"modules": {"door-1": {"sensors": {
    "door": {"kind": "contact", "role": "entry"},
    "pir": {"kind": "motion", "role": "entry", "confirm": "person"},
    "window": {"kind": "contact", "role": "instant", "confirm": "person"},
}}}}).modules


def armed():
    m = AlarmMachine(MODULES, CODES, Timing(exit_delay=1, entry_delay=10, verify_timeout=8, live_view_max=120))
    m.node_online("door-1", 0)
    m.sensor("door-1", {"door": "0", "pir": "0", "window": "0"}, 0)
    m.arm("1234", 0)
    m.tick(1)
    m.drain()
    return m


def shot(i, person, **objects):
    return {"reason": f"verify-{i}", "person": person, "confidence": 0.9 if person else 0, "objects": objects, "path": f"p{i}.jpg"}


def types(m):
    return [e["type"] for e in m.drain()]


def test_motion_waits_for_the_camera():
    m = armed()
    m.sensor("door-1", {"pir": "1"}, 5)
    assert m.state == ARMED and types(m) == ["sensor", "verify"]
    assert m.snapshot(5)["verifying"] == {"node": "door-1", "sensor": "pir"}


def test_person_seen_starts_the_entry_delay():
    m = armed()
    m.sensor("door-1", {"pir": "1"}, 5)
    m.drain()
    m.detection(shot(1, False), 6)
    m.detection(shot(2, True), 6.5)
    assert m.state == ENTRY_DELAY and m.reason == "pir (person seen)"
    assert types(m) == ["motion_confirmed", "state"]


def test_nobody_on_the_whole_burst_dismisses_the_motion():
    m = armed()
    m.sensor("door-1", {"pir": "1"}, 5)
    m.drain()
    m.detection(shot(1, False, cat=1), 6)
    m.detection(shot(2, False, cat=1), 6.5)
    assert m.verify is not None  # not yet: one photo left
    m.detection(shot(3, False), 7)
    events = m.drain()
    assert m.state == ARMED and events[-1]["type"] == "motion_dismissed" and events[-1]["seen"] == {"cat": 1}
    m.tick(30)
    assert m.state == ARMED  # the cat is forgotten


def test_no_answer_counts_anyway():
    m = armed()
    m.sensor("door-1", {"pir": "1"}, 5)
    m.tick(12.9)
    assert m.state == ARMED
    m.tick(13)  # 8 s timeout: detector down or too slow
    assert m.state == ENTRY_DELAY and m.reason == "pir (not verified)"
    assert "verify_timeout" in types(m)


def test_door_never_waits_for_the_camera():
    m = armed()
    m.sensor("door-1", {"door": "1"}, 5)
    assert m.state == ENTRY_DELAY


def test_other_photos_dont_count_towards_the_check():
    m = armed()
    m.sensor("door-1", {"pir": "1"}, 5)
    m.detection({"reason": "pir", "person": True, "objects": {}}, 5.5)  # the single motion photo
    assert m.state == ARMED and m.verify is not None


def test_instant_sensor_with_confirmation():
    m = armed()
    m.sensor("door-1", {"window": "1"}, 5)
    assert m.state == ARMED
    m.detection(shot(1, True), 6)
    assert m.state == TRIGGERED


def test_disarm_cancels_the_check():
    m = armed()
    m.sensor("door-1", {"pir": "1"}, 5)
    m.disarm("1234", 6)
    m.tick(20)
    assert m.state == DISARMED and m.verify is None


def test_live_view_is_logged_and_ends_by_itself():
    m = armed()
    m.live_view(True, 10, "api")
    e = m.drain()[0]
    assert e == {"type": "live_view", "on": True, "seconds": 120, "source": "api"}
    assert m.snapshot(70)["live_view_s"] == 60
    m.tick(130)
    assert m.drain()[0] == {"type": "live_view", "on": False, "source": "timeout"}
    m.live_view(False, 140, "api")
    assert m.drain() == []  # already off
