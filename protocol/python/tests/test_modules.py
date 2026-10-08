from pathlib import Path

import pytest

from alarm_protocol.modules import DEFAULT_DOOR, ModuleError, load, parse

REPO = Path(__file__).resolve().parents[3]


def mod(**sensors):
    return {"modules": {"m-1": {"sensors": sensors}}}


def test_repo_config_is_valid():
    cfg = load(REPO / "config" / "modules.yaml")
    assert "door-1" in cfg.modules
    for m in cfg.modules.values():
        assert m.sensors


def test_binary_and_numeric_activity():
    m = parse(mod(door={"kind": "contact", "role": "entry"},
                  gas={"kind": "gas", "role": "safety", "unit": "ppm", "alarm_above": 400},
                  cold={"kind": "temperature", "role": "safety", "alarm_below": 5},
                  hum={"kind": "humidity", "role": "telemetry"})).modules["m-1"]
    door, gas, cold, hum = (m.sensors[n] for n in ("door", "gas", "cold", "hum"))
    assert door.binary and door.is_active("1") and door.is_active("0") is False and door.is_active("2") is None
    assert not gas.binary and gas.is_active("399.9") is False and gas.is_active("400") and gas.is_active("x") is None
    assert cold.is_active("4.5") and not cold.is_active("20")
    assert hum.is_active("99") is False  # telemetry never alarms


@pytest.mark.parametrize("sensor, message", [
    ({"kind": "contact", "role": "panic"}, "role"),
    ({"role": "entry"}, "kind"),
    ({"kind": "gas", "role": "safety"}, "alarm_above"),          # numeric alarm needs a threshold
    ({"kind": "humidity", "role": "telemetry", "alarm_above": 80}, "telemetry"),
    ({"kind": "contact", "role": "entry", "alarm_above": 1}, "numeric"),
    ({"kind": "gas", "role": "safety", "alarm_above": "high"}, "number"),
    ({"kind": "contact", "role": "entry", "colour": "red"}, "unknown"),
])
def test_invalid_sensor(sensor, message):
    with pytest.raises(ModuleError, match=message):
        parse(mod(s=sensor))


@pytest.mark.parametrize("data", [
    {}, {"modules": {}}, {"modules": {"Bad_ID": {"sensors": {"a": {"kind": "contact", "role": "entry"}}}}},
    {"modules": {"m-1": {"sensors": {}}}}, {"modules": {"m-1": {"sensors": {"9x": {"kind": "contact", "role": "entry"}}}}},
    {"modules": {"m-1": {"outputs": ["laser"], "sensors": {"a": {"kind": "contact", "role": "entry"}}}}},
])
def test_invalid_module(data):
    with pytest.raises(ModuleError):
        parse(data)


def test_default_door_matches_the_original():
    assert {n: s.role for n, s in DEFAULT_DOOR.sensors.items()} == {"door": "entry", "pir": "entry", "lid": "tamper"}
