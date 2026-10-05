import pytest

from alarm_core.codes import CodeChecker, hash_code, verify
from alarm_core.machine import ARMED, ARMING, DISARMED, ENTRY_DELAY, TRIGGERED, AlarmMachine, Timing

USER, DURESS = "1234", "9999"
FAST = 1000  # pbkdf2 iterations; real hashes use 200k


@pytest.fixture
def m():
    codes = CodeChecker([hash_code(USER, FAST)], [hash_code(DURESS, FAST)])
    machine = AlarmMachine(["door-1"], codes, Timing(exit_delay=30, entry_delay=20, siren_max=180))
    machine.node_online("door-1", 0)
    machine.sensor("door-1", {"door": "0", "pir": "0", "lid": "0"}, 0)
    machine.drain()
    return machine


def types(m):
    return [e["type"] for e in m.drain()]


def armed(m, now=0.0):
    assert m.arm(USER, now, "test")
    m.tick(now + 30)
    assert m.state == ARMED
    m.drain()
    return m


def test_code_hashing():
    h = hash_code("4321", FAST)
    assert verify("4321", h) and not verify("4322", h)
    with pytest.raises(ValueError):
        hash_code("12")


def test_arm_needs_valid_code(m):
    assert not m.arm("0000", 0)
    assert types(m) == ["bad_code"]
    assert m.state == DISARMED


def test_exit_delay_then_armed(m):
    assert m.arm(USER, 0, "test")
    assert m.state == ARMING and m.outputs() == {"buzzer": "0", "led": "armed"}
    m.sensor("door-1", {"door": "1"}, 5)  # leaving the house is fine
    assert m.state == ARMING
    m.tick(29.9)
    assert m.state == ARMING
    m.tick(30)
    assert m.state == ARMED


def test_arm_refused_when_node_offline_or_lid_open(m):
    m.link_lost("door-1", 0)
    m.drain()
    assert not m.arm(USER, 0)
    assert m.drain()[-1]["problems"] == ["door-1 offline"]
    m.node_online("door-1", 1)
    m.sensor("door-1", {"lid": "1"}, 1)
    m.drain()
    assert not m.arm(USER, 2)
    assert m.drain()[-1]["problems"] == ["door-1 lid open"]


def test_entry_delay_then_disarm_in_time(m):
    armed(m)
    m.sensor("door-1", {"door": "1"}, 40)
    assert m.state == ENTRY_DELAY and m.reason == "door"
    m.tick(55)
    assert m.disarm(USER, 55, "keypad")
    assert m.state == DISARMED and not m.siren


def test_entry_delay_expires_triggers_siren(m):
    armed(m)
    m.sensor("door-1", {"pir": "1"}, 40)
    m.tick(60)
    assert m.state == TRIGGERED and m.node == "door-1"
    assert m.outputs() == {"buzzer": "1", "led": "alarm"}
    m.tick(60 + 180)
    assert not m.siren and m.state == TRIGGERED  # siren stops, alarm stays latched
    assert "siren_timeout" in types(m)
    m.disarm(USER, 300)
    assert m.outputs() == {"buzzer": "0", "led": "off"}


def test_tamper_triggers_immediately_when_armed(m):
    armed(m)
    m.sensor("door-1", {"lid": "1"}, 40)
    assert m.state == TRIGGERED and m.reason == "tamper:lid"


def test_tamper_while_disarmed_only_reports(m):
    m.sensor("door-1", {"lid": "1"}, 1)
    assert m.state == DISARMED
    assert types(m) == ["sensor", "tamper"]


def test_link_lost_fail_secure(m):
    m.link_lost("door-1", 1)
    assert m.state == DISARMED
    m.node_online("door-1", 2)
    armed(m, 2)
    m.link_lost("door-1", 40)
    assert m.state == TRIGGERED and m.reason == "link_lost"


def test_duress_disarms_like_a_normal_code_plus_silent_event(m):
    armed(m)
    m.disarm(DURESS, 40, "keypad")
    events = m.drain()
    assert m.state == DISARMED
    assert [e["type"] for e in events] == ["duress", "state"]
    normal = AlarmMachine(["door-1"], m.codes)
    normal.state = ARMED
    normal.disarm(USER, 40, "keypad")
    assert {k: v for k, v in events[1].items()} == normal.drain()[0]


def test_lockout_after_five_bad_codes(m):
    armed(m)
    for i in range(4):
        assert not m.disarm("0000", 40 + i)
    assert not m.disarm("0000", 45)
    assert types(m)[-1] == "code_lockout"
    assert not m.disarm(USER, 50)  # right code, but locked out
    assert types(m) == ["code_locked"]
    assert m.disarm(USER, 45 + 300)


def test_repeated_heartbeat_does_not_repeat_events(m):
    armed(m)
    for t in range(40, 45):
        m.sensor("door-1", {"door": "0", "pir": "0", "lid": "0"}, t)
    assert m.drain() == [] and m.state == ARMED


def test_first_report_door_open_while_armed_counts(m):
    machine = AlarmMachine(["door-1"], m.codes, Timing(exit_delay=1))
    machine.node_online("door-1", 0)
    machine.arm(USER, 0)
    machine.tick(1)
    machine.sensor("door-1", {"door": "1"}, 2)  # e.g. node rebooted with the door open
    assert machine.state == ENTRY_DELAY


def test_unknown_node_ignored(m):
    m.sensor("ghost", {"door": "1"}, 1)
    m.link_lost("ghost", 1)
    assert m.drain() == []
