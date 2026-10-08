# Modules

The system is a **core** (the Docker stack: alarm-core, API, camera, notifier…) with **modules** plugged into it. A field module is a device in the house: an ESP, or a simulated one. Each module is described once, in [`config/modules.yaml`](../config/modules.yaml), and the core handles every sensor by the **role** it's given there, never by name.

**A new kind of module needs a description, not new core code.** `test_a_module_the_core_has_never_seen` checks this with a made-up "vault" module.

## The description

```yaml
modules:
  env-1:                      # module id: 1-16 chars of a-z, 0-9, -
    type: environment         # free text, shown on the dashboard
    name: Kitchen             # display name
    sensors:
      gas:  {kind: gas,         role: safety,    unit: ppm, alarm_above: 400, normal: 120, label: Gas}
      temp: {kind: temperature, role: safety,    unit: °C,  alarm_above: 57,  normal: 21}
      hum:  {kind: humidity,    role: telemetry, unit: "%", normal: 45}
      lid:  {kind: tamper,      role: tamper}
    outputs: [buzzer, led]    # what the core may switch on this module
```

| Sensor key | Required | Meaning |
|---|---|---|
| `kind` | yes | What it measures. `contact`, `motion`, `tamper`, `smoke`, `water`, `vibration`, `button` and `glass_break` are **on/off**; anything else is **numeric**. Force it with `binary: true/false`. |
| `role` | yes | What the core does with it (table below) |
| `unit` | no | Shown next to numeric readings |
| `alarm_above` / `alarm_below` | numeric alarming sensors | The threshold that makes the sensor **active** |
| `normal` | no | Typical reading: the simulator's starting value and its "Normal" button |
| `label` | no | Display name (defaults to the sensor name) |
| `confirm` | no | `person` (entry and instant sensors only): while armed, the camera must see someone before the sensor counts. No person → dismissed; no verdict within 8 s → counts anyway. |

A sensor is **active** when an on/off sensor reports `1`, or a numeric one crosses its threshold.

## Roles

| Role | When active | Typical sensors |
|---|---|---|
| `entry` | While armed: starts the entry delay | Front door, hallway motion |
| `instant` | While armed or in the entry delay: alarm immediately. Arming is refused while one is active. | Windows, a safe's vibration sensor |
| `tamper` | Not disarmed: alarm immediately. Disarmed: a `tamper` warning only, so the box can be opened for maintenance. Arming is refused while one is active. | Enclosure lid |
| `safety` | **Whatever the arm state:** a safety alarm, separate from intrusion. Every module's buzzer sounds until someone enters a code (Disarm), which silences it. It stays listed until the reading is back to normal, and arming is refused meanwhile. A new safety alarm sounds again. | Gas, smoke, water leak, overheating |
| `telemetry` | Never active: shown and charted only | Humidity, light, CO₂ |

The description is validated at startup. A numeric `safety`/`entry`/`instant`/`tamper` sensor without a threshold, a threshold on a `telemetry` sensor, or an unknown key or role all stop alarm-core with a clear message.

## Adding a module: checklist

1. **Describe it** in `config/modules.yaml`.
2. **Give it a key:** `scripts/dev-secrets.sh`, which creates one for every module in the file, then restart the broker: `docker compose -f infra/docker/compose.yml restart mosquitto`.
3. **Simulate it** (no hardware needed): add a container to the `sim` profile in [`infra/docker/compose.yml`](../infra/docker/compose.yml), copying `env-1`, or run `.venv/bin/python -m alarm_sim node --node <id>`. The simulator builds the module's sensors from its description.
4. **Restart alarm-core** (or `scripts/sim.sh up`). It refuses to start if a module has no key.
5. **Check:**
   - The **dashboard** draws the module from its description: on/off tiles, numeric readings with a chart and their threshold, and simulator controls for every sensor.
   - **Grafana** charts its readings (`alarm_node_sensor_value`), with no dashboard change.
   - **Phone alerts** cover its safety alarms.
6. **For real hardware:** the firmware sends the same sensor names in its heartbeats (below).

Remember: **every module in the file must be online to arm.** That's deliberate, so a missing module isn't a silent blind spot. Remove modules you don't run.

## On the wire

Field modules speak [protocol v1](../protocol/spec.md). Each heartbeat carries **every** sensor in the description, and changes are sent at once as `EVT`:

```
door=0,pir=0,lid=0,up=812,rssi=-61          door-1
gas=121.4,temp=21.1,hum=45.3,lid=0,...       env-1
```

- On/off values are `0` / `1`. Numeric values are plain decimals (`21.4`, `-3.0`), with no unit.
- Sensor names must match the description exactly (`[a-z][a-z0-9_]{0,15}`).
- Values the core can't read (`lots`, `2` for an on/off sensor) are ignored and the last good value is kept.

## Implementations

| Language | Where | Used by |
|---|---|---|
| Python | [protocol/python](../protocol/python) | The core, and the Python simulator (any module, from its description) |
| C++17 | [protocol/cpp](../protocol/cpp) | The edge simulator as env-1 (`ENV_NODE=cpp scripts/sim.sh up`), and the base for the ESP firmware |

Both are tested against [`protocol/test-vectors.json`](../protocol/test-vectors.json).

## Not yet

- **Core modules** (camera, detector…) aren't declared in this file yet. They run as Docker services; declaring them, so their health shows up the same way, is roadmap step 2.5.
- **Changing the file needs an alarm-core restart.** There's no hot reload.
- **Hysteresis:** a reading hovering right at its threshold can flip on and off. Add `clear_below`/`clear_above` if a real sensor needs it.
