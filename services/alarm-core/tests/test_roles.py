"""Role-based sensors: instant, safety, telemetry, and a module the core has never seen."""

from alarm_core.codes import CodeChecker, hash_code
from alarm_core.machine import ARMED, DISARMED, ENTRY_DELAY, TRIGGERED, AlarmMachine, Timing
from alarm_protocol.modules import parse

CODES = CodeChecker([hash_code("1234", 1000)], [hash_code("9999", 1000)])
MODULES = parse({"modules": {
    "door-1": {"sensors": {"door": {"kind": "contact", "role": "entry"},
                           "window": {"kind": "contact", "role": "instant"},
                           "lid": {"kind": "tamper", "role": "tamper"}}, "outputs": ["buzzer", "led"]},
    "env-1": {"sensors": {"gas": {"kind": "gas", "role": "safety", "unit": "ppm", "alarm_above": 400},
                          "hum": {"kind": "humidity", "role": "telemetry", "unit": "%"}}},
}}).modules


def machine():
    m = AlarmMachine(MODULES, CODES, Timing(exit_delay=1, entry_delay=10))
    for n in MODULES:
        m.node_online(n, 0)
    m.sensor("door-1", {"door": "0", "window": "0", "lid": "0"}, 0)
    m.sensor("env-1", {"gas": "120.0", "hum": "45.0"}, 0)
    m.drain()
    return m


def armed(m):
    assert m.arm("1234", 0, "test")
    m.tick(1)
    assert m.state == ARMED
    m.drain()
    return m


def types(m):
    return [e["type"] for e in m.drain()]


def test_instant_sensor_skips_the_entry_delay():
    m = armed(machine())
    m.sensor("door-1", {"window": "1"}, 5)
    assert m.state == TRIGGERED and m.reason == "window"


def test_instant_sensor_during_entry_delay_triggers():
    m = armed(machine())
    m.sensor("door-1", {"door": "1"}, 5)
    assert m.state == ENTRY_DELAY
    m.sensor("door-1", {"window": "1"}, 6)
    assert m.state == TRIGGERED


def test_cannot_arm_with_window_open_or_safety_alarm():
    m = machine()
    m.sensor("door-1", {"window": "1"}, 1)
    assert not m.arm("1234", 1)
    assert m.drain()[-1]["problems"] == ["door-1 window active"]
    m.sensor("door-1", {"window": "0"}, 2)
    m.sensor("env-1", {"gas": "650.0"}, 2)
    m.drain()
    assert not m.arm("1234", 3)
    assert m.drain()[-1]["problems"] == ["safety alarm: env-1 gas"]


def test_gas_leak_alarms_even_when_disarmed():
    m = machine()
    m.sensor("env-1", {"gas": "650.0"}, 5)
    assert m.state == DISARMED  # not an intrusion
    events = m.drain()
    assert [e["type"] for e in events] == ["sensor", "safety_alarm"]
    assert events[1]["value"] == "650.0" and events[1]["threshold"] == 400 and events[1]["unit"] == "ppm"
    assert m.outputs() == {"buzzer": "1", "led": "alarm"}
    snap = m.snapshot(6)["safety"]
    assert snap[0]["node"] == "env-1" and snap[0]["sensor"] == "gas"


def test_safety_alarm_silenced_by_code_then_cleared():
    m = machine()
    m.sensor("env-1", {"gas": "650.0"}, 5)
    m.drain()
    assert m.disarm("1234", 6, "keypad")
    assert types(m) == ["safety_silenced"]
    assert m.outputs() == {"buzzer": "0", "led": "alarm"}  # quiet, but still shown
    m.sensor("env-1", {"gas": "700.0"}, 7)  # still above: no new event, stays silenced
    assert m.drain() == [] and m.snapshot(7)["safety"][0]["value"] == "700.0"
    m.sensor("env-1", {"gas": "150.0"}, 30)
    assert types(m) == ["sensor", "safety_clear"]
    assert m.outputs() == {"buzzer": "0", "led": "off"} and not m.safety


def test_new_safety_alarm_sounds_again_after_silencing():
    m = machine()
    m.sensor("env-1", {"gas": "650.0"}, 5)
    m.disarm("1234", 6)
    m.sensor("env-1", {"gas": "100.0"}, 7)
    m.sensor("env-1", {"gas": "800.0"}, 8)
    assert m.outputs()["buzzer"] == "1"


def test_safety_alarm_and_intrusion_are_independent():
    m = armed(machine())
    m.sensor("env-1", {"gas": "650.0"}, 5)
    assert m.state == ARMED  # gas doesn't start an intrusion
    m.sensor("door-1", {"window": "1"}, 6)
    assert m.state == TRIGGERED
    m.disarm("1234", 7)
    assert m.state == DISARMED and m.safety  # disarming doesn't make the gas go away


def test_numeric_readings_dont_flood_events():
    m = machine()
    for i in range(20):
        m.sensor("env-1", {"gas": f"{120 + i:.1f}", "hum": f"{45 + i:.1f}"}, i)
    assert m.drain() == []
    assert m.snapshot(20)["nodes"]["env-1"]["sensors"]["hum"] == "64.0"


def test_malformed_values_ignored():
    m = machine()
    m.sensor("env-1", {"gas": "lots"}, 1)
    m.sensor("door-1", {"door": "2"}, 1)
    assert m.drain() == [] and m.sensors["env-1"]["gas"] == "120.0"


def test_snapshot_describes_each_module():
    node = machine().snapshot(0)["nodes"]["env-1"]
    assert node["info"]["gas"] == {"kind": "gas", "role": "safety", "binary": False, "label": "gas",
                                   "unit": "ppm", "alarm_above": 400.0}
    assert node["active"] == {"gas": False, "hum": False}


def test_a_module_the_core_has_never_seen():
    """Phase 1's goal: a new kind of module is a description, not new core code."""
    new = parse({"modules": {"vault-1": {
        "type": "vault", "name": "Safe",
        "sensors": {"shake": {"kind": "vibration", "role": "instant"},
                    "temp": {"kind": "temperature", "role": "safety", "alarm_above": 70, "unit": "°C"},
                    "co2": {"kind": "co2", "role": "telemetry", "unit": "ppm"}},
        "outputs": ["buzzer"]}}}).modules
    m = AlarmMachine(new, CODES, Timing(exit_delay=1))
    m.node_online("vault-1", 0)
    m.sensor("vault-1", {"shake": "0", "temp": "20.0", "co2": "410"}, 0)
    m.arm("1234", 0)
    m.tick(1)
    m.sensor("vault-1", {"shake": "1"}, 2)
    assert m.state == TRIGGERED and m.reason == "shake"
    m.sensor("vault-1", {"temp": "75.0"}, 3)
    assert ("vault-1", "temp") in m.safety
