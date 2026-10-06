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
DISARMED --arm--> ARMING --exit delay--> ARMED --door/pir--> ENTRY_DELAY --entry delay--> TRIGGERED
   ^                                                                                         |
   +----------------------------------- disarm (from any state) ----------------------------+
```

| Situation | What happens |
|---|---|
| `door` or `pir` goes to 1 while ARMED | ENTRY_DELAY (30 s by default) to type the code |
| Entry delay runs out | TRIGGERED: siren on all nodes, LED `alarm` |
| `lid` opened while not DISARMED | TRIGGERED immediately (tamper) |
| `lid` opened while DISARMED | `tamper` event only, so the box can be opened for maintenance |
| A node goes silent for 3 s while ARMING, ARMED or ENTRY_DELAY | TRIGGERED immediately (fail-secure: jamming, cut power, smashed node) |
| Siren on for 3 min | Siren stops (`siren_timeout`); the state stays TRIGGERED until disarmed |
| Arming while a node is offline or a lid is open | Refused (`arm_refused`, with the reasons) |
| Duress code | Disarms exactly like the normal code, plus a silent `duress` event |
| 5 wrong codes within 5 min | Every code refused for 5 min, even the right one (`code_lockout`) |

Sensor activity during ARMING is ignored, so you can walk out through the door.

## Topics

| Topic | Direction | Content |
|---|---|---|
| `alarm/v1/<node>/up` / `down` | nodes ↔ alarm-core | Encrypted protocol traffic ([spec](../../protocol/spec.md)) |
| `alarm/control` | clients → alarm-core | `{"action": "arm"\|"disarm"\|"status", "code": "1234", "source": "cli", "req": "a1b2"}` |
| `alarm/events` | alarm-core → services | One JSON event per message |
| `alarm/state` | alarm-core → services | Retained snapshot, republished every second: state, reason, siren, countdown, and per node `online`, `sensors`, `rssi` (dBm), `uptime` (s), `seen_ago` (s), `security` (rejected messages by kind) |

The internal topics are protected only by broker accounts (see [acl](../../infra/docker/mosquitto/acl)): the nodes and the dev `attacker` account can't reach them. On the Pi the broker isn't exposed beyond the Docker network and the IoT interface. This is a trust boundary to cover in the threat model.

### Events

Every event has `ts` (Unix time) and `type`. If it answers a control request, it also carries that request's `req`.

| `type` | Fields | Meaning |
|---|---|---|
| `state` | `state`, `prev`, `reason`, `node`?, `delay`? | State changed (`delay` = seconds until the next automatic change) |
| `sensor` | `node`, `sensor`, `value` | A sensor changed |
| `tamper` | `node`, `sensor` | Enclosure opened while disarmed |
| `node_online` / `link_lost` | `node` | Node link came up / went silent for 3 s |
| `security` | `node`, `kind` (`auth_fail`/`replay`), `detail` | Rejected forged or replayed message |
| `bad_code` / `code_lockout` / `code_locked` | `action`, `source` | Wrong code / lockout started / attempt during lockout |
| `arm_refused` | `source`, `problems` | Why arming was refused |
| `duress` | `action`, `source` | **Never display this on any local screen.** It goes to the notifier only. |
| `siren_timeout` | `seconds` | Siren switched off after the legal maximum |
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
