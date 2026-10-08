"""Module descriptions: what each field module is and what its sensors mean.

Loaded from config/modules.yaml (see docs/modules.md). The core treats every
sensor by its role, so a new kind of module needs a description, not code:

    modules:
      door-1:
        type: entry
        name: Front door
        sensors:
          door: {kind: contact, role: entry}
          lid:  {kind: tamper,  role: tamper}
        outputs: [buzzer, led]
      env-1:
        type: environment
        sensors:
          gas:  {kind: gas, role: safety, unit: ppm, alarm_above: 400, normal: 120}
          hum:  {kind: humidity, role: telemetry, unit: "%", normal: 45}
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROLES = {
    "entry": "when armed, starts the entry delay",
    "instant": "when armed, triggers immediately",
    "tamper": "always watched: triggers when armed, warns when disarmed",
    "safety": "alarms whatever the arm state (gas, smoke, water…)",
    "telemetry": "never alarms; shown and charted",
}
# Kinds that report on/off. Anything else is numeric (e.g. temperature, gas).
BINARY_KINDS = {"contact", "motion", "tamper", "smoke", "water", "vibration", "button", "glass_break"}
OUTPUTS = {"buzzer", "led"}

_ID = re.compile(r"[a-z0-9-]{1,16}")
_SENSOR = re.compile(r"[a-z][a-z0-9_]{0,15}")


class ModuleError(ValueError):
    pass


@dataclass(frozen=True)
class SensorSpec:
    name: str
    kind: str
    role: str
    binary: bool
    unit: str = ""
    alarm_above: float | None = None
    alarm_below: float | None = None
    normal: float | None = None  # simulator baseline for numeric sensors
    label: str = ""
    confirm: str | None = None  # "person": the camera must see someone before it counts

    def is_active(self, value: str) -> bool | None:
        """Active (alarm condition) for a reported value; None if the value is invalid."""
        if self.binary:
            return {"0": False, "1": True}.get(value)
        try:
            v = float(value)
        except ValueError:
            return None
        if self.alarm_above is not None and v >= self.alarm_above:
            return True
        if self.alarm_below is not None and v <= self.alarm_below:
            return True
        return False

    def info(self) -> dict:
        """What the dashboard needs to display this sensor."""
        out = {"kind": self.kind, "role": self.role, "binary": self.binary, "label": self.label or self.name}
        for key in ("unit", "alarm_above", "alarm_below", "normal", "confirm"):
            value = getattr(self, key)
            if value not in (None, ""):
                out[key] = value
        return out


@dataclass(frozen=True)
class ModuleSpec:
    id: str
    type: str
    name: str
    sensors: dict[str, SensorSpec]
    outputs: tuple[str, ...] = ()

    def info(self) -> dict:
        return {"type": self.type, "name": self.name, "outputs": list(self.outputs),
                "sensors": {n: s.info() for n, s in self.sensors.items()}}


@dataclass
class Config:
    modules: dict[str, ModuleSpec] = field(default_factory=dict)


def _sensor(module: str, name: str, raw) -> SensorSpec:
    where = f"{module}.sensors.{name}"
    if not _SENSOR.fullmatch(name):
        raise ModuleError(f"{where}: sensor names are 1-16 chars of a-z, 0-9, _ starting with a letter")
    if not isinstance(raw, dict):
        raise ModuleError(f"{where}: expected a mapping like {{kind: contact, role: entry}}")
    unknown = set(raw) - {"kind", "role", "unit", "alarm_above", "alarm_below", "normal", "label", "binary", "confirm"}
    if unknown:
        raise ModuleError(f"{where}: unknown keys {sorted(unknown)}")
    kind, role = raw.get("kind"), raw.get("role")
    if not isinstance(kind, str) or not kind:
        raise ModuleError(f"{where}: 'kind' is required")
    if role not in ROLES:
        raise ModuleError(f"{where}: 'role' must be one of {sorted(ROLES)}")
    binary = raw.get("binary", kind in BINARY_KINDS)
    nums = {}
    for key in ("alarm_above", "alarm_below", "normal"):
        if key in raw:
            if binary:
                raise ModuleError(f"{where}: '{key}' only applies to numeric sensors")
            if not isinstance(raw[key], (int, float)) or isinstance(raw[key], bool):
                raise ModuleError(f"{where}: '{key}' must be a number")
            nums[key] = float(raw[key])
    has_threshold = "alarm_above" in nums or "alarm_below" in nums
    if not binary and role != "telemetry" and not has_threshold:
        raise ModuleError(f"{where}: a numeric {role} sensor needs alarm_above or alarm_below")
    if role == "telemetry" and has_threshold:
        raise ModuleError(f"{where}: telemetry sensors never alarm; drop the threshold or change the role")
    confirm = raw.get("confirm")
    if confirm is not None and (confirm != "person" or role not in ("entry", "instant")):
        raise ModuleError(f"{where}: 'confirm: person' only applies to entry and instant sensors")
    return SensorSpec(name, kind, role, bool(binary), str(raw.get("unit", "")), nums.get("alarm_above"),
                      nums.get("alarm_below"), nums.get("normal"), str(raw.get("label", "")), confirm)


def parse(data) -> Config:
    if not isinstance(data, dict) or not isinstance(data.get("modules"), dict) or not data["modules"]:
        raise ModuleError("expected a top-level 'modules:' mapping with at least one module")
    modules = {}
    for mid, raw in data["modules"].items():
        if not isinstance(mid, str) or not _ID.fullmatch(mid):
            raise ModuleError(f"module id {mid!r}: 1-16 chars of a-z, 0-9, -")
        if not isinstance(raw, dict) or not isinstance(raw.get("sensors"), dict) or not raw["sensors"]:
            raise ModuleError(f"{mid}: needs a 'sensors:' mapping with at least one sensor")
        unknown = set(raw) - {"type", "name", "sensors", "outputs"}
        if unknown:
            raise ModuleError(f"{mid}: unknown keys {sorted(unknown)}")
        outputs = raw.get("outputs", [])
        if not isinstance(outputs, list) or not set(outputs) <= OUTPUTS:
            raise ModuleError(f"{mid}: outputs must be a list from {sorted(OUTPUTS)}")
        sensors = {name: _sensor(mid, name, s) for name, s in raw["sensors"].items()}
        modules[mid] = ModuleSpec(mid, str(raw.get("type", "generic")), str(raw.get("name", mid)), sensors, tuple(outputs))
    return Config(modules)


def load(path: str | Path) -> Config:
    try:
        data = yaml.safe_load(Path(path).read_text())
    except OSError as e:
        raise ModuleError(f"cannot read {path}: {e}") from e
    except yaml.YAMLError as e:
        raise ModuleError(f"{path}: invalid YAML: {e}") from e
    return parse(data)


# The original door module, used when no description file is given (tests, selftest).
DEFAULT_DOOR = parse({"modules": {"door-1": {
    "type": "entry", "name": "Door",
    "sensors": {"door": {"kind": "contact", "role": "entry"},
                "pir": {"kind": "motion", "role": "entry"},
                "lid": {"kind": "tamper", "role": "tamper"}},
    "outputs": ["buzzer", "led"]}}}).modules["door-1"]


def door_module(node_id: str) -> ModuleSpec:
    """The default door module under another id."""
    return ModuleSpec(node_id, DEFAULT_DOOR.type, node_id, DEFAULT_DOOR.sensors, DEFAULT_DOOR.outputs)
