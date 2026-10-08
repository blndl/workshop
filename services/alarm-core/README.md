# alarm-core

The alarm's brain on the Pi. It talks to the sensor nodes through the protocol `Hub` (encrypted MQTT), runs the state machine, drives the nodes' buzzer and LED, and publishes events for the other services (log, camera, notifier, dashboard).

```
alarm_core/
  machine.py   state machine (pure logic, fully unit-tested)
  codes.py     hashed codes, duress code, brute-force lockout
  eventlog.py  tamper-evident event log (HMAC hash chain)
  service.py   MQTT wiring: nodes <-> machine <-> control/events topics
  __main__.py  CLI: run, ctl, watch, hash-code
```

## States

```
DISARMED --arm--> ARMING --exit delay--> ARMED --entry sensor--> ENTRY_DELAY --entry delay--> TRIGGERED
   ^                                                                                              |
   +---------------------------------------- disarm (from any state) ----------------------------+
```

Sensors are handled by the **role** their module description gives them (`config/modules.yaml`, see [docs/modules.md](../../docs/modules.md)), not by name:

| Situation | What happens |
|---|---|
| `entry` sensor active while ARMED | ENTRY_DELAY (30 s by default) to type the code |
| Entry delay runs out | TRIGGERED: siren on every module, LED `alarm` |
| `instant` sensor active while ARMED or in ENTRY_DELAY | TRIGGERED immediately |
| `tamper` sensor active while not DISARMED | TRIGGERED immediately |
| `tamper` sensor active while DISARMED | `tamper` event only, so the box can be opened for maintenance |
| `safety` sensor active (gas, smoke…), **in any state** | Safety alarm (`safety_alarm`): buzzers on until a code silences it (`safety_silenced`); stays listed until the reading is back to normal (`safety_clear`) |
| A module goes silent for 3 s while ARMING, ARMED or ENTRY_DELAY | TRIGGERED immediately (fail-secure: jamming, cut power, smashed module) |
| Siren on for 3 min | Siren stops (`siren_timeout`); the state stays TRIGGERED until disarmed |
| Arming while a module is offline, a `tamper`/`instant` sensor is active, or a safety alarm is on | Refused (`arm_refused`, with the reasons) |
| Duress code | Disarms exactly like the normal code, plus a silent `duress` event |
| 5 wrong codes within 5 min | Every code refused for 5 min, even the right one (`code_lockout`) |

### Vision: "motion needs a person"

A sensor marked `confirm: person` in `config/modules.yaml` (door-1's motion sensor) doesn't count straight away while armed:

1. alarm-core emits `verify`, and the camera takes a burst of 3 photos (`verify-1..3`).
2. The detector analyses each photo, and alarm-core logs every result (`detection`).
3. **A person on any photo** → `motion_confirmed`, and the sensor counts (entry delay, reason "pir (person seen)").
4. **Nobody on all 3** → `motion_dismissed` (with what *was* seen, e.g. a cat): a false alarm avoided, and the system stays armed.
5. **No answer within 8 s** (detector down, no model, too slow) → `verify_timeout`, and the sensor counts anyway: fail-secure.

The door contact never waits for the camera.

### Live view

`{"action": "live_view", "on": true}` on `alarm/control` turns the camera on while disarmed, for 2 minutes at most, so someone can look. Every start and stop is a logged `live_view` event, so the log shows who looked at the camera and when.

Sensor activity during ARMING is ignored, so you can walk out through the door. Intrusion and safety alarms are independent: gas doesn't start an intrusion, and disarming doesn't make the gas go away.

`--modules` picks the description file (default `config/modules.yaml`). alarm-core refuses to start if the file is invalid or a module has no key.

## Topics

| Topic | Direction | Content |
|---|---|---|
| `alarm/v1/<node>/up` / `down` | nodes ↔ alarm-core | Encrypted protocol traffic ([spec](../../protocol/spec.md)) |
| `alarm/control` | clients → alarm-core | `{"action": "arm"\|"disarm"\|"status"\|"live_view", "code": "1234", "on": true, "source": "cli", "req": "a1b2"}` |
| `alarm/detections` | detector → alarm-core | One result per photo; re-emitted as a logged `detection` event |
| `alarm/events` | alarm-core → services | One JSON event per message |
| `alarm/state` | alarm-core → services | Retained snapshot, republished every second: state, reason, siren, countdown, active `safety` alarms and `safety_silenced`, and per module `type`, `name`, `online`, `sensors` (latest values), `active`, `info` (each sensor's description), `rssi` (dBm), `uptime` (s), `seen_ago` (s), `security` (rejected messages by kind) |

The internal topics are protected only by broker accounts (see [acl](../../infra/docker/mosquitto/acl)): the nodes and the dev `attacker` account can't reach them. On the Pi the broker isn't exposed beyond the Docker network and the IoT interface. This is a trust boundary to cover in the threat model.

### Events

Every event has `ts` (Unix time) and `type`. If it answers a control request, it also carries that request's `req`.

| `type` | Fields | Meaning |
|---|---|---|
| `state` | `state`, `prev`, `reason`, `node`?, `delay`? | State changed (`delay` = seconds until the next automatic change) |
| `sensor` | `node`, `sensor`, `value`, `active` | An on/off sensor changed, or a numeric one crossed its threshold (numeric readings themselves are in `alarm/state`) |
| `safety_alarm` | `node`, `sensor`, `kind`, `value`, `unit`, `threshold` | A safety sensor became active |
| `safety_silenced` | `source`, `alarms` | A code silenced the safety alarm(s) |
| `safety_clear` | `node`, `sensor`, `value` | A safety sensor is back to normal |
| `tamper` | `node`, `sensor` | Enclosure opened while disarmed |
| `node_online` / `link_lost` | `node` | Node link came up / went silent for 3 s |
| `security` | `node`, `kind` (`auth_fail`/`replay`), `detail` | Rejected forged or replayed message |
| `bad_code` / `code_lockout` / `code_locked` | `action`, `source` | Wrong code / lockout started / attempt during lockout |
| `arm_refused` | `source`, `problems` | Why arming was refused |
| `duress` | `action`, `source` | **Never display this on any local screen.** It goes to the notifier only. |
| `siren_timeout` | `seconds` | Siren switched off after the legal maximum |
| `verify` | `node`, `sensor`, `timeout` | Motion on a `confirm: person` sensor: waiting for the camera |
| `detection` | `path`, `reason`, `person`, `confidence`, `objects`, `boxes`, `latency_ms` | What the detector saw on a photo (logged) |
| `motion_confirmed` | `node`, `sensor`, `confidence`, `path` | A person was seen: the sensor counts |
| `motion_dismissed` | `node`, `sensor`, `seen` | Nobody on the burst: false alarm avoided |
| `verify_timeout` | `node`, `sensor`, `answers` | No verdict in time: the sensor counts anyway |
| `live_view` | `on`, `seconds`?, `source` | Live view started or stopped (`source: timeout` when it ends by itself) |
| `status` | the snapshot | Reply to `{"action": "status"}` |
| `control_done` | `action` | Last event for **every** control request: the request was handled. Callers wait for it instead of guessing with a timeout, and it makes a duress disarm indistinguishable from a normal one. Not written to the log. |

## Tamper-evident event log

Every event (except `status` replies) is appended to `data/events.jsonl`. Each line holds the previous line's MAC:

```
{"seq": 5, "prev": "<mac of record 4>", "event": {...}, "mac": HMAC-SHA256(log_key, seq+prev+event)}
```

| Attack on the log | Detected? |
|---|---|
| Edit a record (e.g. door `1` to `0`) | ✅ its MAC no longer matches |
| Delete or insert a record | ✅ the seq/prev chain breaks |
| Reorder records | ✅ |
| Rebuild the whole chain after editing | ✅ needs `log_key`, which isn't in the log |
| Cut records off the end | ✅ only against a known head; alarm-core publishes `{"seq", "head"}` in `alarm/state` so a copy elsewhere (notifier, off-site backup) can check it |
| Delete the whole file | ✅ against a known head |
| Steal the SD card **with** the secrets file | ❌ the key is on the same card. Mitigations: off-site copy of the heads/log (phase 5), or a TPM/secure element |

alarm-core verifies the whole chain **at every startup** and emits `log_tampered` if it's broken. Check it by hand at any time:

```bash
.venv/bin/python -m alarm_core verify-log
.venv/bin/python -m alarm_core verify-log --head 42:fb9eb4b1fc50b5fa   # also catch truncation
```

**Demo:** arm, trigger, disarm. Then edit a line of `data/events.jsonl` (for example `sed -i '' '4s/"value": "1"/"value": "0"/' data/events.jsonl`) and run `verify-log` again.

## Running it

From the repo root, with the broker up (see [simulator/README.md](../../simulator/README.md)):

```bash
.venv/bin/pip install -e services/alarm-core

# terminal 1: alarm-core (short delays for testing)
.venv/bin/python -m alarm_core run --exit-delay 5 --entry-delay 10

# terminal 2: a simulated node
.venv/bin/python -m alarm_sim node

# terminal 3: control it
.venv/bin/python -m alarm_core ctl arm 1234
.venv/bin/python -m alarm_core ctl status
.venv/bin/python -m alarm_core ctl disarm 1234
.venv/bin/python -m alarm_core watch          # live event feed
```

Dev codes (from `scripts/dev-secrets.sh`): **1234** is the user code, **9999** the duress code. To set real codes, run `python -m alarm_core hash-code` and put the hashes in the secrets file under `codes.user` / `codes.duress`.

`alarm_core run` replaces `alarm_sim hub`. Both log in as `hub`, so run only one of them at a time.

## Tests

```bash
.venv/bin/pytest services/alarm-core
```

`test_machine.py` covers the state machine alone. `test_service.py` runs the real service against the simulated node and attacker on an in-memory bus: a full intrusion, disarming in time, jamming while armed, a spoofed "door closed", garbage control messages, and a lost command repaired by the keepalive.

## Not done yet

- **Config file:** delays are CLI flags, and codes live in the secrets file.
- **Partial arming** ("home" mode that ignores the PIR) and per-sensor zones.
