# simulator

Fake ESP8266 sensor nodes that speak [protocol v1](../protocol/spec.md) over MQTT, plus an attacker and a minimal dev hub. Use it to develop and test everything on the Pi side before the hardware exists.

```
alarm_sim/
  node.py       simulated node: handshake, heartbeats, events, commands, jamming/reboot
  attacks.py    replay, spoofing, tampering, forged HELLO, injected CMD, flooding
  devhub.py     minimal hub that only prints what it sees (alarm-core is the real one)
  scenario.py   YAML timeline runner and expectation checks
scenarios/      intrusion, cat, lid_tamper, jamming, replay_attack, spoofing, session_attacks
```

## Setup

All commands run from the repo root, using one shared virtual environment:

```bash
python3 -m venv .venv
.venv/bin/pip install -e protocol/python -e 'simulator[dev]'
```

## Offline (no broker needed)

Runs every scenario against the in-memory hub on a fake clock. It takes under a second, and it's what CI runs.

```bash
.venv/bin/python -m alarm_sim selftest          # all scenarios, PASS/FAIL
.venv/bin/python -m alarm_sim selftest -v simulator/scenarios/replay_attack.yaml   # full log
.venv/bin/pytest simulator
```

## Live, over the real broker

```bash
scripts/dev-secrets.sh                                   # once: keys + broker passwords
docker compose -f infra/docker/compose.dev.yml up -d     # Mosquitto on 127.0.0.1:1883
```

Then, in two terminals:

```bash
.venv/bin/python -m alarm_sim hub                        # terminal 1: dev hub (or alarm_core run)
.venv/bin/python -m alarm_sim node                       # terminal 2: interactive node
```

With `--headless` the node takes no terminal input and is driven from the dashboard's simulator panel instead (see [web/README.md](../web/README.md)). Either way, it listens on the dev-only topic `sim/<node>/cmd` and reports on `sim/<node>/status` ([control.py](alarm_sim/control.py)).

Node commands: `door 1`, `pir 1`, `lid 1`, `jam 6`, `reboot`, `attack replay`, `attack spoof`, `attack inject_cmd`, `status`, `help`. In the hub terminal: `cmd door-1 buzzer=1`.

To play a scenario live instead: `.venv/bin/python -m alarm_sim node --scenario simulator/scenarios/jamming.yaml`.

You can watch the raw traffic, and see that it's unreadable:

```bash
docker compose -f infra/docker/compose.dev.yml exec mosquitto \
  mosquitto_sub -u attacker -P "$(jq -r .attacker.password .secrets/dev.json)" -t 'alarm/v1/#' -v
```

## Writing scenarios

```yaml
name: my_scenario
duration: 12
steps:
  - at: 3
    say: text printed in the log
    set: {door: 1}                 # sensors: door, pir, lid
  - at: 5
    attack: replay                 # see attacks.py ATTACKS
    args: {type: EVT, index: 0}
  - at: 6
    jam: 5                         # seconds of radio silence
  - at: 8
    reboot: 1                      # seconds offline
expect:                            # checked by selftest
  hub: [link_lost]                 # events that must happen
  hub_absent: [auth_fail]          # events that must not happen
  node: [auth_fail]                # rejections recorded by the node
```

Hub event names: `msg`, `session_pending`, `session_started`, `link_lost`, `link_restored`, `auth_fail`, `replay`, `malformed`, `unknown_session`, `rate_limited`, `unknown_node`.

## How it differs from the real node

- `jam` stops traffic but keeps the TCP connection, then starts a new session. A real deauth would drop the connection; the result on the hub side is the same.
- The `attacker` broker account (dev ACL only) stands in for someone who sniffed broker passwords off the Wi-Fi. Without it, the broker's ACL would block some attacks before the protocol even sees them.
